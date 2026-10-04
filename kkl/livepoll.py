"""Background MUT-II poller for live viewers: connects to the engine ECU (init method from
proto.INIT_METHODS: MUT-II 0x00, OBD-II 0x33 or both in turn), polls a PID list in a loop and
reconnects when the session drops. Results go
to one callback, so a web server (or a GUI) can use it. Read-only: every request passes
proto.check_mut()."""

import threading

from . import proto
from .link import KLine, hires_timer, now


class NullLog:
    """KLine needs a logger; a byte-level log at ~150 requests/s would be huge."""

    def ev(self, *args, **kwargs):
        pass


class Poller(threading.Thread):
    """on_event(kind, *args) kinds:
    ("status", code, detail) · ("iface", label) · ("connected", ecu_id, init_label) · ("val", pid, value|None)
    · ("rate", reads_per_s, cycle_s) · ("stopped",)"""

    def __init__(self, open_dev, pids, on_event, init_mode="auto"):
        super().__init__(daemon=True)
        self.open_dev, self.emit = open_dev, on_event
        self.init_mode = init_mode if init_mode in proto.INIT_MODES else "auto"
        self.last_good = None
        self.stop_ev = threading.Event()
        self.lock = threading.Lock()
        self._pids = list(pids)

    def set_pids(self, pids):
        with self.lock:
            self._pids = list(pids)

    def stop(self):
        self.stop_ev.set()

    def run(self):
        self.emit("status", "opening", "")
        try:
            dev = self.open_dev()
        except Exception as e:
            self.emit("status", "error", f"Cannot open interface: {e}")
            self.emit("stopped")
            return
        self.emit("iface", getattr(dev, "label", ""))
        kl = KLine(dev, NullLog())
        hires_timer(True)
        try:
            kl.setup(15625, 1)
            tries = 0
            while not self.stop_ev.is_set():
                order = proto.init_order(self.init_mode, self.last_good)
                method = order[tries % len(order)]
                label = proto.INIT_METHODS[method]["label"]
                self.emit("status", "connecting", label)
                res = proto.connect(kl, NullLog(), method)
                tries += 1
                if res["outcome"] != "DATA":
                    self.emit("status", "no_response", f"{label}: {res['outcome']}")
                    # in auto mode the other method follows at once; a full round waits 3 s
                    self.stop_ev.wait(3.0 if tries % len(order) == 0 else 0.3)
                    continue
                self.last_good, tries = method, 0
                self.emit("connected", "".join(q["resp"] for q in res["queries"]), label)
                self._poll(kl)
                if not self.stop_ev.is_set():
                    self.emit("status", "lost", "")
                    self.stop_ev.wait(2.0)
        except Exception as e:
            self.emit("status", "error", f"{type(e).__name__}: {e}")
        finally:
            try:
                dev.close()
            except Exception:
                pass
            hires_timer(False)
            self.emit("stopped")

    def _poll(self, kl):
        misses, count, t_rate = 0, 0, now()
        while not self.stop_ev.is_set():
            with self.lock:
                pids = list(self._pids)
            keepalive = not pids
            t_cycle = now()
            for pid in pids or [0xFE]:  # an empty list still keeps the session alive
                if self.stop_ev.is_set():
                    return
                v = self._query(kl, pid)
                if not keepalive:
                    self.emit("val", pid, v)
                misses = 0 if v is not None else misses + 1
                if misses >= 8:
                    return
                count += 1
            kl.trim()
            t = now()
            if t - t_rate >= 1.0:
                self.emit("rate", count / (t - t_rate), t - t_cycle)
                count, t_rate = 0, t

    @staticmethod
    def _query(kl, pid):
        """One MUT request: the K-line echoes our byte, then the ECU sends one value byte."""
        proto.check_mut(pid)
        kl.discard()
        kl.write([pid])
        got = kl.read_n(2, 0.15)
        if len(got) == 2 and got[0][1] == pid:
            return got[1][1]
        return None
