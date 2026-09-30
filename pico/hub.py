# Device state for the Pico firmware: PID definitions on flash, the polling loop, the event
# queues of the connected browsers and the status LED. One asyncio loop, so no locks.
import asyncio
import json
import os
import time

from kline import allowed

DEFS = "pid_definitions.csv"
DTC = "dtc_definitions.csv"
HEADER = (
    "# MUT-II PID definitions (engine ECU). Separator: semicolon. Lines starting with # are comments.",
    "# pid ; name ; conversion ; unit ; on list (1/0)",
    "# conversion: expression in x (raw byte 0-255), e.g. x*0.0733 | x*31.25 | x-40 | (x>>4)&15 | round(x*0.49, 1)",
    "#   or a keyword: dtc / dtc2 (fault code bits), bin (binary); empty = no conversion",
)
FIRST = (0x07, 0x14, 0x15, 0x17, 0x21, 0x3A, 0x40, 0x45)
DEFAULT_DTC = ((0, 11, "oxygen sensor"), (1, 12, "air flow sensor"), (2, 13, "intake air temperature sensor"),
               (3, 14, "throttle position sensor"), (4, 15, "idle speed control motor position"),
               (5, 21, "engine coolant temperature sensor"), (6, 22, "crank angle sensor"),
               (7, 23, "top dead centre sensor"), (8, 24, "vehicle speed sensor"),
               (9, 25, "barometric pressure sensor"), (10, 31, "knock sensor"), (11, 32, "manifold pressure sensor"),
               (12, 36, "ignition timing adjustment signal"), (13, 39, "second oxygen sensor"),
               (14, 41, "injector"), (15, 42, "fuel pump"))
CONV_CHARS = "0123456789.,x+-*/%&|^>() abcdefghijklmnopqrstuvwyz_"


def hx(pid):
    return "%02X" % pid


def parse_pids(text):
    """'07,14,20-2F' -> ([0x07, 0x14, 0x20, ... 0x2F], rejected). Keeps the order, no duplicates."""
    pids, rejected = [], []
    for sep in " ;":
        text = text.replace(sep, ",")
    for part in text.split(","):
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a, 16), int(b or a, 16)
        except ValueError:
            rejected.append(part)
            continue
        for p in range(lo, hi + 1):
            if not allowed(p):
                rejected.append(hx(p))
            elif p not in pids:
                pids.append(p)
    return pids, rejected


def check_conv(conv):
    """The browser evaluates conversions; this only keeps junk out of the file."""
    if len(conv) > 80 or any(c not in CONV_CHARS for c in conv.lower()):
        raise ValueError("invalid conversion (allowed: numbers, x, + - * / // % & | ^ >>, ( ), abs min max round, "
                         "or dtc, dtc2, bin)")


class Client:
    def __init__(self):
        self.msgs = []
        self.ev = asyncio.Event()


