"""K-line link layer on top of an FTDI backend: timestamped RX capture,
echo-aware TX, 5-baud (slow) init and 25/25 ms wake-up (fast) init."""

import ctypes
import time

LS_NAMES = ((0x02, "OE"), (0x04, "PE"), (0x08, "FE"), (0x10, "BI"))


def now():
    return time.perf_counter()


def hires_timer(on):
    """1 ms Windows timer resolution + high process priority for steadier bit timing."""
    try:
        winmm = ctypes.windll.winmm
        (winmm.timeBeginPeriod if on else winmm.timeEndPeriod)(1)
        if on:
            k32 = ctypes.windll.kernel32
            k32.SetPriorityClass(k32.GetCurrentProcess(), 0x80)  # HIGH_PRIORITY_CLASS
    except (AttributeError, OSError):
        pass


class KLine:
    def __init__(self, dev, log):
        self.dev = dev
        self.log = log
        self.buf = []      # every received byte as (t, byte); t = perf_counter when read
        self.pos = 0       # first byte not yet consumed by a reader
        self.baud = None
        self.ls_last = 0
        self.ls_counts = {}

    # -- setup ---------------------------------------------------------------
    def setup(self, baud=10400, latency=1):
        self.dev.configure(latency=latency)
        self.dev.break_off()
        self.set_baud(baud)
        self.dev.purge()

    def set_baud(self, baud):
        self.dev.set_baud(baud)
        self.baud = baud
        self.log.ev("baud", baud=baud)

    # -- receive -------------------------------------------------------------
    def poll(self):
        n = self.dev.in_waiting()
        t = now()
        if n:
            data = self.dev.read(n)
            if data:
                self.buf.extend((t, b) for b in data)
                self.log.ev("rx", t=t, hex=data.hex(" "))
        ls = self.dev.line_status()
        if ls is not None:
            ls &= 0x1E
            if ls != self.ls_last:
                rising = ls & ~self.ls_last
                for bit, name in LS_NAMES:
                    if rising & bit:
                        self.ls_counts[name] = self.ls_counts.get(name, 0) + 1
                self.log.ev("line", t=t, flags=[name for bit, name in LS_NAMES if ls & bit])
                self.ls_last = ls
        return n

    def reset_line_stats(self):
        self.ls_counts = {}

    def wait_until(self, deadline):
        while True:
            self.poll()
            rem = deadline - now()
            if rem <= 0:
                return
            if rem > 0.003:
                time.sleep(0.001)

    def sleep(self, seconds):
        self.wait_until(now() + seconds)

    def wait_for(self, cond, timeout):
        deadline = now() + timeout
        while True:
            self.poll()
            if cond():
                return True
            if now() >= deadline:
                return False
            time.sleep(0.0005)

    def discard(self):
        self.poll()
        self.pos = len(self.buf)

    def take(self):
        """Consume and return everything received so far."""
        self.poll()
        out = self.buf[self.pos:]
        self.pos = len(self.buf)
        return out

    def trim(self):
        """Drop consumed bytes so long polling sessions don't grow the buffer forever."""
        del self.buf[:self.pos]
        self.pos = 0

    def read_n(self, n, timeout):
        self.wait_for(lambda: len(self.buf) - self.pos >= n, timeout)
        out = self.buf[self.pos:self.pos + n]
        self.pos += len(out)
        return out

    def read_until_idle(self, idle, timeout, first_timeout=None):
        """Consume bytes until `idle` s pass without a new one (after the first
        byte), `first_timeout` passes with nothing at all, or `timeout`."""
        start = now()
        deadline = start + timeout
        first_deadline = start + (timeout if first_timeout is None else first_timeout)
        out = []
        while True:
            self.poll()
            if len(self.buf) > self.pos:
                out.extend(self.buf[self.pos:])
                self.pos = len(self.buf)
            t = now()
            if t >= deadline or (not out and t >= first_deadline) or (out and t - out[-1][0] >= idle):
                return out
            time.sleep(0.0005)

    # -- transmit ------------------------------------------------------------
    def write(self, data):
        data = bytes(data)
        t = now()
        self.dev.write(data)
        self.log.ev("tx", t=t, hex=data.hex(" "))
        return t

    def send(self, data, gap=0.0, echo_timeout=0.15):
        """Send byte by byte, consuming each byte's half-duplex echo.
        Returns (echo_ok, t_first_write)."""
        self.discard()
        bad, t_first = [], None
        for i, b in enumerate(data):
            t = self.write([b])
            t_first = t if t_first is None else t_first
            e = self.read_n(1, echo_timeout)
            if not e or e[0][1] != b:
                bad.append([i, f"{b:02X}", f"{e[0][1]:02X}" if e else None])
            if gap and i + 1 < len(data):
                self.sleep(gap)
        if bad:
            self.log.ev("echo_mismatch", bad=bad)
        return not bad, t_first

    # -- line control ----------------------------------------------------------
    def _lline(self, level, lline):
        """Optionally mirror the init bits onto RTS/DTR (L-line or pin-1 driver).
        'rts'/'dtr': asserted while K is low; '-inv' suffix: asserted while K is high."""
        if not lline:
            return
        name, inv = lline.split("-")[0], lline.endswith("-inv")
        on = (level == 0) != inv
        (self.dev.set_rts if name == "rts" else self.dev.set_dtr)(on)

    def five_baud(self, addr, bit=0.2, idle=0.3, method="break", lline=None):
        """Send `addr` at 5 baud (8N1, LSB first) by forcing TXD low with a UART
        break or via async bit-bang. t_release = start of the stop bit."""
        bits = [0] + [(addr >> i) & 1 for i in range(8)]
        self.dev.break_off()
        self._lline(1, lline)
        self.sleep(idle)
        self.log.ev("5baud_begin", addr=f"{addr:02X}", bit_ms=round(bit * 1000, 1),
                    method=method, lline=lline)
        edges, readback = [], []
        if method == "bitbang":
            self.dev.bitbang(True)
        t0 = now()
        level = 1
        for i, b in enumerate(bits):
            self.wait_until(t0 + i * bit)
            if b != level:
                edges.append(round((now() - t0) * 1000, 2))
                if method == "bitbang":
                    self.dev.bitbang_write(b)
                else:
                    (self.dev.break_off if b else self.dev.break_on)()
                self._lline(b, lline)
                level = b
            if method == "bitbang":  # sample RXD (= K-line as seen by the transceiver) mid-bit
                self.wait_until(t0 + (i + 0.5) * bit)
                readback.append((self.dev.pins() >> 1) & 1)
        self.wait_until(t0 + 9 * bit)
        edges.append(round((now() - t0) * 1000, 2))
        if method == "bitbang":
            self.dev.bitbang(False)        # back to UART: TXD idles high = stop bit
            self.dev.purge_rx()            # drop bit-bang samples; the ECU answers >=100 ms later
            self.dev.set_baud(self.baud)
        else:
            self.dev.break_off()
        self._lline(1, lline)
        t_rel = now()
        self.log.ev("5baud_end", t=t_rel, edges_ms=edges, readback=readback)
        return {"t0": t0, "t_release": t_rel, "t_stop_end": t0 + 10 * bit,
                "edges_ms": edges, "readback": readback}

    def fast_init(self, method="byte", t_low=0.025, t_high=0.025, idle=0.3, baud=10400):
        """ISO 14230 wake-up (25 ms low, 25 ms high). Returns the time at which
        the first StartCommunication byte should be written.
        method 'byte': 0x00 at 360 baud = start bit + 8 data bits = exactly 25 ms low.
        method 'break': UART break timed in software."""
        self.set_baud(baud)
        self.dev.break_off()
        self.sleep(idle)
        self.log.ev("fastinit_begin", method=method)
        echo = None
        if method == "break":
            t0 = now()
            self.dev.break_on()
            t_fall = (t0 + now()) / 2
            self.wait_until(t_fall + t_low)
            t1 = now()
            self.dev.break_off()
            t_rise = (t1 + now()) / 2
        else:
            self.set_baud(round(9 / t_low))
            self.discard()
            t0 = self.write(b"\x00")
            e = self.read_n(1, 0.2)
            echo = f"{e[0][1]:02X}" if e else None
            # echo is reported ~1.4 ms after the rising edge (mid stop bit) + ~1 ms USB latency
            t_rise = e[0][0] - 0.0024 if e else t0 + t_low + 0.002
            t_fall = t_rise - t_low
            self.set_baud(baud)
        self.log.ev("fastinit_end", low_ms=round((t_rise - t_fall) * 1000, 2), echo=echo)
        return t_rise + t_high
