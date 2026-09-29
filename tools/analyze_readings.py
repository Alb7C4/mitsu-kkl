#!/usr/bin/env python3
"""Offline analysis of mut_gui recordings, used to work out what MUT PIDs mean.

Reads logs/<time>_readings_<nr>.csv (English format: ',' and decimal point), the older
logs/<time>_odczyty*.csv (Polish format: ';' and decimal comma) and logs/<time>_gui_changes*.csv.

  python tools/analyze_readings.py summary  FILE           which PIDs changed, with hints
  python tools/analyze_readings.py timeline FILE 21,10,24  change points as t:value
  python tools/analyze_readings.py window   FILE 26 34     PIDs that change between 26 s and 34 s
  python tools/analyze_readings.py bits     FILE A8,71     per-bit change points of flag bytes
  python tools/analyze_readings.py corr     FILE 17        PIDs that move together with PID 17
  python tools/analyze_readings.py changes  FILE           summary of a *_gui_changes.csv

Times are seconds from the start of the recording (column "t [s]").
"""

import argparse
import csv
import re
import statistics
import sys
from pathlib import Path

# Values that cycle by themselves in 83, 94-99, A1, A2 and B4-BF on ECU E4 3A (internal buffer).
ROTATING = {0, 36, 50, 105}
PID_COL = re.compile(r"^([0-9A-F]{2})(\s|$)")


def read_rows(path):
    text = Path(path).read_text(encoding="utf-8-sig")
    first = text.split("\n", 1)[0]
    sep = ";" if first.count(";") > first.count(",") else ","
    return [r for r in csv.reader(text.splitlines(), delimiter=sep) if r]


def number(s):
    try:
        return float(s.strip().replace(",", "."))
    except ValueError:
        return None


class Recording:
    """Snapshot recording: one row per polling cycle, one raw (decimal) column per PID.
    Converted columns ('... [unit]', '... (converted)', '... (przeliczona)') are skipped."""

    def __init__(self, path):
        rows = read_rows(path)
        head, data = rows[0], rows[1:]
        cols = {}
        for i, h in enumerate(head):
            h = h.strip()
            m = PID_COL.match(h)
            if m and "[" not in h and not h.endswith(("(converted)", "(przeliczona)")):
                cols[m.group(1)] = i
        self.names = {p: head[i].strip() for p, i in cols.items()}
        self.wall = [r[0] for r in data]
        self.t = [number(r[1]) for r in data]
        self.v = {}
        for p, i in cols.items():
            col = []
            for r in data:
                x = number(r[i]) if i < len(r) else None
                col.append(None if x is None else int(x))
            self.v[p] = col

    def changed(self):
        return {p: s for p, s in self.v.items() if len({x for x in s if x is not None}) > 1}


def hints(pid, series, changed):
    vals = [x for x in series if x is not None]
    out = []
    for other, s2 in changed.items():
        if other == pid:
            continue
        pairs = [(a, b) for a, b in zip(series, s2) if a is not None and b is not None]
        if pairs and all(a == b for a, b in pairs):
            out.append(f"= {other}")
        elif pairs and max(abs(a - b) for a, b in pairs) <= 2:
            out.append(f"~ {other}")
    distinct = set(vals)
    flipped = 0
    for a, b in zip(vals, vals[1:]):
        flipped |= a ^ b
    bits = [b for b in range(8) if flipped >> b & 1]
    if distinct <= ROTATING:
        out.append("rotating buffer?")
    elif len(distinct) <= 16 and len(bits) <= 5:  # few values, few bits: looks like a flag byte
        out.append("bits " + ",".join(map(str, bits)))
    steps = [abs(a - b) for a, b in zip(vals, vals[1:]) if a != b]
    if len(distinct) > 40 and steps and statistics.median(steps) > 20:
        out.append("noisy (low byte?)")
    return " ".join(out)


def cmd_summary(args):
    head = read_rows(args.file)[0]
    if "pid" in head and "old" in head:
        return cmd_changes(args)
    rec = Recording(args.file)
    ts = [x for x in rec.t if x is not None]
    dts = [b - a for a, b in zip(ts, ts[1:])]
    changed = rec.changed()
    print(f"{Path(args.file).name}: rows={len(ts)} span={ts[-1] - ts[0]:.1f} s "
          f"cycle~{statistics.median(dts) if dts else 0:.2f} s  PIDs={len(rec.v)} changed={len(changed)}")
    if len(rec.v) <= 40:
        print("recorded:", " ".join(rec.v))
    print(" PID  min  max first last distinct  hints")
    for p, s in sorted(changed.items(), key=lambda kv: -(max(x for x in kv[1] if x is not None)
                                                         - min(x for x in kv[1] if x is not None))):
        vals = [x for x in s if x is not None]
        print(f"  {p} {min(vals):4d} {max(vals):4d} {vals[0]:5d} {vals[-1]:4d} {len(set(vals)):8d}  "
              f"{hints(p, s, changed)}")


