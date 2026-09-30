"""Stand-in for MicroPython's `machine` module, so the Pico firmware runs unchanged on a PC:
the UART and the TX pin drive kkl.sim.SimDevice (a simulated K-line with an ECU), and the RX
pin read as a GPIO returns the simulated K-line level. run.py sets the module globals before
the firmware is imported, from config.json (TX/RX pins and inversion, like the real board)."""

SIM = None        # kkl.sim.SimDevice shared by the UART and the pins
TX_GPIO, RX_GPIO = 0, 1
TX_INVERT = RX_INVERT = 0   # 1 when the interface inverts (transistor TX stage: GPIO high = K low)
pins = {}         # gpio -> last value written, for tests (e.g. pin 1 grounding)


class Pin:
    OUT, IN = 1, 0

    def __init__(self, gpio, mode=None, value=None):
        self.gpio, self.mode = gpio, mode
        if value is not None:
            self.value(value)

    def value(self, v=None):
        if v is None:
            if self.gpio == RX_GPIO and SIM is not None:
                return SIM.level ^ RX_INVERT  # K-line level as seen through the receiver
            return pins.get(self.gpio, 0)
        pins[self.gpio] = v
        if self.gpio == TX_GPIO and SIM is not None:
            k_high = v ^ TX_INVERT
            (SIM.break_off if k_high else SIM.break_on)()

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)


class UART:
    INV_TX, INV_RX = 1, 2

    def __init__(self, uart_id, baudrate=9600, **kwargs):
        SIM.set_baud(baudrate)
        SIM.break_off()  # the pin is back on the UART, K-line idle high

    def deinit(self):
        pass

    def any(self):
        return SIM.in_waiting()

    def read(self, n=None):
        data = SIM.read(n if n is not None else SIM.in_waiting())
        return data or None

    def write(self, data):
        SIM.write(data)
        return len(data)
