# K-line side of the Pico firmware: UART at 15625 baud, 5-baud init by driving the TX pin as
# a plain GPIO, MUT-II requests (1 byte out, echo + 1 byte back). Read-only by construction:
# query() refuses everything outside 00-BF and FD-FF (C0-FC clear codes or drive actuators).
import asyncio
import time

from machine import Pin, UART

MUT_BAUD = 15625


def allowed(pid):
    return 0x00 <= pid <= 0xBF or 0xFD <= pid <= 0xFF


async def sleep_until(t):
    d = time.ticks_diff(t, time.ticks_ms())
    if d > 0:
        await asyncio.sleep_ms(d)


class KLine:
    def __init__(self, cfg):
        self.uart_id = cfg["uart"]
        self.tx, self.rx = cfg["tx_gpio"], cfg["rx_gpio"]
        self.inv_tx = 1 if cfg["invert_tx"] else 0
        self.inv_rx = bool(cfg["invert_rx"])
        self.uart = None
        self.label = "K-line UART%d (TX GP%d, RX GP%d)" % (self.uart_id, self.tx, self.rx)
        self.release()

    def open(self):
        inv = (UART.INV_TX if self.inv_tx else 0) | (UART.INV_RX if self.inv_rx else 0)
        self.uart = UART(self.uart_id, baudrate=MUT_BAUD, bits=8, parity=None, stop=1,
                         tx=Pin(self.tx), rx=Pin(self.rx), timeout=0, rxbuf=512, invert=inv)
        self.flush()

    def release(self):
        """UART off, TX held at the idle level so the K-line stays released (high)."""
        if self.uart:
            self.uart.deinit()
            self.uart = None
        Pin(self.tx, Pin.OUT, value=1 ^ self.inv_tx)

    def flush(self):
        while self.uart.any():
            self.uart.read()

    async def five_baud(self, addr, bit_ms=200, idle_ms=300):
        """Send addr at 5 baud (start bit + 8 data bits LSB first, then the stop bit)."""
        self.release()
        tx = Pin(self.tx, Pin.OUT, value=1 ^ self.inv_tx)
        await asyncio.sleep_ms(idle_ms)
        t0 = time.ticks_ms()
        for i in range(9):
            bit = 0 if i == 0 else (addr >> (i - 1)) & 1
            tx.value(bit ^ self.inv_tx)
            await sleep_until(time.ticks_add(t0, (i + 1) * bit_ms))
        tx.value(1 ^ self.inv_tx)  # stop bit; the ECU answers ~100 ms after it ends
        self.open()

    async def read(self, n, timeout_ms):
        buf = b""
        t0 = time.ticks_ms()
        while len(buf) < n:
            k = self.uart.any()
            if k:
                buf += self.uart.read(min(k, n - len(buf)))
            elif time.ticks_diff(time.ticks_ms(), t0) >= timeout_ms:
                break
            else:
                await asyncio.sleep_ms(1)
        return buf

    async def read_sync(self, timeout_ms):
        """Collect bytes until 0x55 and two key bytes arrived (or timeout)."""
        buf = b""
        t0 = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), t0) < timeout_ms:
            k = self.uart.any()
            if k:
                buf += self.uart.read(k)
                i = buf.find(b"\x55")
                if i >= 0 and len(buf) >= i + 3:
                    break
            else:
                await asyncio.sleep_ms(2)
        return buf

    async def query(self, pid, timeout_ms=150):
        """One MUT request -> value byte, or None. The K-line echoes our byte first."""
        if not allowed(pid):
            raise ValueError("blocked request %02X" % pid)
        self.flush()
        self.uart.write(bytes([pid]))
        got = await self.read(2, timeout_ms)
        if len(got) == 2 and got[0] == pid:
            return got[1]
        return None

    async def connect(self):
        """5-baud init to the engine ECU (0x00) and ID read -> (ecu_id, None) or (None, reason)."""
        await self.five_baud(0x00)
        got = await self.read_sync(1200)
        if not got:
            return None, "SILENT"
        if got.find(b"\x55") < 0:
            return None, "NOISE"
        await asyncio.sleep_ms(20)
        self.flush()
        self.uart.write(b"\xfe")
        raw = await self.read(2, 150)
        if not raw:
            return None, "NO_ECHO"
        if len(raw) < 2 or raw[0] != 0xFE:
            return None, "NO_ID"
        lo = await self.query(0xFF)
        if lo is None:
            return None, "NO_ID"
        return "%02X%02X" % (raw[1], lo), None
