#!/usr/bin/env python3
"""Live data in the web browser: the same MUT-II polling as mut_gui, served as a web page.

  python mut_web.py                                        # cable picked automatically, opens the browser
  python mut_web.py --backend sim --sim mutlive --connect  # demo without a car
  python mut_web.py --lan                                  # also reachable from a phone on the same network

The page (web/) talks to this server only through the API in web/API.md, so the same page
can later be served by a Raspberry Pi Pico W. Read-only like the other tools: every request
to the ECU passes proto.check_mut().
"""

import argparse
import json
import queue
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from kkl import __version__, dtcdefs, piddefs, proto
from kkl.interfaces import AUTO, cli_key, list_interfaces, open_interface
from kkl.livepoll import Poller

# Next to the .exe when frozen by PyInstaller (not its temp dir); the page itself is bundled.
HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent
WEB = Path(getattr(sys, "_MEIPASS", HERE)) / "web"
DEFS_DEFAULT, DEFS_LEGACY = HERE / "pid_definitions.csv", HERE / "pid_definicje.csv"
DTC_DEFS = HERE / "dtc_definitions.csv"
FIRST_LIST = "07,14,15,17,21,3A,40,45"
STATIC = {"/": ("index.html", "text/html"), "/index.html": ("index.html", "text/html"),
          "/app.js": ("app.js", "text/javascript"), "/style.css": ("style.css", "text/css")}


def hx(pid):
    return f"{pid:02X}"


