"""Simulated K-line + ECU for testing the probe logic without a car.

Models: 'mut' (addr 00, 15625, 55 EF 85, echo + 1 byte), 'mutlive' (like mut but every
request 00-BF answers and RPM/TPS/coolant move), 'iso' (0x33, 10400,
08 08, ~KB2 / CC, OBD mode 01/03), 'kwp' (fast init, C1 E9 8F), 'dsm' (1953,
no init), 'none' (powered bus, nobody answers), 'dead' (cable not powered).
"""

import math
import time

MUT_VALUES = {0xFE: 0xE4, 0xFF: 0xB3, 0x14: 0xA5, 0x07: 0x50, 0x21: 0x00, 0x17: 0x1A, 0x15: 0xCF}


def now():
    return time.perf_counter()


def _cs(msg):
    return msg + [sum(msg) & 0xFF]


class SimDevice:
    backend = "sim"

    def __init__(self, model="mut"):
        self.model = model
        self.powered = model != "dead"
        self.baud = 9600
        self.level = 1
        self.edges = [(now() - 10.0, 1)]
        self.rxq = []
        self.bb = False
        self.pending_init = None
        self.session = None
        self.wakeup_t = None
        self.frame = []

    # -- bus model -------------------------------------------------------------
    def _push(self, t, b):
        if self.powered:
            self.rxq.append((t, b))
            self.rxq.sort()

    def _level_at(self, t):
        lvl = 1
        for te, le in self.edges:
            if te > t:
                break
            lvl = le
        return lvl

    def _drive(self, lvl):
        t = now()
        if lvl == self.level:
            return
        if lvl == 0:
            if t - self.edges[-1][0] >= 0.29 and self.pending_init is None:
                self.pending_init = t
            if not self.bb:
                self._push(t + 0.0008, 0x00)  # break seen by our own UART
        elif 0.023 <= t - self.edges[-1][0] <= 0.027:
            self.wakeup_t, self.pending_init = t, None
        self.level = lvl
        self.edges.append((t, lvl))

    def _ecu_bytes(self, t, data, ecu_baud, gap=0.002):
        ok = abs(self.baud - ecu_baud) / ecu_baud < 0.03
        for i, b in enumerate(data):
            self._push(t + i * gap, b if ok else 0xF8)

    def _evaluate(self):
        t0 = self.pending_init
        if t0 is None or now() < t0 + 1.95:
            return
        self.pending_init = None
        if self._level_at(t0 + 0.1) != 0 or self._level_at(t0 + 1.9) != 1:
            return
        addr = sum(self._level_at(t0 + (i + 1.5) * 0.2) << i for i in range(8))
        t_end = t0 + 2.0
        if self.model in ("mut", "mutlive") and addr == 0x00:
            self._ecu_bytes(t_end + 0.05, [0x55, 0xEF, 0x85], 15625)
            self.session = {"type": "mut", "last": t_end} if abs(self.baud - 15625) < 400 else None
        elif self.model == "iso" and addr == 0x33:
            self._ecu_bytes(t_end + 0.1, [0x55, 0x08, 0x08], 10400, gap=0.01)
            self.session = {"type": "iso", "stage": "kb", "t_kb2": t_end + 0.12, "last": t_end}

    def _on_byte(self, t, b):
        if self.session and t - self.session.get("last", t) > 5.0:
            self.session = None  # ECU session timed out
        s = self.session
        if s:
            s["last"] = t
        if self.model == "dsm" and abs(self.baud - 1953) < 60 and b in MUT_VALUES:
            self._push(t + 0.012, MUT_VALUES[b])
        elif s and s["type"] == "mut" and self._mut_value(b) is not None:
            self._push(t + 0.004, self._mut_value(b))
        elif s and s["type"] == "iso" and s["stage"] == "kb":
            if b == 0xF7 and 0.024 <= t - s["t_kb2"] <= 0.052:
                self._push(t + 0.03, 0xCC)
                s["stage"], self.frame = "ready", []
        elif s and s.get("stage") == "ready":
            self._frame_byte(t, b)
        elif self.model == "kwp" and self.wakeup_t and t - self.wakeup_t < 0.2:
            self.session = {"type": "kwp", "stage": "ready"}
            self.frame = []
            self._frame_byte(t, b)

    def _mut_value(self, b):
        if self.model != "mutlive":
            return MUT_VALUES.get(b)
        if b > 0xBF and b not in MUT_VALUES:
            return None
        t = now()
        if b == 0x21:
            return int(25 + 20 * math.sin(t / 3))           # RPM drifts slowly
        if b == 0x17:
            return 0x21 + (60 if int(t) % 12 < 2 else 0)     # throttle blip every 12 s
        if b == 0x07:
            return 0x89 + (int(t * 7) % 3) - 1               # +-1 noise
        return MUT_VALUES.get(b, (b * 37 + 11) & 0xFF)

    def _frame_byte(self, t, b):
        self.frame.append(b)
        f = self.frame
        if len(f) < 4 or sum(f[:-1]) & 0xFF != f[-1]:
            return
        self.frame = []
        payload = f[3:-1]
        iso = f[0] == 0x68
        hdr = (lambda n: [0x48, 0x6B, 0x10]) if iso else (lambda n: [0x80 | n, 0xF1, 0x10])
        reply = None
        if payload == [0x81]:
            reply = [0xC1, 0xE9, 0x8F]
        elif payload == [0x01, 0x00]:
            reply = [0x41, 0x00, 0xBE, 0x1F, 0xB8, 0x10]
        elif payload == [0x03]:
            reply = [0x43, 0x01, 0x33, 0x00, 0x00, 0x00, 0x00]
        elif payload == [0x82]:
            reply = [0xC2]
        if reply:
            self._ecu_bytes(t + 0.03, _cs(hdr(len(reply)) + reply), 10400)

    # -- backend interface -------------------------------------------------------
    def configure(self, latency=1):
        pass

    def set_baud(self, baud):
        self.baud = baud

    def purge(self):
        self.rxq = []

    purge_rx = purge

    def in_waiting(self):
        self._evaluate()
        t = now()
        return sum(1 for ta, _ in self.rxq if ta <= t)

    def read(self, n):
        t = now()
        ready = [x for x in self.rxq if x[0] <= t][:n]
        self.rxq = self.rxq[len(ready):]
        return bytes(b for _, b in ready)

    def write(self, data):
        t = now() + 0.001
        for i, b in enumerate(bytes(data)):
            if self.bb:
                continue
            t_b = t + (i + 1) * 10 / self.baud
            self._push(t_b + 0.0005, b)
            if self.baud < 500 and b == 0x00:  # 25 ms low wake-up via a slow byte
                self.edges += [(t, 0), (t + 9 / self.baud, 1)]
                self.wakeup_t = t + 9 / self.baud
                continue
            self._on_byte(t_b, b)

    def break_on(self):
        self._drive(0)

    def break_off(self):
        self._drive(1)

    def set_dtr(self, on):
        pass

    set_rts = set_dtr

    def line_status(self):
        return 0

    def bitbang(self, on, mask=0x01):
        self.bb = on
        if not on:
            self._drive(1)

    def bitbang_write(self, level):
        self._drive(1 if level else 0)

    def pins(self):
        return 0x01 | (self.level << 1) if self.powered else 0x03

    def info(self):
        return {"backend": "sim", "model": self.model}

    def close(self):
        pass
