"""PID list profiles: named PID lists kept in an editable ';'-separated text file.

    name ; PIDs        e.g.   Warm-up ; 10,13,14,16,21,24,29,32,58,79

The PIDs use the same syntax as the GUI's PID field (hex, ranges like 20-2F). Profiles only
hold lists; names and conversions stay in the PID definitions file.
"""

import os
from pathlib import Path

from .piddefs import format_pids, parse_pids

HEADER = (
    "# PID list profiles. Separator: semicolon. Lines starting with # are comments.",
    "# name ; PIDs (hex, ranges allowed, e.g. 07,14,20-2F)",
)
# Written into a new file; built from PIDs confirmed on the car (see PID_znaczenia.md).
EXAMPLES = {
    "Basic": "07,10,11,14,15,17,21,24,40,45",
    "Warm-up": "10,13,14,16,21,24,29,32,58,79",
    "Throttle": "00,17,1C,35,54,56,57,73,8A,AA,AC",
    "Idle and ignition": "04,16,20,21,24,25,33,76",
}


def load_profiles(path):
    """-> (profiles {name: [pid, ...]}, problems, keep). A missing file is created with EXAMPLES.
    `keep` holds the user's comment lines (and unreadable lines as comments) for save_profiles()."""
    path = Path(path)
    if not path.exists():
        save_profiles(path, {name: parse_pids(text)[0] for name, text in EXAMPLES.items()})
    profiles, problems, keep = {}, [], []
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line in HEADER:
            continue
        if line.startswith("#"):
            keep.append(line)
            continue
        name, sep, text = (x.strip() for x in line.partition(";"))
        if not sep or not name:
            problems.append(f"line {n}: expected 'name ; PIDs'")
            keep.append("# unreadable: " + line)
            continue
        pids, bad = parse_pids(text)
        if bad:
            problems.append(f"{name}: skipped {', '.join(bad[:5])} (blocked or invalid)")
        profiles[name] = pids
    return profiles, problems, keep


def save_profiles(path, profiles, keep=()):
    """Write the file atomically, profiles in their current order."""
    lines = list(HEADER) + list(keep)
    lines += [f"{name.replace(';', ',')} ; {format_pids(pids)}" for name, pids in profiles.items()]
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    os.replace(tmp, path)
