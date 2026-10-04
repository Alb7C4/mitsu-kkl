#!/usr/bin/env python3
"""K-line probe for late-90s Mitsubishi ECUs (MUT-II etc.) over a KKL cable.

  python kkl_probe.py info                       # interfaces, FTDI chip, driver, EEPROM (no TX)
  python kkl_probe.py --port COM5 selftest       # a cable on another chip, through its COM port
  python kkl_probe.py selftest                   # echo / loopback: is the cable powered?
  python kkl_probe.py scan [--full]              # matrix of init methods / speeds / addresses
  python kkl_probe.py mut --addr 00 --ack        # single MUT-II attempt
  python kkl_probe.py mut --addr 00 --repeat 50  # live values once it connects
  python kkl_probe.py iso | kwpfast | dsm | listen | addrscan
  python kkl_probe.py report                     # summary of logs/attempts.jsonl

Interface: auto by default (FTDI via D2XX, else the first FTDI/CH340/PL2303/CP210x COM
port); force one with --backend d2xx|serial|sim or just --port COMx.

Hex values (addresses, request bytes) are always hex: --addr 33 == 0x33.
Only read-only requests can be sent; see kkl/proto.py for the whitelist.
"""

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from kkl import __version__, proto
from kkl.interfaces import AUTO, cli_key, list_interfaces, open_interface
from kkl.link import KLine, hires_timer, now
from kkl.log import ATTEMPTS, RunLog

# Next to the .exe when frozen by PyInstaller (not its temp dir), so logs survive.
HERE = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().parent


def hexint(s):
    return int(s, 16)


def hexlist(s):
    return tuple(int(x, 16) for x in s.replace(" ", ",").split(",") if x)


def intlist(s):
    return [int(x) for x in s.split(",") if x]


def fmt_params(params):
    out = []
    for k, v in params.items():
        if k in ("addr", "target"):
            v = f"{v:02X}"
        elif k == "queries":
            v = ",".join(f"{q:02X}" for q in v)
        elif isinstance(v, bool):
            v = int(v)
        out.append(f"{k}={v}")
    return " ".join(out)


def open_device(args):
    """Open the interface picked with --backend/--port/... (default auto); the device carries a `label`."""
    return open_interface(args.iface)


class DeviceLost(RuntimeError):
    pass


class Runner:
    def __init__(self, kl, log, gap, success_gap, reopen, latency):
        self.kl, self.log = kl, log
        self.gap, self.success_gap = gap, success_gap
        self.reopen, self.latency = reopen, latency
        self.n = 0
        self.results = []

    def _recover(self, wait=60.0):
        """The FTDI dropped off USB (FT_IO_ERROR): wait for it to re-enumerate."""
        print(f"  USB device lost - waiting up to {wait:.0f} s for it to come back...", flush=True)
        self.log.ev("device_lost")
        try:
            self.kl.dev.close()
        except Exception:
            pass
        deadline = now() + wait
        while now() < deadline:
            time.sleep(2.0)
            try:
                dev = self.reopen()
            except Exception:
                continue
            self.kl.dev = dev
            self.kl.setup(10400, self.latency)
            self.log.ev("device_back")
            print("  device is back", flush=True)
            return
        raise DeviceLost("FTDI device disappeared from USB and did not come back")

    def run(self, kind, fn, cooldown=True, **params):
        self.n += 1
        label = f"{kind} {fmt_params(params)}"
        self.log.begin(self.n, kind, params)
        t = now()
        try:
            res = fn(self.kl, self.log, **params)
        except proto.SafetyError:
            raise
        except Exception as e:  # keep the scan going, keep the traceback in the log
            res = {"outcome": "ERROR", "summary": f"{type(e).__name__}: {e}"}
            self.log.ev("exception", tb=traceback.format_exc())
        try:
            self.kl.dev.break_off()
        except Exception:
            self._recover()
        res["dur_s"] = round(now() - t, 2)
        self.log.end(kind, params, res)
        print(f"[{self.n:3}] {label:<52} -> {res['outcome']:<9} {res.get('summary', '')}", flush=True)
        self.results.append((label, res))
        if cooldown:
            good = proto.rank(res["outcome"]) >= proto.rank("HANDSHAKE")
            self.kl.sleep(self.success_gap if good else self.gap)
        return res


