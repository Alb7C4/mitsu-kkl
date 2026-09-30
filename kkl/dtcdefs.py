"""Fault code (DTC) definitions: which bit of the MUT fault bytes is which Mitsubishi code,
and what the code means. Kept in an editable ';'-separated file:

    bit ; code ; description

Bits 0-7 are the first fault byte (PID 40 active / 45 stored), bits 8-15 the second one
(41 / 46). A line with an empty bit only describes a code. The defaults are built in, so the
dtc/dtc2 conversions work even without the file.
"""

from pathlib import Path

from . import proto

HEADER = (
    "# Mitsubishi fault code (DTC) definitions for the engine ECU. Separator: semicolon. "
    "Lines starting with # are comments.",
    "# bit ; code ; description",
    "# bit 0-7 = first fault byte (PID 40 active, 45 stored), bit 8-15 = second byte (PID 41 active, "
    "46 stored); an empty bit only describes a code",
    "# Confirmed on this car (ECU ID E4 3A): bit 2 = 13, bit 3 = 14, bit 5 = 21, bit 9 = 25. The other "
    "bits follow the usual Mitsubishi order and are unverified.",
    "# Bit 12 comes on about 20 s after a cold start on this car: count the check-engine blinks to "
    "confirm its code number.",
)

DESCRIPTIONS = {
    11: "oxygen sensor", 12: "air flow sensor", 13: "intake air temperature sensor",
    14: "throttle position sensor", 15: "idle speed control motor position", 21: "engine coolant temperature sensor",
    22: "crank angle sensor", 23: "top dead centre sensor", 24: "vehicle speed sensor",
    25: "barometric pressure sensor", 31: "knock sensor", 32: "manifold pressure sensor",
    36: "ignition timing adjustment signal", 39: "second oxygen sensor", 41: "injector", 42: "fuel pump",
}

_bits = dict(enumerate(proto.DTC_CODES))  # bit -> code
_names = dict(DESCRIPTIONS)               # code -> description


def label(code):
    name = _names.get(code)
    return f"{code} {name}" if name else str(code)


def table():
    """[(bit, code, description), ...] for the bits defined in the loaded file."""
    return [(bit, code, _names.get(code, "")) for bit, code in sorted(_bits.items())]


def decode(value, base=0):
    """Fault byte -> ['13 intake air temperature sensor', ...]; base 0 = first byte, 8 = second."""
    out = []
    for i in range(8):
        if value >> i & 1:
            code = _bits.get(base + i)
            out.append(label(code) if code is not None else f"bit {base + i} (no code defined)")
    return out


def _write_defaults(path):
    lines = list(HEADER) + [f"{bit} ; {code} ; {DESCRIPTIONS.get(code, '')}" for bit, code in enumerate(proto.DTC_CODES)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def load(path):
    """Read the definitions file (created with the defaults when missing). Returns problems."""
    global _bits, _names
    path = Path(path)
    if not path.exists():
        _write_defaults(path)
    bits, names, problems = {}, {}, []
    for n, raw in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        f = [x.strip() for x in line.split(";")] + ["", ""]
        try:
            code = int(f[1])
            bit = int(f[0]) if f[0] else None
            if bit is not None and not 0 <= bit <= 15:
                raise ValueError
        except ValueError:
            problems.append(f"line {n}: expected 'bit ; code ; description', bit 0-15 or empty")
            continue
        if bit is not None:
            bits[bit] = code
        if f[2]:
            names[code] = f[2]
    _bits, _names = bits, names
    return problems
