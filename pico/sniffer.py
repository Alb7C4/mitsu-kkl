# K-line edge sniffer for Raspberry Pi Pico / Pico 2 (W) with MicroPython 1.23+. Receive only:
# the pin is an input, nothing is ever driven.
#
# A PIO state machine timestamps every edge of the receiver output with 1 us resolution and DMA
# copies the timestamps into a ring buffer, so the CPU only has to forward them over USB.
# Started by the PC tool (python tools/sniff_pico.py), which also decodes the capture.
#
# Output lines: "SNIFF ..." header, "D <base64>" = little-endian 32-bit words, "LOST <n>" when the
# ring overflowed. Word = (x << 1) | level after the edge; x = free-running 31-bit counter that
# counts DOWN one step per microsecond. The first word is the level when the capture started.
# Each edge costs the counter one extra tick, the PC side adds it back.

import sys
import time

import rp2
import uctypes
import ubinascii
from machine import Pin

PIN = 1       # GPIO with the receiver output (the PC tool rewrites these two lines)
PULL = ""     # "", "up" or "down"

FREQ = 2_000_000          # PIO clock: one loop = 2 cycles = 1 us
RING_BITS = 14            # 16 KiB ring = 4096 edges, about 0.5 s of continuous 15625 baud traffic
RING_BYTES = 1 << RING_BITS
RING_WORDS = RING_BYTES // 4
COUNT = 0x0FFFFFFF        # DMA transfers before it stops (hours of traffic)
PIO0_RXF0 = 0x50200020    # PIO0 RX FIFO of state machine 0 (same on RP2040 and RP2350)
DREQ_PIO0_RX0 = 4


@rp2.asm_pio(autopush=True, push_thresh=32, in_shiftdir=rp2.PIO.SHIFT_LEFT, fifo_join=rp2.PIO.JOIN_RX)
def edges():
    mov(x, invert(null))
    in_(x, 31)
    in_(pins, 1)               # first word: start level
    jmp(pin, "high")
    label("low")               # line low: 2 cycles per tick
    jmp(pin, "rose")
    jmp(x_dec, "low")
    label("rose")              # edge: 4 cycles, 1 tick
    in_(x, 31)
    in_(pins, 1)
    jmp(x_dec, "high")
    label("high")              # line high: 2 cycles per tick
    jmp(pin, "h1")
    in_(x, 31)                 # fell: 4 cycles, 1 tick
    in_(pins, 1)
    jmp(x_dec, "low")
    label("h1")
    jmp(x_dec, "high")


def main():
    pull = {"up": Pin.PULL_UP, "down": Pin.PULL_DOWN}.get(PULL)
    pin = Pin(PIN, Pin.IN, pull)
    raw = bytearray(2 * RING_BYTES)                       # DMA ring must be aligned to its size
    ring_addr = (uctypes.addressof(raw) + RING_BYTES - 1) & ~(RING_BYTES - 1)
    ring = memoryview(uctypes.bytearray_at(ring_addr, RING_BYTES))

    rp2.PIO(0).remove_program()
    sm = rp2.StateMachine(0, edges, freq=FREQ, in_base=pin, jmp_pin=pin)
    dma = rp2.DMA()
    ctrl = dma.pack_ctrl(size=2, inc_read=False, inc_write=True, ring_size=RING_BITS, ring_sel=True,
                         treq_sel=DREQ_PIO0_RX0)
    dma.config(read=PIO0_RXF0, write=ring_addr, count=COUNT, ctrl=ctrl, trigger=True)
    sm.active(1)
    print("SNIFF pin=GP%d pull=%s tick_us=1 level=%d" % (PIN, PULL or "none", pin.value()))

    last = 0
    try:
        while True:
            done = COUNT - (dma.count & 0x0FFFFFFF)
            if done == last:
                time.sleep_ms(2)
                continue
            if done - last > RING_WORDS:
                print("LOST %d" % (done - last - RING_WORDS))
                last = done - RING_WORDS
            while last < done:
                i = last % RING_WORDS
                k = min(done - last, RING_WORDS - i, 96)
                sys.stdout.write("D " + ubinascii.b2a_base64(ring[i * 4:(i + k) * 4]).decode())
                last += k
    finally:
        sm.active(0)
        dma.close()
        rp2.PIO(0).remove_program()
        print("END")


main()