def scan_plan(full, backend, lline):
    P = [("listen", proto.listen, dict(baud=b, secs=1.5)) for b in (15625, 10400, 1953)]
    P += [
        ("mut", proto.mut, dict(addr=0x00, baud=15625, always_query=True)),
        ("mut", proto.mut, dict(addr=0x01, baud=15625, always_query=True)),
        ("mut", proto.mut, dict(addr=0x00, baud=15625, ack=True)),
    ]
    if backend == "d2xx":
        P.append(("mut", proto.mut, dict(addr=0x00, baud=15625, method="bitbang", always_query=True)))
    if lline:
        P.append(("mut", proto.mut, dict(addr=0x00, baud=15625, lline=lline, always_query=True)))
    P += [
        ("iso", proto.iso, dict(addr=0x33, baud=10400)),
        ("kwpfast", proto.kwpfast, dict(target=0x33, physical=False, method="byte")),
        ("kwpfast", proto.kwpfast, dict(target=0x10, physical=True, method="byte")),
        ("kwpfast", proto.kwpfast, dict(target=0x33, physical=False, method="break")),
        ("dsm", proto.dsm, dict(baud=1953)),
    ]
    if lline:
        P.append(("iso", proto.iso, dict(addr=0x33, baud=10400, lline=lline)))
    if full:
        P += [("mut", proto.mut, dict(addr=a, baud=15625)) for a in range(0x02, 0x08)]
        P += [("mut", proto.mut, dict(addr=0x00, baud=b, always_query=True))
              for b in (10400, 9600, 1953, 4800, 19200)]
        P += [("iso", proto.iso, dict(addr=0x33, baud=b)) for b in (15625, 9600)]
        P += [("mut", proto.mut, dict(addr=0x00, baud=15625, idle_ms=2500, always_query=True)),
              ("mut", proto.mut, dict(addr=0x01, baud=15625, ack=True))]
        if backend == "d2xx":
            P.append(("iso", proto.iso, dict(addr=0x33, baud=10400, method="bitbang")))
    return P


def print_table(results):
    if not results:
        return
    print("\n=== summary (best first) ===")
    for label, res in sorted(results, key=lambda r: -proto.rank(r[1]["outcome"])):
        print(f"  {res['outcome']:<9} {label}")


# ------------------------------------------------------------------ commands --
def cmd_info(args, kl, log, runner):
    from kkl import ftdi_d2xx
    from kkl.update import check_latest
    newer = check_latest()
    print(f"mitsu-kkl {__version__}" + (f" - newer version {newer[0]} available: {newer[1]}" if newer else ""))
    for i in list_interfaces()[1:]:
        print(f"interface: {i.key:<14} {i.label}")
    if kl.dev.backend == "d2xx":
        for d in ftdi_d2xx.list_devices():
            print("device:", json.dumps(d))
    info = kl.dev.info()
    print("opened:", json.dumps(info))
    log.ev("info", info=info)
    if kl.dev.backend == "d2xx":
        ee = kl.dev.read_eeprom()
        log.ev("eeprom", **ee)
        print("eeprom:", json.dumps(ee.get("decoded", ee.get("error"))))
        if "words" in ee:
            w = ee["words"]
            for i in range(0, len(w), 16):
                print(f"  {i:02X}: " + " ".join(f"{x:04X}" for x in w[i:i + 16]))


def cmd_selftest(args, kl, log, runner):
    runner.run("selftest", proto.selftest, cooldown=False)


def cmd_listen(args, kl, log, runner):
    for b in args.baud:
        runner.run("listen", proto.listen, cooldown=False, baud=b, secs=args.secs)


