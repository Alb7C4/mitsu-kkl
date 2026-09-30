# Bench test of the K-line interface (hw/schemat.svg) on the Pico, without a car: needs +12 V on
# the OBD plug (pin 16 +, pins 4/5 -), e.g. a lab supply with a ~200 mA current limit.
# From the project folder:   mpremote run pico/benchtest.py
# Reads config.json from the Pico if present, so it tests the same pins as the firmware.
import json
import time

from machine import Pin, UART

cfg = {"uart": 0, "tx_gpio": 0, "rx_gpio": 1, "invert_tx": True, "invert_rx": False,
       "pin1_gpio": 2, "pin1_active_high": True}
try:
    with open("config.json") as f:
        cfg.update(json.load(f))
except (OSError, ValueError):
    print("no config.json on the Pico, using the defaults of hw/schemat.svg")

inv_tx, inv_rx = 1 if cfg["invert_tx"] else 0, 1 if cfg["invert_rx"] else 0
passed = []


def check(name, ok, hint=""):
    passed.append(ok)
    print("%s  %s%s" % ("OK  " if ok else "FAIL", name, "" if ok else "\n      -> " + hint))


def k_drive(low):
    """low=True: our transistor pulls the K-line to 0 V; False: release it."""
    Pin(cfg["tx_gpio"], Pin.OUT, value=(0 if low else 1) ^ inv_tx)


def k_level():
    """K-line level as seen by the receiver: 1 = high (~12 V), 0 = low."""
    return Pin(cfg["rx_gpio"], Pin.IN).value() ^ inv_rx


print("K-line interface bench test: TX GP%d, RX GP%d, pin 1 GP%s" % (cfg["tx_gpio"], cfg["rx_gpio"], cfg["pin1_gpio"]))
k_drive(False)
time.sleep_ms(20)
check("1. K-line idle high", k_level() == 1,
      "no 12 V on OBD 16 / +12V_P, R4 missing, receiver (U2, R5-R8, R10) or invert_rx wrong")

k_drive(True)
time.sleep_ms(20)
low = k_level()
k_drive(False)
time.sleep_ms(20)
check("2. TX pulls the K-line low and releases it", low == 0 and k_level() == 1,
      "check R1, Q1 (collector on K, emitter on GND), R2, or invert_tx in config.json")

inv = (UART.INV_TX if inv_tx else 0) | (UART.INV_RX if inv_rx else 0)
uart = UART(cfg["uart"], baudrate=15625, bits=8, parity=None, stop=1, tx=Pin(cfg["tx_gpio"]),
            rx=Pin(cfg["rx_gpio"]), timeout=0, rxbuf=256, invert=inv)
time.sleep_ms(20)
while uart.any():
    uart.read()
pattern = b"\x55\xaa\x00\xff\x0f\xf0"
uart.write(pattern)
time.sleep_ms(30)
echo = uart.read() or b""
hx = lambda b: " ".join("%02X" % x for x in b) or "-"
check("3. UART echo at 15625 baud (%s -> %s)" % (hx(pattern), hx(echo)), echo == pattern,
      "no echo: TX/RX wiring or inversion; wrong bytes: slow edges (R4, cable) or noise")
uart.deinit()
k_drive(False)

if cfg["pin1_gpio"] is not None:
    p1 = Pin(cfg["pin1_gpio"], Pin.OUT)
    ground = 1 if cfg["pin1_active_high"] else 0
    p1.value(ground)
    print("4. Pin 1 grounded for 5 s: measure OBD pin 1 against pin 4/5 now, it should read ~0 V")
    time.sleep(5)
    p1.value(1 - ground)
    print("   pin 1 released (without a car it floats; in the car the ECU pulls it up)")

print("\nResult: %d of %d checks passed" % (sum(passed), len(passed)))