class Hub:
    def __init__(self, cfg, kl, pin1, led, version):
        self.cfg, self.kl, self.pin1, self.led, self.version = cfg, kl, pin1, led, version
        self.clients = []
        self.status = {"code": "idle", "detail": "", "ecu_id": "", "iface": kl.label}
        self.values, self.pending, self.rate = {}, {}, None
        self.defs, self.keep = {}, []  # pid -> [name, conv, unit, active]
        self.load_defs()
        self.dtc = self.load_dtc()
        self.pids = [p for p in sorted(self.defs) if self.defs[p][3]] or list(FIRST)
        self.running = False
        self.task = None
        self.set_pin1(False)

    # -- files on flash ------------------------------------------------------------------
    def load_defs(self):
        try:
            f = open(DEFS)
        except OSError:
            self.defs = {p: ["", "", "", True] for p in FIRST}
            self.save_defs()
            return
        with f:
            for line in f:
                line = line.strip().lstrip("﻿")
                if not line or line in HEADER:
                    continue
                if line.startswith("#"):
                    self.keep.append(line)
                    continue
                fl = [x.strip() for x in line.split(";")] + ["", "", "", ""]
                try:
                    pid = int(fl[0], 16)
                except ValueError:
                    continue
                if allowed(pid):
                    self.defs[pid] = [fl[1], fl[2], fl[3], fl[4].lower() not in ("0", "nie", "n", "no", "false")]

    def save_defs(self):
        tmp = DEFS + ".tmp"
        with open(tmp, "w") as f:
            for line in HEADER + tuple(self.keep):
                f.write(line + "\n")
            for p in sorted(self.defs):
                name, conv, unit, active = self.defs[p]
                if name or conv or unit or active:
                    f.write("%s ; %s ; %s ; %s ; %d\n" % (hx(p), name, conv, unit, 1 if active else 0))
        try:
            os.remove(DEFS)
        except OSError:
            pass
        os.rename(tmp, DEFS)

    def load_dtc(self):
        out = []
        try:
            with open(DTC) as f:
                for line in f:
                    line = line.strip().lstrip("﻿")
                    if not line or line.startswith("#"):
                        continue
                    fl = [x.strip() for x in line.split(";")] + ["", ""]
                    try:
                        if fl[0]:
                            out.append((int(fl[0]), int(fl[1]), fl[2]))
                    except ValueError:
                        pass
        except OSError:
            pass
        return out or list(DEFAULT_DTC)

    def defs_json(self):
        return {"pids": {hx(p): {"name": d[0], "conv": d[1], "unit": d[2], "active": d[3]}
                         for p, d in sorted(self.defs.items())},
                "dtc": [{"bit": b, "code": c, "desc": s} for b, c, s in self.dtc]}

    def update_def(self, pid, name, conv, unit):
        check_conv(conv)
        clean = lambda s: s.replace(";", ",").replace("\n", " ")[:60]
        d = self.defs.setdefault(pid, ["", "", "", pid in self.pids])
        d[0], d[1], d[2] = clean(name), conv, clean(unit)
        self.save_defs()
        self.publish({"type": "defs"})

    # -- polled list ------------------------------------------------------------------
    def set_pids(self, pids, temporary=False):
        self.pids = list(pids)
        self.values = {p: self.values.get(p) for p in self.pids}
        if not temporary:
            for p, d in self.defs.items():
                d[3] = p in self.pids
            for p in self.pids:
                self.defs.setdefault(p, ["", "", "", True])
            self.save_defs()
        self.publish({"type": "pids", "pids": [hx(p) for p in pids]})

    # -- events -----------------------------------------------------------------------
    def snapshot(self):
        return {"type": "state", "status": dict(self.status), "pids": [hx(p) for p in self.pids],
                "values": {hx(p): self.values.get(p) for p in self.pids}, "rate": self.rate}

    def subscribe(self):
        c = Client()
        self.clients.append(c)
        return c

    def unsubscribe(self, c):
        if c in self.clients:
            self.clients.remove(c)

    def publish(self, msg):
        data = json.dumps(msg).encode()
        for c in self.clients:
            if len(c.msgs) > 200:  # a stalled browser: start it over from a fresh snapshot
                c.msgs = [json.dumps(self.snapshot()).encode()]
            c.msgs.append(data)
            c.ev.set()

    def set_status(self, code, detail="", ecu_id=""):
        self.status["code"], self.status["detail"], self.status["ecu_id"] = code, detail, ecu_id
        msg = dict(self.status)
        msg["type"] = "status"
        self.publish(msg)

    async def flusher(self):
        """Values go out in batches every 100 ms."""
        while True:
            await asyncio.sleep_ms(100)
            if self.pending:
                batch, self.pending = self.pending, {}
                self.publish({"type": "values", "v": {hx(p): v for p, v in batch.items()}})

    async def blinker(self):
        """LED: off = idle, slow blink = connecting, on = connected, fast blink = error."""
        n = 0
        while True:
            await asyncio.sleep_ms(125)
            n += 1
            code = self.status["code"]
            if code == "connected":
                on = True
            elif code in ("error", "no_response"):
                on = n % 2 == 0
            elif code == "idle":
                on = False
            else:
                on = n % 8 < 4
            self.led.value(1 if on else 0)

    # -- connection --------------------------------------------------------------------
    def set_pin1(self, ground):
        """Pin 1 of the OBD socket to ground (ECU diagnostic mode) through a transistor."""
        if self.pin1:
            self.pin1.value(1 if ground == bool(self.cfg["pin1_active_high"]) else 0)

    def connect(self):
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._run())

    def disconnect(self):
        self.running = False

    async def pause(self, ms):
        t0 = time.ticks_ms()
        while self.running and time.ticks_diff(time.ticks_ms(), t0) < ms:
            await asyncio.sleep_ms(50)

    async def _run(self):
        self.set_status("opening")
        try:
            self.set_pin1(True)
            await asyncio.sleep_ms(300)
            while self.running:
                self.set_status("connecting")
                ecu, why = await self.kl.connect()
                if not ecu:
                    self.set_status("no_response", why)
                    # like the MUT tester: release pin 1 for 0.5 s before the next attempt
                    self.set_pin1(False)
                    await self.pause(500)
                    self.set_pin1(True)
                    await self.pause(2500)
                    continue
                self.set_status("connected", ecu_id=ecu)
                await self._poll()
                if self.running:
                    self.set_status("lost")
                    await self.pause(2000)
            self.set_status("idle")
        except Exception as e:
            self.set_status("error", "%s: %s" % (type(e).__name__, e))
        finally:
            self.kl.release()
            self.set_pin1(False)
            self.running, self.rate = False, None

    async def _poll(self):
        misses, count, t_rate = 0, 0, time.ticks_ms()
        while self.running:
            pids = list(self.pids)
            t_cycle = time.ticks_ms()
            for pid in pids or [0xFE]:  # an empty list still keeps the session alive
                if not self.running:
                    return
                v = await self.kl.query(pid)
                if pids:
                    self.values[pid] = self.pending[pid] = v
                misses = 0 if v is not None else misses + 1
                if misses >= 8:
                    return
                count += 1
            t = time.ticks_ms()
            dt = time.ticks_diff(t, t_rate)
            if dt >= 1000:
                self.rate = {"reads": round(count * 1000 / dt, 1), "cycle": time.ticks_diff(t, t_cycle) / 1000}
                msg = dict(self.rate)
                msg["type"] = "rate"
                self.publish(msg)
                count, t_rate = 0, t
