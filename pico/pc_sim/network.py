"""Stand-in for MicroPython's `network` module (Pico W access point) on a PC."""

AP_IF, STA_IF = 1, 0


def country(code):
    pass


class WLAN:
    def __init__(self, interface):
        self.cfg = {}

    def config(self, **kwargs):
        self.cfg.update(kwargs)

    def active(self, on=None):
        return True

    def ifconfig(self):
        return ("127.0.0.1", "255.255.255.0", "127.0.0.1", "127.0.0.1")
