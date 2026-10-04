"""Passive K-line capture through a second cable (CH340 by default on COM14). It never transmits.

    python tools/sniff_ch340.py                 # COM14, 15625 baud, stop with Ctrl+C
    python tools/sniff_ch340.py --port COM14 --baud 10400 --seconds 60

Every received chunk is written with its arrival time to logs/<time>_sniff_<port>.csv
(t_ms;gap_ms;n;hex). A slow 5-baud init shows up as 00 bytes (the line held low) separated
by gaps, so the low/high times of the init can be read from the gap column.
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import serial

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", default="COM14")
    ap.add_argument("--baud", type=int, default=15625)
    ap.add_argument("--seconds", type=float, default=0, help="stop after this many seconds (0 = Ctrl+C)")
    args = ap.parse_args()

    out = ROOT / "logs" / f"{datetime.now():%Y%m%d-%H%M%S}_sniff_{args.port}.csv"
    out.parent.mkdir(exist_ok=True)
    ser = serial.Serial(args.port, args.baud, timeout=0)
    ser.reset_input_buffer()
    print(f"Listening on {args.port} @ {args.baud} baud (receive only). Log: {out}")
    print("Start EvoScan now. Ctrl+C stops the capture.")
    t0 = time.perf_counter()
    last = None
    total = 0
    try:
        with open(out, "w", encoding="utf-8", newline="") as f:
            f.write(f"# port={args.port} baud={args.baud} start={datetime.now().isoformat(timespec='milliseconds')}\n")
            f.write("t_ms;gap_ms;n;hex\n")
            while not args.seconds or time.perf_counter() - t0 < args.seconds:
                data = ser.read(4096)
                now = time.perf_counter()
                if not data:
                    time.sleep(0.0005)
                    continue
                t_ms = (now - t0) * 1000
                gap = "" if last is None else f"{t_ms - last:.1f}"
                last = t_ms
                total += len(data)
                line = data.hex(" ")
                f.write(f"{t_ms:.1f};{gap};{len(data)};{line}\n")
                f.flush()
                print(f"{t_ms:10.1f} ms  +{gap or '-':>8} ms  {line}")
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()
    print(f"Stopped. {total} bytes captured -> {out}")


if __name__ == "__main__":
    sys.exit(main())
