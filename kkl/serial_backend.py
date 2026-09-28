"""pyserial backend: any USB-serial chip through its COM port (CH340, PL2303, CP210x,
FTDI VCP...). Same interface as D2XXDevice, minus line status and bit-bang. On FTDI
the latency timer must be set in Device Manager."""

import serial


class SerialDevice:
    backend = "serial"

    def __init__(self, port):
        self.port = port
        self.s = serial.Serial(port, 10400, bytesize=8, parity="N", stopbits=1,
                               timeout=0, write_timeout=2)

    def configure(self, latency=1):
        pass

    def set_baud(self, baud):
        self.s.baudrate = int(baud)

    def purge(self):
        self.s.reset_input_buffer()
        self.s.reset_output_buffer()

    def purge_rx(self):
        self.s.reset_input_buffer()

    def in_waiting(self):
        return self.s.in_waiting

    def read(self, n):
        return self.s.read(n)

    def write(self, data):
        self.s.write(bytes(data))

    def break_on(self):
        self.s.break_condition = True

    def break_off(self):
        self.s.break_condition = False

    def set_dtr(self, on):
        self.s.dtr = on

    def set_rts(self, on):
        self.s.rts = on

    def line_status(self):
        return None

    def bitbang(self, on, mask=0x01):
        raise NotImplementedError("bit-bang needs the d2xx backend")

    bitbang_write = pins = bitbang

    def info(self):
        return {"backend": "serial", "port": self.port}

    def close(self):
        try:
            self.s.break_condition = False
        finally:
            self.s.close()
