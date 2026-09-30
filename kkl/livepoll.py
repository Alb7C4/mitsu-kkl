"""Background MUT-II poller for live viewers: connects to the engine ECU (5-baud 0x00 at
15625 baud), polls a PID list in a loop and reconnects when the session drops. Results go
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
    ("status", code, detail) · ("iface", label) · ("connected", ecu_id) · ("val", pid, value|None)
    · ("rate", reads_per_s, cycle_s) · ("stopped",)"""

    def __init__(self, open_dev, pids, on_event):
        super().__init__(daemon=True)
        self.open_dev, self.emit = open_dev, on_event
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
            while not self.stop_ev.is_set():
                self.emit("status", "connecting", "")
                res = proto.mut(kl, NullLog(), addr=0x00, baud=15625, queries=proto.MUT_ID_QUERIES)
                if res["outcome"] != "DATA":
                    self.emit("status", "no_response", res["outcome"])
                    self.stop_ev.wait(3.0)
                    continue
                self.emit("connected", "".join(q["resp"] for q in res["queries"]))
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
