"""Find and open K-line interfaces: FTDI chips through D2XX, any USB-serial chip
(CH340, PL2303, CP210x, FTDI...) through its COM port, or the simulator.

Interface keys, as stored in the GUI settings:

    auto | d2xx:#0 | d2xx:<FTDI serial number> | serial:COM5 | sim:<model>

A chip used through its COM port must itself be able to run 15625 baud and send a break.
"""

from dataclasses import dataclass

AUTO = "auto"

# USB vendor IDs of the chips found in KKL cables; "auto" tries the ports in this order.
CHIPS = {0x0403: "FTDI", 0x1A86: "CH340", 0x067B: "PL2303", 0x10C4: "CP210x"}


@dataclass
class Iface:
    key: str
    label: str


def _d2xx_devices():
    try:
        from .ftdi_d2xx import list_devices
        return list_devices()
    except Exception:  # no ftd2xx.dll / FTDI driver: nothing to offer through D2XX
        return []


def _com_ports():
    """COM ports, known KKL chips first; Bluetooth ports are skipped (no K-line behind them)."""
    from serial.tools import list_ports
    ports = [p for p in list_ports.comports() if "BTHENUM" not in (p.hwid or "").upper()]
    known = list(CHIPS)

    def order(p):
        group = known.index(p.vid) if p.vid in known else len(known) + (0 if p.vid else 1)
        num = p.device[3:]
        return group, int(num) if num.isdigit() else 999

    return sorted(ports, key=order)


def _port_label(p):
    chip = CHIPS.get(p.vid)
    if chip:
        return f"{p.device} – {chip}" + (" via COM port" if chip == "FTDI" else "")
    if p.vid:
        return f"{p.device} – USB {p.vid:04X}:{p.pid:04X} {p.description}"
    return f"{p.device} – {p.description}"


def list_interfaces():
    out = [Iface(AUTO, "Automatic: FTDI, CH340, PL2303 or CP210x cable")]
    devs = _d2xx_devices()
    for d in devs:
        ident = d["serial"] or f"#{d['index']}"
        suffix = f" ({ident})" if d["serial"] or len(devs) > 1 else ""
        out.append(Iface(f"d2xx:{ident}", f"FTDI via D2XX – {d['desc']}{suffix}"))
    out += [Iface(f"serial:{p.device}", _port_label(p)) for p in _com_ports()]
    return out


def cli_key(backend=None, dev=None, serial=None, port=None, sim="mut"):
    """--backend/--dev/--serial/--port/--sim command-line options -> interface key.
    Without --backend, --port implies serial and --serial/--dev imply d2xx; with none
    of them the result is None (the caller's default applies)."""
    if backend is None:
        backend = "serial" if port else "d2xx" if serial or dev is not None else None
        if backend is None:
            return None
    return {"auto": AUTO, "d2xx": f"d2xx:{serial or f'#{dev or 0}'}",
            "serial": f"serial:{port or 'COM1'}", "sim": f"sim:{sim}"}[backend]


def open_interface(key):
    """Open the interface behind `key`; the device gets a `label` for status messages."""
    kind, _, arg = key.partition(":")
    if kind == AUTO:
        return _open_auto()
    if kind == "d2xx":
        from .ftdi_d2xx import D2XXDevice
        dev = D2XXDevice(index=int(arg[1:])) if arg.startswith("#") else D2XXDevice(serial=arg)
        dev.label = "FTDI (D2XX)"
    elif kind == "serial":
        from .serial_backend import SerialDevice
        dev = SerialDevice(arg)
        dev.label = next((_port_label(p) for p in _com_ports() if p.device == arg), arg)
    elif kind == "sim":
        from .sim import SimDevice
        dev = SimDevice(arg or "mut")
        dev.label = f"simulator ({arg or 'mut'})"
    else:
        raise ValueError(f"unknown interface '{key}'")
    return dev


def _open_auto():
    errors = []
    if _d2xx_devices():
        try:
            return open_interface("d2xx:#0")
        except Exception as e:
            errors.append(f"FTDI: {e}")
    for p in _com_ports():
        if p.vid not in CHIPS:
            continue  # other USB devices (Arduino, modems...) and RS-232: only when chosen explicitly
        try:
            return open_interface(f"serial:{p.device}")
        except Exception as e:
            errors.append(f"{p.device}: {e}")
    raise RuntimeError("no FTDI, CH340, PL2303 or CP210x cable found"
                       + (f" ({'; '.join(errors)})" if errors else ""))
