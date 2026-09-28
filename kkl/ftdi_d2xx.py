"""Minimal ctypes wrapper for the FTDI D2XX driver (ftd2xx.dll).

Only what K-line work needs: UART setup, break, modem lines, queue/read/write,
line status, async bit-bang and read-only EEPROM access.
"""

import ctypes as C
from ctypes import wintypes as W

_STATUS = ("OK", "INVALID_HANDLE", "DEVICE_NOT_FOUND", "DEVICE_NOT_OPENED", "IO_ERROR",
           "INSUFFICIENT_RESOURCES", "INVALID_PARAMETER", "INVALID_BAUD_RATE",
           "DEVICE_NOT_OPENED_FOR_ERASE", "DEVICE_NOT_OPENED_FOR_WRITE",
           "FAILED_TO_WRITE_DEVICE", "EEPROM_READ_FAILED", "EEPROM_WRITE_FAILED",
           "EEPROM_ERASE_FAILED", "EEPROM_NOT_PRESENT", "EEPROM_NOT_PROGRAMMED",
           "INVALID_ARGS", "NOT_SUPPORTED", "OTHER_ERROR")

DEVICE_TYPES = {0: "BM (FT232BM/BL)", 1: "AM", 2: "100AX", 3: "UNKNOWN", 4: "2232C",
                5: "232R", 6: "2232H", 7: "4232H", 8: "232H", 9: "X-series"}

_H = C.c_void_p
_DW = W.DWORD
_P = C.POINTER
_VP = C.c_void_p

_PROTOS = {
    "FT_CreateDeviceInfoList": [_P(_DW)],
    "FT_GetDeviceInfoDetail": [_DW, _P(_DW), _P(_DW), _P(_DW), _P(_DW), _VP, _VP, _P(_H)],
    "FT_Open": [C.c_int, _P(_H)],
    "FT_OpenEx": [_VP, _DW, _P(_H)],
    "FT_Close": [_H],
    "FT_SetBaudRate": [_H, C.c_ulong],
    "FT_SetDataCharacteristics": [_H, C.c_ubyte, C.c_ubyte, C.c_ubyte],
    "FT_SetFlowControl": [_H, C.c_ushort, C.c_ubyte, C.c_ubyte],
    "FT_SetTimeouts": [_H, C.c_ulong, C.c_ulong],
    "FT_SetLatencyTimer": [_H, C.c_ubyte],
    "FT_GetLatencyTimer": [_H, _P(C.c_ubyte)],
    "FT_Purge": [_H, C.c_ulong],
    "FT_GetQueueStatus": [_H, _P(_DW)],
    "FT_Read": [_H, _VP, _DW, _P(_DW)],
    "FT_Write": [_H, _VP, _DW, _P(_DW)],
    "FT_SetBreakOn": [_H],
    "FT_SetBreakOff": [_H],
    "FT_SetDtr": [_H],
    "FT_ClrDtr": [_H],
    "FT_SetRts": [_H],
    "FT_ClrRts": [_H],
    "FT_GetModemStatus": [_H, _P(C.c_ulong)],
    "FT_SetBitMode": [_H, C.c_ubyte, C.c_ubyte],
    "FT_GetBitMode": [_H, _P(C.c_ubyte)],
    "FT_GetDeviceInfo": [_H, _P(_DW), _P(_DW), _VP, _VP, _VP],
    "FT_GetDriverVersion": [_H, _P(_DW)],
    "FT_GetLibraryVersion": [_P(_DW)],
    "FT_ReadEE": [_H, _DW, _P(W.WORD)],
}


class D2XXError(RuntimeError):
    pass


def _dll():
    dll = C.WinDLL("ftd2xx.dll")
    for name, args in _PROTOS.items():
        fn = getattr(dll, name)
        fn.argtypes = args
        fn.restype = C.c_ulong
    return dll


def _check(name, status):
    if status != 0:
        msg = _STATUS[status] if status < len(_STATUS) else str(status)
        raise D2XXError(f"{name} failed: FT_{msg}")


def _ver(v):
    return f"{(v >> 16) & 0xFF:x}.{(v >> 8) & 0xFF:02x}.{v & 0xFF:02x}"


def _vp(buf):
    return C.cast(buf, C.c_void_p)


def list_devices():
    dll = _dll()
    n = _DW()
    _check("FT_CreateDeviceInfoList", dll.FT_CreateDeviceInfoList(C.byref(n)))
    out = []
    for i in range(n.value):
        flags, typ, dev_id, loc = _DW(), _DW(), _DW(), _DW()
        serial, desc, h = C.create_string_buffer(64), C.create_string_buffer(128), _H()
        st = dll.FT_GetDeviceInfoDetail(i, C.byref(flags), C.byref(typ), C.byref(dev_id),
                                        C.byref(loc), _vp(serial), _vp(desc), C.byref(h))
        if st:
            continue
        out.append({"index": i, "opened_elsewhere": bool(flags.value & 1),
                    "type": DEVICE_TYPES.get(typ.value, str(typ.value)),
                    "vid_pid": f"{dev_id.value >> 16:04X}:{dev_id.value & 0xFFFF:04X}",
                    "serial": serial.value.decode(errors="replace"),
                    "desc": desc.value.decode(errors="replace"), "loc": loc.value})
    return out