def _slow_common(args):
    p = dict(method=args.method, bit_ms=args.bit_ms, idle_ms=args.idle_ms)
    if args.lline:
        p["lline"] = args.lline
    return p


def cmd_mut(args, kl, log, runner):
    p = dict(addr=args.addr, baud=args.baud, ack=args.ack, always_query=args.always_query,
             **_slow_common(args))
    if args.queries is not None:
        p["queries"] = args.queries
    if args.repeat:
        p.update(repeat=args.repeat, interval=args.interval)
    for _ in range(args.tries):
        if proto.rank(runner.run("mut", proto.mut, **p)["outcome"]) >= proto.rank("DATA"):
            break


def cmd_mutdump(args, kl, log, runner):
    runner.run("mutdump", proto.mutdump, cooldown=False, addr=args.addr, baud=args.baud,
               start=args.start, end=args.end, method=args.method)


def cmd_dtc(args, kl, log, runner):
    for _ in range(args.tries):
        if runner.run("dtc", proto.dtc, cooldown=False)["outcome"] == "DATA":
            break
        kl.sleep(3.0)


def cmd_clear(args, kl, log, runner):
    if not args.yes:
        print("This sends MUT 0xCA (erase DTCs) to the engine ECU. Re-run with --yes to do it.")
        return
    runner.run("clear", proto.mut_clear, cooldown=False)


def cmd_iso(args, kl, log, runner):
    for _ in range(args.tries):
        r = runner.run("iso", proto.iso, addr=args.addr, baud=args.baud, obd=not args.no_obd,
                       **_slow_common(args))
        if proto.rank(r["outcome"]) >= proto.rank("DATA"):
            break


def cmd_kwpfast(args, kl, log, runner):
    for m in args.method:
        runner.run("kwpfast", proto.kwpfast, target=args.target, physical=args.physical,
                   method=m, baud=args.baud)


def cmd_dsm(args, kl, log, runner):
    for b in args.baud:
        runner.run("dsm", proto.dsm, baud=b, queries=args.queries)


def cmd_addrscan(args, kl, log, runner):
    fn = proto.mut if args.proto == "mut" else proto.iso
    for a in range(args.start, args.end + 1):
        p = dict(addr=a, baud=args.baud, sync_timeout=0.9, **_slow_common(args))
        if args.proto == "mut":
            p.update(queries=proto.MUT_ID_QUERIES, ack=args.ack)
        else:
            p.update(obd=False)
        runner.run(args.proto, fn, **p)


def wait_for_echo(kl, log, secs, settle):
    """Poll with a single echo byte until the cable is plugged into the car."""
    print(f"waiting up to {secs:.0f} s for K-line echo (plug the cable in, ignition ON)...", flush=True)
    deadline = now() + secs
    while now() < deadline:
        if proto.quick_echo(kl):
            log.ev("echo_detected")
            print(f"echo detected, settling {settle:.0f} s", flush=True)
            kl.sleep(settle)
            return True
        kl.sleep(2.0)
    print("no echo within the wait time")
    return False


def cmd_scan(args, kl, log, runner):
    if args.wait_echo:
        wait_for_echo(kl, log, args.wait_echo, args.settle)
    st = runner.run("selftest", proto.selftest, cooldown=False)
    if st["outcome"] == "NO_ECHO" and not args.force:
        print("\nNo echo on the K-line: the cable is probably not powered from the OBD socket "
              "(pin 16 +12 V / pin 4-5 GND) or not plugged in. Use --force to scan anyway.")
        return
    for kind, fn, params in scan_plan(args.full, kl.dev.backend, args.lline):
        runner.run(kind, fn, **params)


