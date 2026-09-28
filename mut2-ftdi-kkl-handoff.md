# MUT-II over a VAG KKL cable (FT232BL) — handoff notes

Context file for continuing this work in Claude Code. Summarises a chat conversation
(2026-09-27) about reusing an existing VAG KKL diagnostic cable to talk to a
late-1990s Mitsubishi ECU using the MUT-II protocol, directly from a PC via the
cable's own FTDI chip (no Raspberry Pi Pico needed).

## Goal

- Talk MUT-II to a late-90s Mitsubishi ECU from a PC through an existing VAG KKL cable.
- Primary path: use the cable's FT232BL directly (Python/pyserial or D2XX).
- Alternative path (already explored in a separate Pico 2 W project): replace the
  FTDI with a Raspberry Pi Pico. Notes on that are kept below for reference.

## Hardware facts

### FT232BL

- FT232BL is the lead-free (RoHS) LQFP-32 variant of FT232BM — same silicon, same
  features. Driver reports it as device type BM (`FT_DEVICE_BM`). Nothing needs to be
  "forced" to make it behave like a BM.
- Supports: exact 15625 baud (3 MHz / 192), break on TXD, async bit-bang, latency
  timer down to 1 ms.

| Signal | FT232BL (LQFP-32) | FT232RL (SSOP-28), if the cable turns out to use it |
|---|---|---|
| TXD | 25 | 1 |
| RXD | 24 | 5 |
| VCCIO | 13 | 4 |
| GND | 9, 17, 29 | 7, 18, 21 |
| RTS# / DTR# | 23 / 21 | 3 / 2 |

- TXD can be driven directly (break = forced low; or bit-bang mode). RXD is an input
  driven by the transceiver — it can be read but not set.
- VCCIO in KKL cables is almost always 5 V → UART levels are 5 V, not 3.3 V.

### Cable / transceiver

- K-line: single wire, bidirectional, 12 V; TXD and RXD both go to the transceiver
  (L9637D / LM339 / discrete transistors), never directly to K.
- Tester-side pull-up ~510 Ω from K to +12 V.
- OBD pins: 7 = K, 15 = L, 16 = +12 V, 4/5 = GND.
- Half duplex: every transmitted byte is echoed back on RX. Software must consume it.
- Transceiver type in the user's cable: **not yet identified**.

### Possible cable mods for Mitsubishi

- **OBD pin 1 → GND**: some Mitsubishi models (Galant/Legnum, Evo) need this to enter
  diagnostic mode. VAG KKL cables do not connect pin 1. Add a switch to GND, or drive
  it from DTR/RTS via a transistor so software can toggle it on re-init.
- **L-line**: plain MUT-II uses K only. Some later JOBD/hybrid ECUs reportedly need
  L driven during 5-baud init — check if the cable even wires pin 15.

### Checks still to do on the cable

1. Read the chip marking (BL vs RL; possible clone).
2. Measure VCCIO (pin 13 on BL) with USB connected.
3. Scope/logic-analyser TXD (pin 25): break works, 15625 baud bit = 64 µs.
4. Check for a 93C46 EEPROM with custom VID/PID (inspect with FT_Prog or libftdi
   `ftdi_eeprom`). PID 0000 = clone bricked by old FTDI driver, recoverable in FT_Prog.
5. Set latency timer to 1 ms in Device Manager → port properties (Windows).

## MUT-II protocol summary

- 5-baud init: send the module address at 5 baud, 8N1, LSB first (200 ms/bit).
- Engine ECU address = **0x00** (confirmed by libftdimut). NOT 0x01 — 0x01 is TCU.
  Module map used in the user's Pico firmware: ECU 0x00, TCU 0x01, ABS 0x02,
  SRS 0x03, A/C 0x04.
- Standard ISO 9141 init uses 0x33 instead — not what MUT-II wants.
- After init: 15625 baud, 8N1. ECU typically sends 4 bytes (reported as C0 55 EF 85;
  libftdimut only checks that 4 bytes arrive, not their content).
- Request/response: send 1 command byte → read 2 bytes (echo + value).
- 0xFE / 0xFF commonly used to read the 2-byte ROM/ECU ID.
- Session times out after ~10–15 s without requests → re-init.
- Retry pattern from forum implementation: if no response, release pin 1, wait
  ~500 ms, start over.
- **Danger**: on some ECUs 0xF1–0xFC fire actuators / cut injectors for 6 s and 0xCA
  clears DTCs. Stick to data-range requests and 0xFE/0xFF while testing.

