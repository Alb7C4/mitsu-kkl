"""K-line sniffer with a Raspberry Pi Pico: capture every edge with 1 us resolution, then decode.

The Pico runs pico/sniffer.py (sent over USB, nothing is installed on it) and only LISTENS:
connect the receiver output of a K-line cable (e.g. the RXD pin of the CH340 chip, through a
divider if it is a 5 V signal) to a GPIO, plus ground.

    python tools/sniff_pico.py                    # finds the Pico, GP1, stop with Ctrl+C
    python tools/sniff_pico.py --pin 1 --pull up --port COM7
    python tools/sniff_pico.py --decode logs/<file>_pico_sniff.txt   # decode a saved capture again
    python tools/sniff_pico.py --selftest         # decoder check without hardware

Output in logs/: <time>_pico_sniff.txt (raw capture) and <time>_pico_sniff_decoded.txt:
5-baud init frames with the address byte and the bit time, then the bytes at the detected baud
rate (15625 / 10400 / 9600 / 1953) with timestamps.
"""
import argparse
import base64
import bisect
import re
import struct
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIRMWARE = ROOT / "pico" / "sniffer.py"
BAUDS = (15625, 10400, 9600, 1953)
SLOW_MIN_US = 100_000     # a low longer than this is part of a 5-baud frame, not a UART byte
BURST_GAP_US = 20_000     # bytes closer than this are decoded together (one baud rate per burst)
LINE_GAP_US = 10_000      # new output line after this much silence


# ----------------------------------------------------------------------------- capture parsing