def cmd_report(args):
    path = Path(args.logdir) / ATTEMPTS
    if not path.exists():
        print("no attempts logged yet")
        return
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows[-args.last:]:
        print(f"{r['wall'][5:16]} {r['kind']:<8} {fmt_params(r['params']):<48} -> "
              f"{r['outcome']:<9} {r.get('summary', '')}  [{r.get('note', '')}]")
    best = {}
    for r in rows:
        key = f"{r['kind']} {fmt_params(r['params'])}"
        if key not in best or proto.rank(r["outcome"]) > proto.rank(best[key]):
            best[key] = r["outcome"]
    print(f"\n=== best outcome per configuration ({len(rows)} attempts) ===")
    for key, out in sorted(best.items(), key=lambda kv: -proto.rank(kv[1])):
        print(f"  {out:<9} {key}")


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"mitsu-kkl {__version__}")
    ap.add_argument("--backend", choices=("auto", "d2xx", "serial", "sim"),
                    help="default auto = FTDI via D2XX, else the first FTDI/CH340/PL2303/CP210x COM port; "
                         "serial = any chip via --port (--port alone implies serial)")
    ap.add_argument("--sim", choices=("mut", "mutlive", "mutobd", "iso", "kwp", "dsm", "none", "dead"), default="mut",
                    help="ECU model for --backend sim (offline testing)")
    ap.add_argument("--dev", type=int, help="D2XX device index (implies --backend d2xx)")
    ap.add_argument("--serial", help="D2XX: open by FTDI serial number (implies --backend d2xx)")
    ap.add_argument("--port", help="COM port, e.g. COM5 (implies --backend serial)")
    ap.add_argument("--latency", type=int, default=1, help="FTDI latency timer [ms]")
    ap.add_argument("--dtr", choices=("on", "off"), help="static DTR state for the whole run")
    ap.add_argument("--rts", choices=("on", "off"), help="static RTS state for the whole run")
    ap.add_argument("--gap", type=float, default=2.5, help="idle seconds between attempts")
    ap.add_argument("--success-gap", type=float, default=12.0,
                    help="idle seconds after an attempt that opened a session (lets it time out)")
    ap.add_argument("--note", default="", help="free text stored with every attempt (pin1, ignition...)")
    ap.add_argument("--logdir", help="default: logs/ (logs/sim/ for the simulator)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="FTDI device, driver, EEPROM (read-only, no TX)")
    sub.add_parser("selftest", help="idle/echo/break loopback test")

    s = sub.add_parser("listen", help="passive capture")
    s.add_argument("--baud", type=intlist, default=[15625, 10400, 1953])
    s.add_argument("--secs", type=float, default=2.0)

    def slow_opts(s):
        s.add_argument("--method", choices=("break", "bitbang"), default="break")
        s.add_argument("--lline", choices=("rts", "dtr", "rts-inv", "dtr-inv"),
                       help="mirror 5-baud bits onto RTS/DTR (L-line / pin-1 driver)")
        s.add_argument("--bit-ms", type=float, default=200.0)
        s.add_argument("--idle-ms", type=float, default=300.0)
        s.add_argument("--tries", type=int, default=1)

    s = sub.add_parser("mut", help="MUT-II 5-baud init + requests")
    s.add_argument("--addr", type=hexint, default=0x00)
    s.add_argument("--baud", type=int, default=15625)
    s.add_argument("--ack", action="store_true", help="answer ~KB2 like ISO 9141")
    s.add_argument("--queries", type=hexlist, help="request bytes, e.g. FE,FF,14,21")
    s.add_argument("--always-query", action="store_true", help="send requests even if nothing came back")
    s.add_argument("--repeat", type=int, default=0, help="after connecting, poll the data requests N times")
    s.add_argument("--interval", type=float, default=0.0)
    slow_opts(s)

    s = sub.add_parser("mutdump", help="MUT-II connect + read every safe request 00-BF once")
    s.add_argument("--addr", type=hexint, default=0x00)
    s.add_argument("--baud", type=int, default=15625)
    s.add_argument("--start", type=hexint, default=0x00)
    s.add_argument("--end", type=hexint, default=0xBF)
    s.add_argument("--method", choices=("break", "bitbang"), default="break")

    s = sub.add_parser("dtc", help="read engine DTC bytes (0x40/41 active, 0x45/46 stored)")
    s.add_argument("--tries", type=int, default=2)

    s = sub.add_parser("clear", help="erase engine DTCs (MUT 0xCA), engine stopped, needs --yes")
    s.add_argument("--yes", action="store_true")

    s = sub.add_parser("iso", help="ISO 9141-2 / KWP2000 slow init + OBD mode 01")
    s.add_argument("--addr", type=hexint, default=0x33)
    s.add_argument("--baud", type=int, default=10400)
    s.add_argument("--no-obd", action="store_true")
    slow_opts(s)

    s = sub.add_parser("kwpfast", help="ISO 14230 fast init")
    s.add_argument("--target", type=hexint, default=0x33)
    s.add_argument("--physical", action="store_true", help="physical addressing (e.g. --target 10)")
    s.add_argument("--method", type=lambda v: v.split(","), default=["byte", "break"])
    s.add_argument("--baud", type=int, default=10400)

    s = sub.add_parser("dsm", help="DSM-style requests at 1953 baud, no init")
    s.add_argument("--baud", type=intlist, default=[1953])
    s.add_argument("--queries", type=hexlist, default=proto.DSM_QUERIES)

    s = sub.add_parser("addrscan", help="5-baud init over a range of addresses")
    s.add_argument("--start", type=hexint, default=0x00)
    s.add_argument("--end", type=hexint, default=0x7F)
    s.add_argument("--baud", type=int, default=15625)
    s.add_argument("--proto", choices=("mut", "iso"), default="mut")
    s.add_argument("--ack", action="store_true")
    slow_opts(s)

    s = sub.add_parser("scan", help="run the matrix of strategies")
    s.add_argument("--full", action="store_true", help="also other modules, bauds and variants")
    s.add_argument("--force", action="store_true", help="scan even if selftest sees no echo")
    s.add_argument("--wait-echo", type=float, default=0.0, metavar="SECS",
                   help="first wait until the cable is powered (echo appears)")
    s.add_argument("--settle", type=float, default=5.0, help="seconds to wait after echo appears")
    s.add_argument("--lline", choices=("rts", "dtr", "rts-inv", "dtr-inv"),
                   help="add variants that mirror the init onto RTS/DTR")

    s = sub.add_parser("report", help="summarise logs/attempts.jsonl")
    s.add_argument("--last", type=int, default=40)
    return ap


def main():
    args = build_parser().parse_args()
    args.iface = cli_key(args.backend, args.dev, args.serial, args.port, args.sim) or AUTO
    args.logdir = args.logdir or str(HERE / "logs" / ("sim" if args.backend == "sim" else ""))
    if args.cmd == "report":
        return cmd_report(args)
    try:
        dev = open_device(args)
    except Exception as e:
        print(f"cannot open interface ({args.iface}): {e}")
        return 2
    if args.iface == AUTO:
        print(f"interface: {dev.label}")
    log = RunLog(args.logdir, args.cmd, sys.argv[1:], args.note)
    log.ev("interface", backend=dev.backend, label=dev.label)
    kl = KLine(dev, log)
    runner = Runner(kl, log, args.gap, args.success_gap, lambda: open_device(args), args.latency)
    hires_timer(True)
    try:
        kl.setup(10400, args.latency)
        if args.dtr:
            dev.set_dtr(args.dtr == "on")
        if args.rts:
            dev.set_rts(args.rts == "on")
        globals()["cmd_" + args.cmd](args, kl, log, runner)
    except KeyboardInterrupt:
        print("\ninterrupted")
    except proto.SafetyError as e:
        print(f"BLOCKED: {e}")
        return 3
    finally:
        try:
            kl.dev.close()
        finally:
            hires_timer(False)
            log.close()
    if len(runner.results) > 1:
        print_table(runner.results)
    print(f"log: {log.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
