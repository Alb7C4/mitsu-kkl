"""PID definitions for the live viewer, kept in a ';'-separated text file:

    pid ; name ; conversion ; unit ; on list (1/0)

The conversion is an arithmetic expression in x (the raw byte 0-255), e.g. x*0.0733,
x*31.25, x-40, (x>>4)&15, round(x*0.49, 1), or a keyword: dtc / dtc2 (Mitsubishi fault
code bits) or bin (8-bit binary). Expressions go through a small AST walker, never eval().
"""

import ast
import operator
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import dtcdefs, proto

HEADER = (
    "# MUT-II PID definitions (engine ECU). Separator: semicolon. Lines starting with # are comments.",
    "# pid ; name ; conversion ; unit ; on list (1/0)",
    "# conversion: expression in x (raw byte 0-255), e.g. x*0.0733 | x*31.25 | x-40 | (x>>4)&15 | round(x*0.49, 1)",
    "#   or a keyword: dtc / dtc2 (fault code bits), bin (binary); empty = no conversion",
)
# What the Polish version wrote: its header is dropped on load, its default names are renamed.
LEGACY_HEADER = (
    "# Definicje PID MUT-II (ECU silnika). Separator: średnik. Linie zaczynające się od # to komentarze.",
    "# pid ; nazwa ; przelicznik ; jednostka ; na liście (1/0)",
    "# przelicznik: wyrażenie z x (surowy bajt 0-255), np. x*0.0733 | x*31.25 | x-40 | (x>>4)&15 | round(x*0.49, 1)",
    "#   albo słowo: dtc / dtc2 (bity kodów usterek), bin (zapis dwójkowy); puste = bez przeliczenia",
)
LEGACY_NAMES = {0x07: "temp. cieczy (surowa)", 0x14: "napięcie akumulatora", 0x15: "ciśnienie baro",
                0x17: "przepustnica TPS", 0x21: "obroty", 0x3A: "temp. powietrza IAT (surowa)",
                0x40: "kody usterek aktywne (1)", 0x41: "kody usterek aktywne (2)",
                0x45: "kody usterek zapamiętane (1)", 0x46: "kody usterek zapamiętane (2)"}
LEGACY_UNITS = {"obr/min": "rpm"}


@dataclass
class PidDef:
    pid: int
    name: str = ""
    conv: str = ""
    unit: str = ""
    active: bool = False


DEFAULTS = (
    PidDef(0x07, "coolant temp (raw)"),
    PidDef(0x14, "battery voltage", "x*0.0733", "V"),
    PidDef(0x15, "barometric pressure", "x*0.49", "kPa"),
    PidDef(0x17, "throttle position TPS", "x*100/255", "%"),
    PidDef(0x21, "engine speed", "x*31.25", "rpm"),
    PidDef(0x3A, "intake air temp IAT (raw)"),
    PidDef(0x40, "active fault codes (1)", "dtc"),
    PidDef(0x41, "active fault codes (2)", "dtc2"),
    PidDef(0x45, "stored fault codes (1)", "dtc"),
    PidDef(0x46, "stored fault codes (2)", "dtc2"),
    PidDef(0xFE, "ECU ID (hi)"),
    PidDef(0xFF, "ECU ID (lo)"),
)


# -- PID lists ---------------------------------------------------------------------
def parse_pids(text):
    """'07,14,20-2F' -> ([0x07, 0x14, 0x20 ... 0x2F], rejected)."""
    pids, rejected = [], []
    for part in text.replace(" ", ",").replace(";", ",").split(","):
        if not part:
            continue
        try:
            a, _, b = part.partition("-")
            rng = range(int(a, 16), int(b or a, 16) + 1)
        except ValueError:
            rejected.append(part)
            continue
        for p in rng:
            if p not in proto.MUT_ALLOWED:
                rejected.append(f"{p:02X}")
            elif p not in pids:
                pids.append(p)
    return pids, rejected


def format_pids(pids):
    """[0x07, 0x20, 0x21, 0x22, 0x23] -> '07,20-23' (keeps the given order)."""
    out, i = [], 0
    while i < len(pids):
        j = i
        while j + 1 < len(pids) and pids[j + 1] == pids[j] + 1:
            j += 1
        out.append(f"{pids[i]:02X}-{pids[j]:02X}" if j - i >= 2 else ",".join(f"{p:02X}" for p in pids[i:j + 1]))
        i = j + 1
    return ",".join(out)


# -- conversions --------------------------------------------------------------------
_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.BitAnd: operator.and_,
           ast.BitOr: operator.or_, ast.BitXor: operator.xor, ast.RShift: operator.rshift}
_UNOPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"abs": abs, "min": min, "max": max, "round": round}
CONV_ERROR = "error"  # what a conversion shows when it fails for a particular value
_ALLOWED = "allowed: numbers, x, + - * / // % & | ^ >>, parentheses, abs/min/max/round"