def decode_eeprom(words):
    """Decode the interesting parts of a BM/232R-style 93C46 image (64 words)."""
    if not words or all(w == 0xFFFF for w in words):
        return {"state": "blank or absent"}
    raw = b"".join(w.to_bytes(2, "little") for w in words)
    info = {"vid": f"{words[1]:04X}", "pid": f"{words[2]:04X}", "release": f"{words[3]:04X}",
            "max_power_mA": (words[4] >> 8) * 2}

    def string_at(ptr_word):
        off, ln = (ptr_word & 0xFF) & 0x7F, ptr_word >> 8
        if ln < 2 or off + ln > len(raw):
            return None
        return raw[off + 2:off + ln].decode("utf-16-le", errors="replace")

    for i, key in ((7, "manufacturer"), (8, "product"), (9, "serial")):
        info[key] = string_at(words[i])
    return info


class D2XXDevice:
    backend = "d2xx"

    def __init__(self, index=0, serial=None):
        self.dll = _dll()
        self.h = _H()
        if serial:
            s = C.create_string_buffer(serial.encode())
            _check("FT_OpenEx", self.dll.FT_OpenEx(_vp(s), 1, C.byref(self.h)))
        else:
            _check("FT_Open", self.dll.FT_Open(index, C.byref(self.h)))
        self.dll.FT_SetBitMode(self.h, 0, 0)  # plain UART mode, in case a crash left bit-bang on

    def _call(self, name, *args):
        _check(name, getattr(self.dll, name)(self.h, *args))

    def configure(self, latency=1):
        self._call("FT_SetDataCharacteristics", 8, 0, 0)   # 8N1
        self._call("FT_SetFlowControl", 0, 0x11, 0x13)     # no flow control
        self._call("FT_SetTimeouts", 50, 1000)
        self._call("FT_SetLatencyTimer", latency)

    def set_baud(self, baud):
        self._call("FT_SetBaudRate", int(baud))

    def purge(self):
        self._call("FT_Purge", 3)

    def purge_rx(self):
        self._call("FT_Purge", 1)

    def in_waiting(self):
        n = _DW()
        self._call("FT_GetQueueStatus", C.byref(n))
        return n.value

    def read(self, n):
        buf, got = C.create_string_buffer(n), _DW()
        self._call("FT_Read", _vp(buf), n, C.byref(got))
        return buf.raw[:got.value]

    def write(self, data):
        data = bytes(data)
        buf, done = C.create_string_buffer(data, len(data)), _DW()
        self._call("FT_Write", _vp(buf), len(data), C.byref(done))
        if done.value != len(data):
            raise D2XXError(f"FT_Write wrote {done.value}/{len(data)} bytes")

    def break_on(self):
        self._call("FT_SetBreakOn")

    def break_off(self):
        self._call("FT_SetBreakOff")

    def set_dtr(self, on):
        self._call("FT_SetDtr" if on else "FT_ClrDtr")

    def set_rts(self, on):
        self._call("FT_SetRts" if on else "FT_ClrRts")

    def modem_status(self):
        v = C.c_ulong()
        self._call("FT_GetModemStatus", C.byref(v))
        return v.value

    def line_status(self):
        """OE=0x02 PE=0x04 FE=0x08 BI=0x10 of the most recent status packet."""
        return (self.modem_status() >> 8) & 0xFF

    def bitbang(self, on, mask=0x01):
        """Async bit-bang with only D0 (TXD) as output; D1 (RXD) stays an input."""
        self._call("FT_SetBitMode", mask if on else 0, 0x01 if on else 0x00)

    def bitbang_write(self, level):
        self.write(b"\x01" if level else b"\x00")

    def pins(self):
        v = C.c_ubyte()
        self._call("FT_GetBitMode", C.byref(v))
        return v.value

    def read_eeprom(self, words=64):
        out = []
        for i in range(words):
            w = W.WORD()
            st = self.dll.FT_ReadEE(self.h, i, C.byref(w))
            if st:
                return {"error": f"FT_{_STATUS[st] if st < len(_STATUS) else st}", "words": out}
            out.append(w.value)
        return {"words": out, "decoded": decode_eeprom(out)}

    def info(self):
        typ, dev_id = _DW(), _DW()
        serial, desc = C.create_string_buffer(64), C.create_string_buffer(128)
        self._call("FT_GetDeviceInfo", C.byref(typ), C.byref(dev_id), _vp(serial), _vp(desc), None)
        drv, lib, lat = _DW(), _DW(), C.c_ubyte()
        self._call("FT_GetDriverVersion", C.byref(drv))
        _check("FT_GetLibraryVersion", self.dll.FT_GetLibraryVersion(C.byref(lib)))
        self._call("FT_GetLatencyTimer", C.byref(lat))
        ms = self.modem_status()
        return {"backend": "d2xx", "type": DEVICE_TYPES.get(typ.value, str(typ.value)),
                "vid_pid": f"{dev_id.value >> 16:04X}:{dev_id.value & 0xFFFF:04X}",
                "serial": serial.value.decode(errors="replace"),
                "desc": desc.value.decode(errors="replace"),
                "driver": _ver(drv.value), "library": _ver(lib.value),
                "latency_ms": lat.value, "modem_status": f"{ms & 0xFF:02X}",
                "line_status": f"{(ms >> 8) & 0xFF:02X}"}

    def close(self):
        if self.h:
            try:
                self.dll.FT_SetBreakOff(self.h)
                self.dll.FT_SetBitMode(self.h, 0, 0)
            finally:
                self.dll.FT_Close(self.h)
                self.h = _H()