class Hub:
    """State shared by the poller thread, the HTTP handlers and the event-stream clients."""

    def __init__(self, iface, defs_path=None, init_mode="auto"):
        self.lock = threading.RLock()
        self.init_mode = init_mode
        self.clients = set()
        self.iface, self.poller = iface, None
        self.status = {"code": "idle", "detail": "", "ecu_id": "", "iface": ""}
        self.values, self.pending, self.rate = {}, {}, None
        self.defs_path = Path(defs_path) if defs_path else (
            DEFS_LEGACY if not DEFS_DEFAULT.exists() and DEFS_LEGACY.exists() else DEFS_DEFAULT)
        self.defs, self.keep, self.defs_mtime = {}, [], None
        self.load_defs()
        self.pids = [p for p, d in sorted(self.defs.items()) if d.active] or piddefs.parse_pids(FIRST_LIST)[0]
        dtcdefs.load(DTC_DEFS)
        threading.Thread(target=self._flusher, daemon=True).start()

    # -- definitions file (shared with mut_gui) ------------------------------------------
    def load_defs(self):
        if self.defs_path.exists():
            self.defs, _problems, self.keep, _legacy = piddefs.load_defs(self.defs_path)
            self.defs_mtime = self.defs_path.stat().st_mtime
        else:
            first = set(piddefs.parse_pids(FIRST_LIST)[0])
            self.defs = {d.pid: replace(d, active=d.pid in first) for d in piddefs.DEFAULTS}
            self._save_defs()

    def _save_defs(self):
        piddefs.save_defs(self.defs_path, self.defs, self.keep)
        self.defs_mtime = self.defs_path.stat().st_mtime

    def defs_json(self):
        with self.lock:
            pids = {hx(p): {"name": d.name, "conv": d.conv, "unit": d.unit, "active": d.active}
                    for p, d in sorted(self.defs.items())}
        return {"pids": pids, "dtc": [{"bit": b, "code": c, "desc": s} for b, c, s in dtcdefs.table()]}

    def update_def(self, pid, name, conv, unit):
        piddefs.compile_conversion(conv)  # ValueError -> HTTP 400
        with self.lock:
            d = self.defs.setdefault(pid, piddefs.PidDef(pid, active=pid in self.pids))
            d.name, d.conv, d.unit = name.replace(";", ","), conv, unit.replace(";", ",")
            self._save_defs()
        self.publish({"type": "defs"})

    # -- polled list ----------------------------------------------------------------------
    def set_pids(self, pids, temporary=False):
        with self.lock:
            self.pids = list(pids)
            self.values = {p: self.values.get(p) for p in self.pids}
            if self.poller:
                self.poller.set_pids(self.pids)
            if not temporary:
                for p, d in self.defs.items():
                    d.active = p in self.pids
                for p in self.pids:
                    self.defs.setdefault(p, piddefs.PidDef(p, active=True))
                self._save_defs()
        self.publish({"type": "pids", "pids": [hx(p) for p in pids]})

    # -- connection -------------------------------------------------------------------------
    def connect(self, iface=None):
        with self.lock:
            if self.poller and self.poller.is_alive():
                return
            if iface:
                self.iface = iface
            key = self.iface
            self.poller = Poller(lambda: open_interface(key), self.pids, self.on_poller, self.init_mode)
            self.poller.start()

    def disconnect(self, wait=0.0):
        with self.lock:
            p = self.poller
        if p:
            p.stop()
            if wait:
                p.join(wait)

    def on_poller(self, kind, *args):
        """Called from the poller thread."""
        with self.lock:
            st = self.status
            if kind == "val":
                self.values[args[0]] = self.pending[args[0]] = args[1]
                return
            if kind == "rate":
                self.rate = {"reads": round(args[0], 1), "cycle": round(args[1], 3)}
                msg = {"type": "rate", **self.rate}
            elif kind == "iface":
                st["iface"] = args[0]
                return
            elif kind == "status":
                st.update(code=args[0], detail=args[1], ecu_id="")
                msg = {"type": "status", **st}
            elif kind == "connected":
                st.update(code="connected", detail=args[1], ecu_id=args[0])
                msg = {"type": "status", **st}
            elif kind == "stopped":
                self.poller, self.rate = None, None
                if st["code"] != "error":  # keep an error visible after the thread ends
                    st.update(code="idle", detail="", ecu_id="")
                msg = {"type": "status", **st}
            else:
                return
        self.publish(msg)

    # -- event stream -------------------------------------------------------------------------
    def snapshot(self):
        with self.lock:
            return {"type": "state", "status": dict(self.status), "pids": [hx(p) for p in self.pids],
                    "values": {hx(p): self.values.get(p) for p in self.pids}, "rate": self.rate}

    def subscribe(self, q):
        with self.lock:
            self.clients.add(q)
            return self.snapshot()

    def unsubscribe(self, q):
        with self.lock:
            self.clients.discard(q)

    def publish(self, msg):
        data = json.dumps(msg)
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(data)
            except queue.Full:  # a stalled client: start it over from a fresh snapshot
                while not q.empty():
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                q.put_nowait(json.dumps(self.snapshot()))

    def _flusher(self):
        """Batch values every 100 ms; notice edits of the definitions file (mut_gui, Notepad)."""
        last_check = 0.0
        while True:
            time.sleep(0.1)
            with self.lock:
                batch, self.pending = self.pending, {}
            if batch:
                self.publish({"type": "values", "t": int(time.time() * 1000),
                              "v": {hx(p): v for p, v in batch.items()}})
            if time.monotonic() - last_check >= 2.0:
                last_check = time.monotonic()
                try:
                    changed = self.defs_path.stat().st_mtime != self.defs_mtime
                except OSError:
                    changed = False
                if changed:
                    with self.lock:
                        self.load_defs()
                    self.publish({"type": "defs"})


