# Minimal asyncio HTTP server for the Pico: serves web/ and implements web/API.md
# (the same contract as mut_web.py on the PC), including the Server-Sent Events stream.
import asyncio
import json
import os

from hub import hx, parse_pids

STATIC = {"/": ("web/index.html", "text/html"), "/index.html": ("web/index.html", "text/html"),
          "/app.js": ("web/app.js", "text/javascript"), "/style.css": ("web/style.css", "text/css")}
REASONS = {200: "OK", 400: "Bad Request", 404: "Not Found", 405: "Method Not Allowed",
           413: "Payload Too Large", 415: "Unsupported Media Type", 500: "Internal Server Error"}


def head(code, ctype, length=None, extra=""):
    h = "HTTP/1.0 %d %s\r\nContent-Type: %s; charset=utf-8\r\nCache-Control: no-store\r\n" % (
        code, REASONS.get(code, ""), ctype)
    if length is not None:
        h += "Content-Length: %d\r\n" % length
    return (h + extra + "\r\n").encode()


async def send_json(w, code, obj):
    body = json.dumps(obj).encode()
    w.write(head(code, "application/json", len(body)) + body)
    await w.drain()


async def send_file(w, path, ctype):
    try:
        size = os.stat(path)[6]
    except OSError:
        return await send_json(w, 404, {"error": path})
    w.write(head(200, ctype, size))
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            w.write(chunk)
            await w.drain()


async def events(w, hub):
    w.write(head(200, "text/event-stream"))
    c = hub.subscribe()
    try:
        w.write(b"data: " + json.dumps(hub.snapshot()).encode() + b"\n\n")
        await w.drain()
        while True:
            try:
                await asyncio.wait_for(c.ev.wait(), 15)
            except asyncio.TimeoutError:
                w.write(b": ping\n\n")
                await w.drain()
                continue
            c.ev.clear()
            msgs, c.msgs = c.msgs, []
            for m in msgs:
                w.write(b"data: " + m + b"\n\n")
            await w.drain()
    except Exception:  # the browser went away
        pass
    finally:
        hub.unsubscribe(c)


async def change(w, hub, method, path, headers, body):
    # A JSON content type makes browsers preflight cross-site requests, which we never approve.
    if not headers.get("content-type", "").startswith("application/json"):
        return await send_json(w, 415, {"error": "Content-Type must be application/json"})
    try:
        data = json.loads((body or b"{}").decode())
        if method == "POST" and path == "/api/connect":
            hub.connect()
        elif method == "POST" and path == "/api/disconnect":
            hub.disconnect()
        elif method == "POST" and path == "/api/pids":
            text = data["text"] if "text" in data else ",".join(data.get("pids", []))
            pids, rejected = parse_pids(text)
            hub.set_pids(pids, bool(data.get("temporary")))
            return await send_json(w, 200, {"pids": [hx(p) for p in pids], "rejected": rejected})
        elif method == "PUT" and path == "/api/defs":
            pids, rejected = parse_pids(str(data.get("pid", "")))
            if len(pids) != 1 or rejected:
                raise ValueError("PID %s is not readable (allowed: 00-BF, FD-FF)" % data.get("pid"))
            hub.update_def(pids[0], str(data.get("name", "")), str(data.get("conv", "")).strip(),
                           str(data.get("unit", "")))
        else:
            return await send_json(w, 404, {"error": "not found"})
    except (ValueError, KeyError, TypeError) as e:
        return await send_json(w, 400, {"error": str(e)})
    await send_json(w, 200, {"ok": True})


async def handle(r, w, hub):
    stream = False
    try:
        line = await r.readline()
        if not line:
            return
        method, path = line.decode().split(" ")[:2]
        path = path.split("?")[0]
        headers = {}
        while True:
            h = await r.readline()
            if not h or h in (b"\r\n", b"\n"):
                break
            k, _, v = h.decode().partition(":")
            headers[k.strip().lower()] = v.strip()
        n = int(headers.get("content-length", "0") or 0)
        if n > 8192:
            return await send_json(w, 413, {"error": "body too large"})
        body = await r.readexactly(n) if n else b""
        if method == "GET":
            if path in STATIC:
                await send_file(w, *STATIC[path])
            elif path == "/api/info":
                await send_json(w, 200, {"version": hub.version, "server": "pico", "iface": "kline",
                                         "ifaces": [{"key": "kline", "label": hub.kl.label}]})
            elif path == "/api/state":
                await send_json(w, 200, hub.snapshot())
            elif path == "/api/defs":
                await send_json(w, 200, hub.defs_json())
            elif path == "/api/events":
                stream = True
                await events(w, hub)
            else:
                await send_json(w, 404, {"error": "not found"})
        elif method in ("POST", "PUT"):
            await change(w, hub, method, path, headers, body)
        else:
            await send_json(w, 405, {"error": "method not allowed"})
    except Exception as e:
        if not stream:
            try:
                await send_json(w, 500, {"error": "%s: %s" % (type(e).__name__, e)})
            except Exception:
                pass
    finally:
        try:
            w.close()
            await w.wait_closed()
        except Exception:
            pass


async def serve(hub, port):
    return await asyncio.start_server(lambda r, w: handle(r, w, hub), "0.0.0.0", port)