## Reference implementation: niallm90/libftdimut

- https://github.com/niallm90/libftdimut
- https://github.com/niallm90/libftdimut-example

Written for a Tactrix Openport 1.3 (FTDI-based) using D2XX:

- `FT_SetVIDPID(0x0403, 0xCC4A)` — Openport PID. A KKL cable is likely 0403:6001;
  change `USB_PID` in `libftdimut.h` (on Linux also unload `ftdi_sio`).
- 15625 baud, 8N1, no flow control, 1000 ms read/write timeouts, latency timer 1 ms.
- `ftdimut_init()`:
  1. Sends 0x17; if the reply is non-zero it assumes the session is alive and skips init.
  2. Otherwise `FT_SetBreakOn`, sleep **1800 ms** (start bit + 8 zero bits = 0x00 at
     5 baud), `FT_SetBreakOff`, then immediately `FT_Read` 4 bytes.
- `ftdimut_getData(req)`: write 1 byte, read 2 bytes, return `buf[1]`.

Known weaknesses:

- `getData` returns 0 both on error and for a genuine value of 0 → the 0x17
  "is session alive" test can trigger an unnecessary re-init.
- No handling of OBD pin 1.
- Break-only init can only send 0x00. Toggling break per bit (see script below)
  generalises it to any module address on the same FTDI hardware.

## Python sketch (pyserial, FTDI VCP COM port)

Corrected version. Earlier draft had two bugs: it used address 0x01, and it flushed
the RX buffer *after* the stop bit, which could discard the ECU's sync bytes
(W1 can be as short as ~20 ms). Flush **before** init; read immediately after.

```python
import serial, time

PORT = "COM5"          # adjust
s = serial.Serial(PORT, 15625, bytesize=8, parity="N", stopbits=1, timeout=1.0)

def wait_until(t):
    while time.perf_counter() < t:
        pass                                   # busy-wait: better than sleep on Windows

def five_baud(addr):
    s.break_condition = False
    time.sleep(0.4)                            # idle before init
    s.reset_input_buffer()                     # flush BEFORE init
    bits = [0] + [(addr >> i) & 1 for i in range(8)]   # start + 8 data bits, LSB first
    t = time.perf_counter()
    for b in bits:
        s.break_condition = (b == 0)           # break = TXD low
        t += 0.2
        wait_until(t)
    s.break_condition = False                  # stop bit / idle; read right away

def query(cmd):
    s.write(bytes([cmd]))
    data = s.read(2)                           # echo + value
    if len(data) != 2:
        return None                            # distinguish "no reply" from value 0
    return data[1]

def connect(addr=0x00, retries=3):
    for _ in range(retries):
        five_baud(addr)
        sync = s.read(4)
        print("sync:", sync.hex())
        hi, lo = query(0xFE), query(0xFF)
        if hi is not None and lo is not None:
            print("ECU ID: %02X%02X" % (hi, lo))
            return True
        time.sleep(0.5)
    return False

if connect(0x00):
    print("RPM-ish test / data request here")
```

For 0x00 this produces exactly libftdimut's waveform (1800 ms low, then idle).

## Pico alternative (reference only)

- Existing separate project: Pico 2 W (RP2350), MicroPython firmware with bit-banged
  multi-module 5-baud init, WiFi AP and USB-serial (JSON) variants, C# WPF .NET 8
  desktop app.
- If transplanting a Pico into the KKL cable:
  - Physically disconnect FTDI TXD/RXD (lift pins or cut traces); don't rely on reset.
  - Pico RX: RP2040 is not 5 V tolerant; RP2350 only when IOVDD is powered — use a
    divider (e.g. 10k/20k) or move an open-collector pull-up to 3.3 V.
  - Pico TX at 3.3 V may not reach VIH of a 5 V transceiver input (check L9637D
    datasheet; LM339 depends on reference; NPN stage usually fine). Use 74HCT125 if needed.
  - Common ground: Pico, transceiver, OBD 4/5.

## Open questions / next steps

1. Identify car model/year → pure MUT-II vs OBD2/JOBD hybrid (affects address and L-line).
2. Identify the cable's transceiver and confirm VCCIO.
3. Verify break timing and 15625 baud on a scope.
4. Decide on pin-1 grounding method (manual switch vs DTR/RTS transistor).
5. Run the Python sketch against the ECU (ignition ON), log raw bytes.
6. Optionally port libftdimut logic to C#/.NET to plug into the existing WPF app,
   or build a small Python CLI/daemon.