class Handler(BaseHTTPRequestHandler):
    hub = None
    server_version = f"mitsu-kkl/{__version__}"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self):
        # Requiring a JSON content type makes browsers preflight cross-site requests, which this
        # server never approves - so another web page cannot drive it.
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            raise PermissionError("Content-Type must be application/json")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 65536:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        path, hub = self.path.split("?", 1)[0], self.hub
        if path in STATIC:
            name, ctype = STATIC[path]
            f = WEB / name
            return self._send(200, f.read_bytes(), ctype) if f.is_file() else self._send(404, {"error": name})
        if path == "/api/info":
            ifaces = [{"key": i.key, "label": i.label} for i in list_interfaces()]
            if not any(i["key"] == hub.iface for i in ifaces):  # e.g. the simulator from the command line
                kind, _, arg = hub.iface.partition(":")
                ifaces.append({"key": hub.iface, "label": f"simulator ({arg})" if kind == "sim" else hub.iface})
            return self._send(200, {"version": __version__, "server": "pc", "ifaces": ifaces, "iface": hub.iface})
        if path == "/api/state":
            return self._send(200, hub.snapshot())
        if path == "/api/defs":
            return self._send(200, hub.defs_json())
        if path == "/api/events":
            return self._events()
        self._send(404, {"error": "not found"})

    def do_POST(self):
        self._change("POST")

    def do_PUT(self):
        self._change("PUT")

    def _change(self, method):
        path, hub = self.path.split("?", 1)[0], self.hub
        try:
            body = self._json_body()
            if method == "POST" and path == "/api/connect":
                hub.connect(body.get("iface"))
            elif method == "POST" and path == "/api/disconnect":
                hub.disconnect()
            elif method == "POST" and path == "/api/pids":
                text = body["text"] if "text" in body else ",".join(body.get("pids", []))
                pids, rejected = piddefs.parse_pids(text)
                hub.set_pids(pids, bool(body.get("temporary")))
                return self._send(200, {"pids": [hx(p) for p in pids], "rejected": rejected})
            elif method == "PUT" and path == "/api/defs":
                pids, rejected = piddefs.parse_pids(str(body.get("pid", "")))
                if len(pids) != 1 or rejected:
                    raise ValueError(f"PID {body.get('pid')} is not readable (allowed: 00-BF, FD-FF)")
                hub.update_def(pids[0], str(body.get("name", "")), str(body.get("conv", "")).strip(),
                               str(body.get("unit", "")))
            else:
                return self._send(404, {"error": "not found"})
        except PermissionError as e:
            return self._send(415, {"error": str(e)})
        except (ValueError, KeyError, TypeError) as e:
            return self._send(400, {"error": str(e)})
        self._send(200, {"ok": True})

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue(maxsize=1000)
        try:
            data = json.dumps(self.hub.subscribe(q))
            while True:
                self.wfile.write(f"data: {data}\n\n".encode() if data else b": ping\n\n")
                self.wfile.flush()
                try:
                    data = q.get(timeout=15)
                except queue.Empty:
                    data = None
        except OSError:  # the browser went away
            pass
        finally:
            self.hub.unsubscribe(q)


def lan_addresses():
    try:
        return [a for a in socket.gethostbyname_ex(socket.gethostname())[2] if not a.startswith("127.")]
    except OSError:
        return []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"mitsu-kkl {__version__}")
    ap.add_argument("--backend", choices=("auto", "d2xx", "serial", "sim"), help="default: auto")
    ap.add_argument("--sim", default="mutlive", help="simulator model for --backend sim")
    ap.add_argument("--port", help="cable COM port, e.g. COM5 (implies --backend serial)")
    ap.add_argument("--dev", type=int, help="D2XX device index (implies --backend d2xx)")
    ap.add_argument("--serial", help="D2XX: open by FTDI serial number (implies --backend d2xx)")
    ap.add_argument("--connect", action="store_true", help="connect to the ECU right after start")
    ap.add_argument("--http-port", type=int, default=8080, help="web server port (default 8080)")
    ap.add_argument("--lan", action="store_true", help="accept connections from other devices on the network")
    ap.add_argument("--no-browser", action="store_true", help="don't open the browser")
    ap.add_argument("--defs", help="PID definitions file (default: the one mut_gui uses)")
    ap.add_argument("--init", choices=proto.INIT_MODES, default="auto",
                    help="ECU init: mut = MUT-II 0x00 (EU cars, Evo), obd = OBD-II 0x33 (US cars, "
                         "like EvoScan's DSM mode), auto = both in turn (default)")
    args = ap.parse_args()

    key = cli_key(args.backend, args.dev, args.serial, args.port, args.sim) or AUTO
    hub = Handler.hub = Hub(key, args.defs, args.init)
    server = ThreadingHTTPServer(("0.0.0.0" if args.lan else "127.0.0.1", args.http_port), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{args.http_port}/"
    print(f"mitsu-kkl {__version__} web viewer: {url}")
    if args.lan:
        for a in lan_addresses():
            print(f"  from other devices: http://{a}:{args.http_port}/")
    print("Ctrl+C stops the server.")
    if args.connect:
        hub.connect()
    if not args.no_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        hub.disconnect(wait=3.0)
        server.server_close()


if __name__ == "__main__":
    main()