def _eval(node, x):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id == "x":
        return x
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left, x), _eval(node.right, x))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return _UNOPS[type(node.op)](_eval(node.operand, x))
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS
            and not node.keywords):
        return _FUNCS[node.func.id](*(_eval(a, x) for a in node.args))
    raise ValueError(_ALLOWED)


def _compile_expr(text):
    try:
        body = ast.parse(text, mode="eval").body
    except SyntaxError as e:
        raise ValueError(f"syntax error ({e.msg})") from None
    try:
        _eval(body, 1)
    except ZeroDivisionError:
        pass  # only this particular x; fine for others
    except (TypeError, OverflowError) as e:
        raise ValueError(str(e)) from None
    return body


def _fmt_num(r):
    if isinstance(r, float):
        return f"{r:.2f}".rstrip("0").rstrip(".")
    return str(r)


def compile_conversion(text):
    """Return f(raw) -> str, or None for an empty conversion. Raises ValueError if invalid."""
    text = text.strip()
    if not text:
        return None
    key = text.lower()
    if key in ("dtc", "dtc2"):
        base = 0 if key == "dtc" else 8

        def dtc(v):
            codes = dtcdefs.decode(v, base)  # descriptions from dtc_definitions.csv
            return ", ".join(codes) if codes else "no codes"
        return dtc
    if key == "bin":
        return lambda v: f"{v:08b}"
    try:
        body = _compile_expr(text)
    except ValueError as first:
        # 'x*0,0733' parses as a tuple; retry with decimal commas turned into dots
        alt = re.sub(r"(?<=\d),(?=\d)", ".", text)
        if alt == text:
            raise
        try:
            body = _compile_expr(alt)
        except ValueError:
            raise first from None

    def conv(v):
        try:
            return _fmt_num(_eval(body, v))
        except (ArithmeticError, TypeError, ValueError):
            return CONV_ERROR
    return conv


# -- file ---------------------------------------------------------------------------
def load_defs(path):
    """Read a definition file -> (defs, problems, keep, legacy).

    Also accepts the older one-PID-per-line list ('21  # comment') and textbox-style
    lines ('07,14,20-2F'); those PIDs become active entries without a name.
    `keep` holds the user's own comment lines plus unreadable lines (as comments), so
    save_defs() writes them back instead of silently dropping them.
    `legacy` is True for a file written by the Polish version: its header is dropped and
    its default names/units are renamed, so the caller should save it once."""
    defs, problems, keep, legacy = {}, [], [], False
    text = Path(path).read_text(encoding="utf-8-sig")
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line in HEADER:
            continue
        if line in LEGACY_HEADER:
            legacy = True
            continue
        if line.startswith("#"):
            keep.append(line)
            continue

        def unreadable(why):
            problems.append(f"line {n}: {why}")
            keep.append("# unreadable: " + line)

        if ";" not in line:
            pids, bad = parse_pids(line.split("#", 1)[0])
            for p in pids:
                defs.setdefault(p, PidDef(p)).active = True
            if bad or not pids:
                unreadable(f"cannot parse '{line[:30]}'")
            continue
        f = [x.strip() for x in line.split(";")] + [""] * 4
        try:
            pid = int(f[0], 16)
        except ValueError:
            unreadable(f"bad PID '{f[0]}'")
            continue
        if pid not in proto.MUT_ALLOWED:
            unreadable(f"PID {pid:02X} is blocked (read-only: 00-BF, FD-FF)")
            continue
        defs[pid] = PidDef(pid, f[1], f[2], f[3], f[4].lower() not in ("0", "nie", "n", "no", "false"))
        try:
            compile_conversion(f[2])
        except ValueError as e:
            problems.append(f"PID {pid:02X}: conversion '{f[2]}': {e}")
    english = {d.pid: d.name for d in DEFAULTS}
    for pid, d in defs.items():
        if LEGACY_NAMES.get(pid) == d.name:
            d.name, legacy = english[pid], True
        if d.unit in LEGACY_UNITS:
            d.unit, legacy = LEGACY_UNITS[d.unit], True
    return defs, problems, keep, legacy


def save_defs(path, defs, keep=()):
    """Write the file (atomically). Entries with no name, conversion, unit and not on
    the list are dropped, so scanning 00-BF does not leave 192 empty lines behind."""
    lines = list(HEADER) + list(keep)
    for p in sorted(defs):
        d = defs[p]
        if not (d.name or d.conv or d.unit or d.active):
            continue
        fields = (f"{p:02X}", d.name, d.conv, d.unit, "1" if d.active else "0")
        lines.append(" ; ".join(x.replace(";", ",") for x in fields))
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    os.replace(tmp, path)