def pid_list(text):
    return [p.strip().upper().zfill(2) for p in text.split(",") if p.strip()]


def cmd_timeline(args):
    rec = Recording(args.file)
    for p in pid_list(args.pids):
        if p not in rec.v:
            print(f"[{p}] not recorded in this file")
            continue
        pts, prev = [], object()
        for t, x in zip(rec.t, rec.v[p]):
            if x != prev:
                pts.append(f"{t:.1f}:{x}")
                prev = x
        if len(pts) > args.max:
            pts = pts[:args.max // 2] + ["..."] + pts[-args.max // 2:]
        print(f"[{p}] " + " ".join(pts))


def cmd_window(args):
    rec = Recording(args.file)
    idx = [k for k, t in enumerate(rec.t) if t is not None and args.t0 <= t <= args.t1]
    cols = [p for p, s in rec.v.items() if len({s[k] for k in idx}) > 1]
    print("wall time      t     " + " ".join(f"{p:>4}" for p in cols))
    for k in idx:
        print(f"{rec.wall[k][-12:]:>12} {rec.t[k]:6.1f} "
              + " ".join(f"{'-' if rec.v[p][k] is None else rec.v[p][k]:>4}" for p in cols))


def cmd_bits(args):
    rec = Recording(args.file)
    for p in pid_list(args.pids):
        if p not in rec.v:
            print(f"[{p}] not recorded in this file")
            continue
        for b in range(7, -1, -1):
            pts, prev = [], None
            for t, x in zip(rec.t, rec.v[p]):
                if x is None:
                    continue
                bit = x >> b & 1
                if bit != prev:
                    pts.append(f"{t:.1f}:{bit}")
                    prev = bit
            if len(pts) > 1:
                shown = pts if len(pts) <= args.max else pts[:args.max] + [f"... ({len(pts)} changes)"]
                print(f"[{p} bit {b}] " + " ".join(shown))


def pearson(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    xs, ys = zip(*pairs)
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    return None if not sxx or not syy else sxy / (sxx * syy) ** 0.5


def cmd_corr(args):
    rec = Recording(args.file)
    ref = args.pid.upper().zfill(2)
    changed = rec.changed()
    if ref not in changed:
        sys.exit(f"PID {ref} does not change in this file")
    scores = [(p, pearson(changed[ref], s)) for p, s in changed.items() if p != ref]
    scores = sorted((x for x in scores if x[1] is not None), key=lambda x: -abs(x[1]))
    for p, r in scores[:args.top]:
        print(f"  {p}  r={r:+.2f}")


def cmd_changes(args):
    rows = list(csv.DictReader(Path(args.file).read_text(encoding="utf-8-sig").splitlines()))
    by = {}
    for r in rows:
        by.setdefault(r["pid"], []).append(r)
    print(f"{Path(args.file).name}: {len(rows)} highlighted changes "
          f"({rows[0]['time'][-12:]} - {rows[-1]['time'][-12:]}); only jumps >= the GUI threshold")
    for p, ev in sorted(by.items(), key=lambda kv: -len(kv[1])):
        new = [int(e["new"]) for e in ev]
        print(f"  {p}: {len(ev):4d}x  new values {min(new)}-{max(new)}  "
              f"first {ev[0]['time'][-12:]}  last {ev[-1]['time'][-12:]}")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary")
    s.add_argument("file")
    s = sub.add_parser("timeline")
    s.add_argument("file")
    s.add_argument("pids", help="e.g. 21,10,24")
    s.add_argument("--max", type=int, default=60)
    s = sub.add_parser("window")
    s.add_argument("file")
    s.add_argument("t0", type=float)
    s.add_argument("t1", type=float)
    s = sub.add_parser("bits")
    s.add_argument("file")
    s.add_argument("pids")
    s.add_argument("--max", type=int, default=30)
    s = sub.add_parser("corr")
    s.add_argument("file")
    s.add_argument("pid")
    s.add_argument("--top", type=int, default=15)
    s = sub.add_parser("changes")
    s.add_argument("file")
    args = ap.parse_args()
    globals()["cmd_" + args.cmd](args)


if __name__ == "__main__":
    main()
