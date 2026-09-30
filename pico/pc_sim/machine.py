"""Stand-in for MicroPython's `machine` module, so the Pico firmware runs unchanged on a PC:
the UART and the TX pin drive kkl.sim.SimDevice (a simulated K-line with an ECU).
run.py sets SIM and TX_GPIO before the firmware is imported."""

SIM = None       # kkl.sim.SimDevice shared by the UART and the TX pin
TX_GPIO = 0
pins = {}        # gpio -> last value, for tests (e.g. pin 1 grounding)


class Pin:
    OUT, IN = 1, 0

    def __init__(self, gpio, mode=None, value=None):
        self.gpio = gpio
        if value is not None:
            self.value(value)

    def value(self, v=None):
        if v is None:
            return pins.get(self.gpio, 0)
        pins[self.gpio] = v
        if self.gpio == TX_GPIO and SIM is not None:
            (SIM.break_off if v else SIM.break_on)()  # TX low = K-line pulled low

    def on(self):
        self.value(1)

    def off(self):
        self.value(0)


class UART:
    INV_TX, INV_RX = 1, 2

    def __init__(self, uart_id, baudrate=9600, **kwargs):
        SIM.set_baud(baudrate)
        SIM.break_off()  # the pin is back on the UART, idle high

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
