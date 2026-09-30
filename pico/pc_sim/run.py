#!/usr/bin/env python3
"""Run the Pico firmware on a PC against the simulated ECU, to test the firmware and the page
without hardware. The firmware files run unchanged; machine/network come from this folder.

  python pico/pc_sim/run.py                  # http://127.0.0.1:8766/
  python pico/pc_sim/run.py --sim dead       # cable without power: "ECU not responding (SILENT)"
"""

import argparse
import asyncio
import builtins
import json
import os
import runpy
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PICO, ROOT = HERE.parent, HERE.parent.parent
sys.path[:0] = [str(HERE), str(PICO), str(ROOT)]

# The MicroPython-only helpers the firmware uses
time.ticks_ms = lambda: int(time.perf_counter() * 1000)
time.ticks_diff = lambda a, b: a - b
time.ticks_add = lambda a, b: a + b
time.sleep_ms = lambda ms: time.sleep(ms / 1000)
asyncio.sleep_ms = lambda ms: asyncio.sleep(ms / 1000)

# MicroPython always reads and writes text files as UTF-8; Windows Python would use cp1250.
_open = builtins.open


def _utf8_open(file, mode="r", *args, **kwargs):
    if "b" not in mode and not args and "encoding" not in kwargs:
        kwargs["encoding"] = "utf-8"
    return _open(file, mode, *args, **kwargs)


builtins.open = _utf8_open

import machine  # noqa: E402  (pc_sim/machine.py)
from deploy import stage  # noqa: E402
from kkl.link import hires_timer  # noqa: E402
from kkl.sim import SimDevice  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8766, help="web port (default 8766)")
    ap.add_argument("--sim", default="mutlive", help="simulated ECU model (mutlive, mut, none, dead)")
    ap.add_argument("--dir", help="folder used as the Pico's flash (default: a new temp folder)")
    ap.add_argument("--run", help="run this script from pico/ instead of main.py, e.g. benchtest.py")
    args = ap.parse_args()

    flash = stage(Path(args.dir or tempfile.mkdtemp(prefix="mitsu-kkl-pico-flash-")),
                  {"http_port": args.port})
    os.chdir(flash)
    sys.path.insert(0, str(flash))  # on the Pico the flash root is on the import path (version.py)
    cfg = json.loads((flash / "config.json").read_text(encoding="utf-8"))
    machine.SIM = SimDevice(args.sim)
    machine.TX_GPIO, machine.RX_GPIO = cfg["tx_gpio"], cfg["rx_gpio"]
    machine.TX_INVERT, machine.RX_INVERT = int(cfg["invert_tx"]), int(cfg["invert_rx"])
    print(f"Pico flash folder: {flash}")
    hires_timer(True)
    if args.run:
        runpy.run_path(str(PICO / args.run), run_name="__main__")
        return
    import main as firmware  # pico/main.py
    asyncio.run(firmware.main())


if __name__ == "__main__":
    main()
