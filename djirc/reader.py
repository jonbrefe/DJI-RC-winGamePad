"""Background reader thread for the DJI RC-N1/N3 controller.

`Reader` opens the "For Protocol" serial port, enables reporting, and continuously
polls sticks (0x01), buttons/mode (0x27), and battery (0x1E), auto-reconnecting on
failure. It exposes the latest decoded state for a GUI or other consumer:
  latest (bytes|None), aux (bytes|None), battery (int|None), count (int),
  status (str), connected (bool); call stop() to end the loop.
"""
import threading

import serial

from . import protocol as dji

PACKET_LEN = 38         # 0x01 stick packet length
AUX_CMD_ID = 0x27       # button/dial/mode packet
BATTERY_CMD_ID = 0x1E   # status push; battery % at offset 15
BATTERY_OFFSET = 15


class Reader(threading.Thread):
    """Background thread that polls the controller and auto-reconnects.

    Exposes the latest decoded state (sticks, buttons/mode, battery) plus a
    connection flag and a human-readable status for the GUI to display.
    """

    def __init__(self, preferred_port):
        """Set up thread state; the serial port is opened later in run()."""
        super().__init__(daemon=True)
        self._preferred = preferred_port
        self._stop = threading.Event()
        self.latest = None            # most recent 0x01 stick packet (bytes)
        self.aux = None               # most recent 0x27 button/aux packet (bytes)
        self.battery = None           # RC battery percentage
        self.count = 0
        self.status = "Connecting..."
        self.connected = False

    def stop(self):
        """Signal the polling loop to exit."""
        self._stop.set()

    def run(self):
        """Open the port, poll sticks/aux/battery, and reconnect on failure."""
        while not self._stop.is_set():
            try:
                s = dji.open_port(self._preferred)
            except (OSError, serial.SerialException):
                s = None
            if s is None:
                self.connected = False
                self.status = "Waiting for controller\u2026"
                self._stop.wait(1.0)
                continue

            self.connected = True
            self.status = f"Connected: {s.name}"
            try:
                dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x24, bytearray.fromhex('01'))
                while not self._stop.is_set():
                    dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x01, bytearray.fromhex(''))
                    dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, AUX_CMD_ID, bytearray.fromhex(''))
                    dji.send_duml(s, 0x0A, 0x06, 0x40, 0x06, BATTERY_CMD_ID, bytearray.fromhex(''))
                    for _ in range(12):
                        pkt = dji.read_packet(s)
                        if pkt is None:
                            break
                        if len(pkt) < 13:
                            continue
                        if pkt[10] == 0x01 and len(pkt) == PACKET_LEN:
                            self.latest = bytes(pkt)
                            self.count += 1
                        elif pkt[10] == AUX_CMD_ID:
                            self.aux = bytes(pkt)
                        elif pkt[10] == BATTERY_CMD_ID and len(pkt) > BATTERY_OFFSET:
                            self.battery = min(100, pkt[BATTERY_OFFSET])
            except (serial.SerialException, OSError):
                self.status = "Disconnected \u2014 reconnect the controller"
            finally:
                self.connected = False
                self.latest = self.aux = self.battery = None
                try:
                    s.close()
                except (OSError, serial.SerialException):
                    pass
            self._stop.wait(0.8)   # brief pause before trying to reconnect
