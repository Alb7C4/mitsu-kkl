# mitsu-kkl

**MUT-II diagnostics for 1990s Mitsubishi engine ECUs over a cheap VAG "KKL" USB cable.**

*[Polski](README.pl.md) — full manual in Polish.*

Many late-90s Mitsubishi cars only talk Mitsubishi's own MUT-II protocol: 5-baud init to
address 0x00, then 15625 baud, and only while OBD pin 1 is grounded. Most generic scan tools
never get an answer. This project talks to such an ECU from a PC through the simplest
USB-to-K-line cable, and adds a probe that tries many init methods, speeds and addresses
and logs every byte, for cars where nobody knows what works.

Developed and tested on a **Mitsubishi Eclipse 1998 2.0 16V 4G63 (EU)**, engine ECU ID `E4 3A`.

## What's inside

| tool | what it does |
|---|---|
| **`mut_gui`** | Live data viewer: any of the 190+ readable PIDs with your own names and conversions, change highlighting, min/max, CSV recording, fault code view, PID list profiles, automatic reconnect. |
| **`kkl_probe`** | Command-line probe: self-test of the cable, MUT-II / ISO 9141-2 / KWP2000 slow and fast init / DSM 1953 baud, address scans, a full test matrix, fault code reading. Every run is logged byte by byte with timestamps. |

Both tools are **read-only by design** (see [Safety](#safety)).

## Hardware

- **A "dumb" KKL cable**: USB-UART chip + K-line transceiver, sold as "VAG KKL 409.1".
  - **FTDI FT232** works best (used through the FTDI D2XX driver; the only mode with bit-bang init and line error flags).
  - CH340, PL2303 or CP210x work through their COM port **if the chip can run 15625 baud and send a break**. Many old or fake PL2303 chips only do standard baud rates.
  - **ELM327 interfaces do not work**: they cannot do the MUT-II init at 15625 baud.
- **OBD pin 1 → ground (pin 4 or 5).** VAG cables don't wire pin 1, so add a wire, ideally with a switch.
  With pin 1 grounded and ignition on, the check-engine light starts blinking fault codes. That is normal: the ECU is in diagnostic mode.

OBD pins used: 7 = K-line, 16 = +12 V, 4/5 = ground, 1 = diagnostic mode.

## Download and run (Windows)

1. Get `mitsu-kkl-<version>-windows.zip` from **[Releases](../../releases)** and unzip it anywhere.
2. For an FTDI cable, install the FTDI driver (VCP + D2XX) from [ftdichip.com](https://ftdichip.com/drivers/). Windows often installs it by itself.
3. Plug the cable into the car, ground pin 1, switch the ignition on (engine may stay off).
4. Start **`mut_gui.exe`**, pick the cable in the *Interface* list (or leave *Automatic*), press *Connect*.

The .exe files are not signed, so Windows SmartScreen may warn on first start ("More info" → "Run anyway").
Settings, PID definitions and logs are kept next to the .exe.

No car at hand? `mut_gui.exe --backend sim --sim mutlive --connect` runs a simulated ECU.

## Run from source

Tested with Python 3.14 on Windows 10.

```
pip install pyserial
pythonw mut_gui.py
python kkl_probe.py selftest
```

`build_exe.ps1` builds the two .exe files and the release zip with PyInstaller.

## kkl_probe quick reference

```
python kkl_probe.py info                     # cable chip, driver, all detected interfaces (sends nothing)
python kkl_probe.py selftest                 # is the cable powered from the OBD socket and hearing its own echo?
python kkl_probe.py scan [--full]            # try all init methods / speeds / addresses, ~2-5 min
python kkl_probe.py mut --addr 00 --repeat 100   # connect to the engine ECU and poll live values
python kkl_probe.py dtc                      # read fault code bytes
python kkl_probe.py report                   # summary of all attempts so far
```

Other commands: `listen`, `mutdump`, `iso`, `kwpfast`, `dsm`, `addrscan`, `clear`. Run `--help` on any command.
Results are ranked `NO_ECHO` < `SILENT` < `NOISE` < `SYNC` < `HANDSHAKE` < `DATA`; logs go to `logs/`.

## What was found on the test car

| 5-baud address | baud | sync bytes | ID (FE/FF) | pin 1 grounded | pin 1 open |
|---|---|---|---|---|---|
| **0x00 engine** | 15625 | `55 EF 85` | `E4 3A` | answers all 192 read requests 00–BF | silent |
| **0x04 unknown module** | 10400 | `55 73 85` | `B1 01` | answers | silent |
| 0x01–0x03, 0x05–0xFF | – | – | – | silent | – |
| ISO 9141-2 (0x33), KWP2000 fast init, DSM 1953 | – | – | – | silent | silent |

- No `~KB2` acknowledgement is needed after the sync bytes; each request is 1 byte, the answer is echo + 1 byte.
- Fault codes: PID `40/41` = active, `45/46` = stored, one bit per Mitsubishi code (bit 2 = 13, bit 3 = 14, bit 5 = 21, bit 9 = 25 confirmed).
- Erasing codes with MUT `0xCA` does **not** work on this ECU; disconnecting the battery does.
- The PID map built so far (coolant, intake air, timing, idle target, injector pulse, fuel trims, throttle flags…) is in [PID_znaczenia.md](PID_znaczenia.md) (Polish) and ships as names/conversions in the PID definitions file.
- Addresses 00–7F match the [EvoEcu MUT request list](https://evoecu.logic.net/wiki/MUT_Requests) (not shifted); fault code layout and 80–BF differ.

Other Mitsubishi models of the same era may use the same init; results and PID meanings will differ per ECU.

## Safety

Only read requests can be sent: MUT `0x00–0xBF` and `0xFD–0xFF`, OBD/KWP services 01, 02, 03, 07, 09
plus session control. MUT `0xC0–0xFC` is blocked in code before anything reaches the K-line: on MUT-II
ECUs `0xCA` erases fault codes and `0xF1–0xFC` fire actuators or cut injectors. The only exception is
`kkl_probe.py clear --yes`, which sends `0xCA` to the engine ECU with the engine stopped.

Use at your own risk. This project is not affiliated with Mitsubishi Motors.

## More documentation

- [README.pl.md](README.pl.md): full manual in Polish (every GUI function, all commands, test procedure)
- [PID_znaczenia.md](PID_znaczenia.md): PID meanings found on the test car (Polish)
- [mut2-ftdi-kkl-handoff.md](mut2-ftdi-kkl-handoff.md): background notes on MUT-II and the FTDI cable

## License

[MIT](LICENSE)