def parse_capture(lines):
    """Raw capture lines -> (edges [(t_us, level)], notes). The first entry is the start level."""
    words, notes = [], []
    for line in lines:
        line = line.strip()
        if line.startswith("D "):
            data = base64.b64decode(line[2:])
            words.extend(struct.unpack("<%dI" % (len(data) // 4), data[: len(data) // 4 * 4]))
        elif line and not line.startswith("#"):
            notes.append(line)
    edges = []
    t = 0
    prev = None
    for w in words:
        x, lvl = w >> 1, w & 1
        if prev is not None:
            t += ((prev - x) & 0x7FFFFFFF) + 1   # +1: the tick the PIO spends on each edge
        prev = x
        edges.append((t, lvl))
    return edges, notes


def to_segments(edges, invert=None):
    """Edges -> list of (start_us, level) with real level changes only; level 1 = idle (recessive).
    invert=None picks the idle level automatically (the level the line spends most time in)."""
    seg = []
    for t, lvl in edges:
        if not seg or seg[-1][1] != lvl:
            seg.append((t, lvl))
    if invert is None:
        time_in = [0, 0]
        for (t, lvl), (t2, _) in zip(seg, seg[1:]):
            time_in[lvl] += t2 - t
        invert = time_in[0] > time_in[1]
    if invert:
        seg = [(t, 1 - lvl) for t, lvl in seg]
    return seg, invert


class Line:
    def __init__(self, seg):
        self.seg = seg
        self.times = [t for t, _ in seg]
        self.end = seg[-1][0] if seg else 0

    def level(self, t):
        i = bisect.bisect_right(self.times, t) - 1
        return self.seg[i][1] if i >= 0 else 1

    def duration(self, i):
        return (self.seg[i + 1][0] if i + 1 < len(self.seg) else self.end) - self.seg[i][0]


# ----------------------------------------------------------------------------- decoding

def find_slow_frames(line):
    """5-baud frames: a falling edge followed by a low >= 100 ms or by bits of ~200 ms."""
    frames = []
    i, n = 0, len(line.seg)
    while i < n:
        t, lvl = line.seg[i]
        if lvl == 0 and line.duration(i) >= SLOW_MIN_US and (not frames or t >= frames[-1]["end"]):
            parts = []
            j = i
            while j < n and line.seg[j][0] - t < 2_000_000 and line.duration(j) >= SLOW_MIN_US * 0.8:
                parts.append((line.seg[j][1], line.duration(j)))
                j += 1
            if parts and parts[-1][0] == 1:
                parts = parts[:-1]          # the last high is stop bit + idle: unknown length
            nbits = sum(max(1, round(d / 200_000)) for _, d in parts)
            bit = sum(d for _, d in parts) / nbits if nbits else 200_000
            bits = [line.level(t + (k + 0.5) * bit) for k in range(10)]
            addr = sum(b << k for k, b in enumerate(bits[1:9]))
            frames.append({"t": t, "addr": addr, "bit": bit, "start_ok": bits[0] == 0,
                           "stop_ok": bits[9] == 1, "end": t + 10 * bit})
            while i < n and line.seg[i][0] < t + 9.5 * bit:
                i += 1
            continue
        i += 1
    return frames


def decode_uart(line, starts, baud):
    """Decode bytes starting at the given falling edges. -> list of (t, byte, framing_error, misaligned)."""
    T = 1e6 / baud
    out = []
    free = -1
    for s in starts:
        if s < free:
            continue
        if line.level(s + 0.5 * T) != 0:
            continue                         # glitch, not a start bit
        byte = sum(line.level(s + (k + 1.5) * T) << k for k in range(8))
        fe = line.level(s + 9.5 * T) != 1
        i0 = bisect.bisect_right(line.times, s)
        i1 = bisect.bisect_left(line.times, s + 9.5 * T)
        mis = sum(1 for t in line.times[i0:i1] if abs((t - s) / T - round((t - s) / T)) > 0.3)
        out.append((s, byte, fe, mis))
        free = s + 9.5 * T
    return out


def decode(edges, invert=None, baud=None):
    seg, inverted = to_segments(edges, invert)
    line = Line(seg)
    frames = find_slow_frames(line)
    slow = [(f["t"], f["end"]) for f in frames]
    falls = [t for t, lvl in seg if lvl == 0 and not any(a <= t < b for a, b in slow)]
    bursts, cur = [], []
    for t in falls:
        if cur and t - cur[-1] > BURST_GAP_US:
            bursts.append(cur)
            cur = []
        cur.append(t)
    if cur:
        bursts.append(cur)
    data = []
    for b in bursts:
        options = [baud] if baud else BAUDS
        best = None
        for bd in options:
            res = decode_uart(line, b, bd)
            score = sum(fe + mis for _, _, fe, mis in res) / max(1, len(res))
            if best is None or score < best[0] - 1e-9:
                best = (score, bd, res)
        _, bd, res = best
        data.extend((t, byte, fe, bd) for t, byte, fe, _ in res)
    return {"frames": frames, "data": data, "inverted": inverted, "edges": len(edges),
            "span_us": line.end}


def report(res):
    out = []
    span = res["span_us"] / 1e6
    out.append(f"edges: {res['edges']}, capture length {span:.1f} s, idle level "
               f"{'LOW (inverted receiver)' if res['inverted'] else 'HIGH'}")
    out.append(f"5-baud init frames: {len(res['frames'])}"
               + (f", addresses: {' '.join(sorted({'%02X' % f['addr'] for f in res['frames']}))}"
                  if res["frames"] else ""))
    bauds = sorted({bd for *_, bd in res["data"]}, reverse=True)
    out.append(f"UART bytes: {len(res['data'])}" + (f" at {', '.join(map(str, bauds))} baud" if bauds else "")
               + f", framing errors: {sum(1 for _, _, fe, _ in res['data'] if fe)}")
    out.append("")
    out.append("      t [ms]     gap [ms]  event")
    events = [(f["t"], "init", f) for f in res["frames"]] + [(d[0], "byte", d) for d in res["data"]]
    events.sort(key=lambda e: e[0])
    prev_end = None
    cur = None
    last_frame_end = None

    def flush():
        if cur:
            t0, gap, bd, items, after = cur
            gap_s = f"{gap / 1000:+10.1f}" if gap is not None else " " * 10
            note = f"   ({after / 1000:.1f} ms after the init stop bit)" if after is not None else ""
            out.append(f"{t0 / 1000:12.3f} {gap_s}  {bd:>5}: {' '.join(items)}{note}")

    for t, kind, ev in events:
        if kind == "init":
            flush()
            cur = None
            gap = None if prev_end is None else t - prev_end
            gap_s = f"{gap / 1000:+10.1f}" if gap is not None else " " * 10
            out.append(f"{t / 1000:12.3f} {gap_s}  INIT 5 baud: address 0x{ev['addr']:02X}  "
                       f"(bit {ev['bit'] / 1000:.1f} ms, start {'ok' if ev['start_ok'] else 'BAD'}, "
                       f"stop {'ok' if ev['stop_ok'] else 'BAD'})")
            prev_end = last_frame_end = ev["end"]
            continue
        _, byte, fe, bd = ev
        T = 1e6 / bd
        item = f"{byte:02X}" + ("!" if fe else "")
        if cur is None or t - prev_end > LINE_GAP_US or len(cur[3]) >= 16 or cur[2] != bd:
            flush()
            after = None
            if last_frame_end is not None:
                after = t - last_frame_end
                last_frame_end = None
            cur = [t, None if prev_end is None else t - prev_end, bd, [], after]
        cur[3].append(item)
        prev_end = t + 10 * T
    flush()
    out.append("")
    out.append("'!' = framing error (stop bit low). gap = silence since the previous event ended.")
    return "\n".join(out)


# ----------------------------------------------------------------------------- Pico over USB

def find_pico():
    from serial.tools import list_ports
    for p in list_ports.comports():
        if p.vid == 0x2E8A:
            return p.device
    return None


def read_until(ser, marker, timeout):
    buf = b""
    end = time.time() + timeout
    while time.time() < end:
        buf += ser.read(ser.in_waiting or 1)
        if marker in buf:
            return buf
    raise TimeoutError(f"no {marker!r} from the Pico, got {buf[-200:]!r}")


def capture(args):
    import serial
    port = args.port or find_pico()
    if not port:
        sys.exit("No Pico found on USB (VID 2E8A). Is MicroPython on it? Use --port COMx.")
    code = FIRMWARE.read_text(encoding="utf-8")
    code = re.sub(r"^PIN = \d+", f"PIN = {args.pin}", code, count=1, flags=re.M)
    code = re.sub(r'^PULL = "[a-z]*"', f'PULL = "{args.pull}"', code, count=1, flags=re.M)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    raw_path = ROOT / "logs" / f"{stamp}_pico_sniff.txt"
    raw_path.parent.mkdir(exist_ok=True)
    ser = serial.Serial(port, 115200, timeout=0.2)
    ser.write(b"\r\x03\x03")                 # stop whatever runs on the Pico (e.g. main.py)
    time.sleep(0.3)
    ser.reset_input_buffer()
    ser.write(b"\r\x01")                     # raw REPL
    read_until(ser, b"raw REPL; CTRL-B to exit\r\n>", 3)
    data = code.encode()
    for i in range(0, len(data), 256):
        ser.write(data[i:i + 256])
        time.sleep(0.01)
    ser.write(b"\x04")
    read_until(ser, b"OK", 3)

    print(f"Pico on {port}, input GP{args.pin} (pull: {args.pull or 'none'}), receive only.")
    print(f"Raw capture: {raw_path}")
    print("Start the other program now. Ctrl+C stops the capture and decodes it.")
    lines = [f"# pico sniff port={port} pin=GP{args.pin} pull={args.pull or 'none'} start={datetime.now().isoformat(timespec='milliseconds')}"]
    words = 0
    t0 = time.time()
    last_status = 0
    finished = False
    with open(raw_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(lines[0] + "\n")
        try:
            buf = b""
            while not (args.seconds and time.time() - t0 >= args.seconds):
                buf += ser.read(ser.in_waiting or 1)
                if b"\x04" in buf:            # the program on the Pico ended (error?)
                    head, _, tail = buf.partition(b"\x04")
                    buf = head
                    err = tail + read_until(ser, b"\x04>", 2) if b"\x04>" not in tail else tail
                    print("Pico stopped:", err.replace(b"\x04", b"").replace(b">", b"").decode(errors="replace").strip())
                    finished = True
                while b"\n" in buf:
                    raw, _, buf = buf.partition(b"\n")
                    s = raw.decode(errors="replace").strip()
                    if not s:
                        continue
                    f.write(s + "\n")
                    lines.append(s)
                    if s.startswith("D "):
                        words += len(base64.b64decode(s[2:])) // 4
                    else:
                        print("Pico:", s)
                if finished:
                    break
                if time.time() - last_status >= 1:
                    last_status = time.time()
                    print(f"\r  {time.time() - t0:6.1f} s  edges: {max(0, words - 1)}   ", end="", flush=True)
        except KeyboardInterrupt:
            pass
        if not finished:
            ser.write(b"\x03")               # KeyboardInterrupt on the Pico -> it prints END
            try:
                rest = read_until(ser, b"\x04>", 3)
            except TimeoutError as e:
                rest = b""
                print("\n", e)
            for raw in rest.split(b"\x04")[0].split(b"\n"):
                s = raw.decode(errors="replace").strip()
                if s:
                    f.write(s + "\n")
                    lines.append(s)
    ser.write(b"\x02")                       # leave raw REPL
    ser.close()
    print()
    return raw_path, lines


def selftest():
    """Build a synthetic capture (two 0x33 inits, one 0x00 init + 55 EF 85 + MUT polling) and decode it."""
    seg = [(0, 1)]
    t = 500_000

    def level(lv, dur):
        nonlocal t
        seg.append((t, lv))
        t += dur

    def slow(addr, bit=205_000):
        for b in [0] + [(addr >> k) & 1 for k in range(8)] + [1]:
            level(b, bit)

    def uart(data, baud, gap=2_000):
        nonlocal t
        T = int(1e6 / baud)
        for byte in data:
            for b in [0] + [(byte >> k) & 1 for k in range(8)] + [1]:
                level(b, T)
            level(1, gap)

    slow(0x33); level(1, 900_000); slow(0x33); level(1, 900_000)
    slow(0x00, 200_000); level(1, 100_000)
    uart([0x55, 0xEF, 0x85], 15625, gap=12_000)
    level(1, 100_000)
    uart([0xFE, 0xE4, 0xFF, 0x3A, 0x14, 0xA6, 0x21, 0x23], 15625, gap=2_500)
    level(1, 1_000_000)
    uart([0x55, 0x73, 0x85], 10400, gap=10_000)
    level(1, 10_000)
    words = []
    prev_t = None
    x = 0x7FFFFFFF
    for st, lv in seg:
        if prev_t is not None:
            x = (x - (st - prev_t) + 1) & 0x7FFFFFFF
        prev_t = st
        words.append((x << 1) | lv)
    blob = struct.pack("<%dI" % len(words), *words)
    lines = ["D " + base64.b64encode(blob[i:i + 384]).decode() for i in range(0, len(blob), 384)]
    edges, _ = parse_capture(lines)
    res = decode(edges)
    text = report(res)
    print(text)
    assert [f["addr"] for f in res["frames"]] == [0x33, 0x33, 0x00], res["frames"]
    got = [(b, bd) for _, b, fe, bd in res["data"]]
    want = [(b, 15625) for b in (0x55, 0xEF, 0x85, 0xFE, 0xE4, 0xFF, 0x3A, 0x14, 0xA6, 0x21, 0x23)] + \
           [(b, 10400) for b in (0x55, 0x73, 0x85)]
    assert got == want, got
    assert not any(fe for _, _, fe, _ in res["data"])
    print("\nselftest OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", help="Pico COM port (default: found by USB ID)")
    ap.add_argument("--pin", type=int, default=1, help="GPIO with the receiver output (default 1)")
    ap.add_argument("--pull", choices=["", "up", "down"], default="", help="internal pull resistor")
    ap.add_argument("--seconds", type=float, default=0, help="stop after this many seconds (0 = Ctrl+C)")
    ap.add_argument("--baud", type=int, help="decode at this baud rate only (default: detect per burst)")
    ap.add_argument("--idle", choices=["auto", "high", "low"], default="auto",
                    help="idle level of the receiver output (default: detect)")
    ap.add_argument("--decode", metavar="FILE", help="decode a saved raw capture instead of capturing")
    ap.add_argument("--selftest", action="store_true", help="check the decoder on a synthetic capture")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.decode:
        raw_path = Path(args.decode)
        lines = raw_path.read_text(encoding="utf-8").splitlines()
    else:
        raw_path, lines = capture(args)
    edges, notes = parse_capture(lines)
    for n in notes:
        if n.startswith("LOST"):
            print("WARNING: the Pico could not keep up, edges were lost:", n)
    if len(edges) < 2:
        print("No edges captured. Check the wiring (receiver output -> GPIO, common ground) and --pin.")
        return
    invert = {"auto": None, "high": False, "low": True}[args.idle]
    text = report(decode(edges, invert, args.baud))
    out = raw_path.with_name(raw_path.stem + "_decoded.txt")
    out.write_text(text + "\n", encoding="utf-8")
    shown = text.splitlines()
    print("\n".join(shown[:80]))
    if len(shown) > 80:
        print(f"... {len(shown) - 80} more lines")
    print(f"\nDecoded: {out}")


if __name__ == "__main__":
    sys.exit(main())
