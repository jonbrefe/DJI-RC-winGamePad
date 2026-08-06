"""Reusable DUML protocol library for the DJI RC-N1/N3 remote controller.

This module speaks the DJI "DUML" serial protocol exposed by the controller's
USB "For Protocol" VCOM port. It provides the low-level primitives (checksums,
framing, send/receive, decoding) plus a high-level :class:`Controller`. The CRC
tables are computed at import, not hardcoded.

Transport
---------
- Connect the RC by its bottom USB-C port. Windows enumerates a composite USB
  device; the interface named "... USB VCOM For Protocol" (MI_02) appears as a
  serial COM port (via DJI's VCOM driver, which binds Windows' in-box usbser.sys).
- Open it at 115200 baud, 8N1. `open_port()` auto-detects it by description.
- Other interfaces (bulk "HS/SS-Data Channel", VCOM "For Debug") are NOT used
  here; the SDK/video and some controls travel over the bulk channel instead.

DUML packet framing
-------------------
Every message, both directions, has this structure (byte offsets shown):

    off  field
    0    0x55            magic / start-of-frame
    1    length low      total packet length, low 8 bits
    2    length high     bits 0-1 = length high, bit 2 set = version marker (|0x04)
    3    header CRC-8    checksum over bytes 0..2, seed 0x77 (calc_pkt55_hdr_checksum)
    4    source          device address of the sender (0x0A = PC/app)
    5    target          device address of the receiver (0x06 = remote controller)
    6-7  sequence        little-endian, incremented per sent packet
    8    cmd type        attribute/flags (0x40 = request in this project)
    9    cmd set         command group (0x06 = remote-controller set)
    10   cmd id          command within the set
    11.. payload         command-specific bytes
    N-2  CRC-16 low      whole-packet checksum over bytes 0..N-3,
    N-1  CRC-16 high     seed 0x3692 (calc_checksum), little-endian

`read_packet()` validates both checksums and the declared length, returning the
full packet bytes or None on any framing/timeout/CRC error. Packets are routed
by cmd_id (byte 10); cmd_set stays 0x06 for everything used here.

Session
-------
1. `enable_simulator()` -> cmd_set 0x06, cmd_id 0x24, payload 0x01. Puts the RC
   into the mode that streams stick data.
2. Poll each cycle by sending empty requests and reading the replies:
   - `request_sticks()`  -> cmd_id 0x01  -> 38-byte stick packet
   - `request_aux()`     -> cmd_id 0x27  -> 58-byte button/mode packet
   - `request_battery()` -> cmd_id 0x1E  -> 19-byte status packet
   The RC also pushes some packets (e.g. 0x1E, 0x26) unsolicited.

Decoded data (absolute byte offsets within each packet)
-------------------------------------------------------
Analog axes are 16-bit little-endian, resting at 1024 and ranging ~364..1684.
`parse_input()` maps that to a signed -32768..32767 (center 0). The stick fields
sit on a stride-3 series starting at offset 13.

  Stick packet (cmd_id 0x01, len 38):
    13-14  right stick X   (roll)
    16-17  right stick Y   (pitch)
    19-20  left stick Y    (throttle)
    22-23  left stick X    (yaw)
    25-26  left dial       (gimbal / zoom wheel)

  Button+mode packet (cmd_id 0x27, len 58):
    byte 28  flight-mode switch (enum): 0x00 Sport, 0x10 Normal, 0x20 Cinematic
    byte 29  button bitfield:
               0x02 Fn
               0x04 Photo/Video toggle
               0x60 Shutter/Record
               0x80 Return-to-Home / pause
    (offsets 16/18/20/22/24 in this packet carry slowly-drifting analog
     telemetry, not buttons.)

  Status packet (cmd_id 0x1E, len 19):
    byte 15  RC battery percentage (0-100)

Not available on this port
--------------------------
The physical power button is a hardware power control and is not reported in any
DUML packet here, so it cannot be read or mapped.

Discovery method
----------------
The button/mode/battery offsets above were found empirically with test_control.py:
passive logging (--discover), command sweeps (--sweep), focused polling (--watch),
and a two-phase neutral-vs-held capture (--diff) that survives sampling jitter.
"""
import struct

import serial
import serial.tools.list_ports

# --- Packet layout ---
STICK_CMD_ID = 0x01
AUX_CMD_ID = 0x27          # carries button/dial/mode state
BATTERY_CMD_ID = 0x1E      # status push carrying RC battery percentage
STICK_LEN = 38
AUX_LEN = 58
BATTERY_OFFSET = 15        # battery percentage byte in the 0x1E packet

# Stick/dial axes: name -> 16-bit little-endian offset in the 0x01 packet.
AXES = {
    "right_x": 13,
    "right_y": 16,
    "left_y": 19,
    "left_x": 22,
    "left_dial": 25,
}

# Buttons: bitfield at offset 29 of the 0x27 packet. name -> mask.
BUTTON_BITS = {
    "fn": 0x02,
    "photo_video": 0x04,
    "record": 0x60,
    "rth": 0x80,
}

# Flight-mode switch: enum byte at offset 28 of the 0x27 packet.
FLIGHT_MODE_OFFSET = 28
FLIGHT_MODES = {0x00: "sport", 0x10: "normal", 0x20: "cinematic"}


def _build_crc16_table():
    """Compute the DUML CRC-16 lookup table (reflected polynomial 0x8408)."""
    table = []
    for i in range(256):
        value = i
        for _ in range(8):
            value = (value >> 1) ^ 0x8408 if value & 1 else value >> 1
        table.append(value)
    return table


def _build_crc8_table():
    """Compute the DUML header CRC-8 lookup table (Dallas/Maxim, polynomial 0x8C)."""
    table = []
    for i in range(256):
        value = i
        for _ in range(8):
            value = (value >> 1) ^ 0x8C if value & 1 else value >> 1
        table.append(value)
    return table


_CRC16 = _build_crc16_table()
_CRC8 = _build_crc8_table()

_sequence_number = 0x34EB


def calc_checksum(packet, plength):
    """CRC-16 over the first `plength` bytes (DUML whole-packet checksum)."""
    v = 0x3692  # DJI P3/P4/Mavic seed.
    for i in range(plength):
        v = (v >> 8) ^ _CRC16[(packet[i] ^ v) & 0xFF]
    return v


def calc_pkt55_hdr_checksum(seed, packet, plength):
    """CRC-8 over the first `plength` header bytes (DUML 0x55 header checksum)."""
    chksum = seed
    for i in range(plength):
        chksum = _CRC8[(packet[i] ^ chksum) & 0xFF]
    return chksum


def send_duml(s, source, target, cmd_type, cmd_set, cmd_id, payload=None):
    """Frame and write one DUML command (header, checksums, sequence number, CRC)."""
    global _sequence_number
    packet = bytearray.fromhex('55')
    length = 13 + (len(payload) if payload is not None else 0)
    if length > 0x3FF:
        raise ValueError("DUML packet too large")
    packet += struct.pack('B', length & 0xFF)
    packet += struct.pack('B', (length >> 8) | 0x4)
    packet += struct.pack('B', calc_pkt55_hdr_checksum(0x77, packet, 3))
    packet += struct.pack('B', source)
    packet += struct.pack('B', target)
    packet += struct.pack('<H', _sequence_number)
    packet += struct.pack('B', cmd_type)
    packet += struct.pack('B', cmd_set)
    packet += struct.pack('B', cmd_id)
    if payload is not None:
        packet += payload
    packet += struct.pack('<H', calc_checksum(packet, len(packet)))
    s.write(packet)
    _sequence_number = (_sequence_number + 1) & 0xFFFF


def read_packet(serial_port):
    """Read one framed DUML packet; return the full bytes or None on error/timeout."""
    start = serial_port.read(1)
    if start != b'\x55':
        return None

    length_bytes = serial_port.read(2)
    if len(length_bytes) != 2:
        return None

    packet_length = struct.unpack('<H', length_bytes)[0] & 0x03FF
    if packet_length < 13 or packet_length > 0x03FF:
        return None

    header = start + length_bytes
    header_checksum = serial_port.read(1)
    if len(header_checksum) != 1:
        return None
    if calc_pkt55_hdr_checksum(0x77, header, 3) != header_checksum[0]:
        return None

    payload = serial_port.read(packet_length - 4)
    if len(payload) != packet_length - 4:
        return None

    packet = bytearray(header + header_checksum + payload)
    if calc_checksum(packet, len(packet) - 2) != struct.unpack('<H', packet[-2:])[0]:
        return None
    return packet


def parse_input(input_bytes):
    """Convert a raw 16-bit stick reading (center 1024) to signed -32768..32767."""
    output = (int.from_bytes(input_bytes, byteorder='little') - 1024) * 2 * 4096 // 165
    return 32767 if output >= 32768 else output


def open_port(preferred=None):
    """Open the RC serial port. Returns a Serial or None if not found."""
    if preferred:
        return serial.Serial(port=preferred, baudrate=115200, timeout=0.25)
    for port in serial.tools.list_ports.comports(True):
        if "For Protocol" in port.description:
            return serial.Serial(port=port.name, baudrate=115200, timeout=0.25)
    return None


def enable_simulator(s):
    """Enable RC simulator reporting so stick data is streamed."""
    send_duml(s, 0x0A, 0x06, 0x40, 0x06, 0x24, bytearray.fromhex('01'))


def request_sticks(s):
    """Request the stick/dial packet (0x01)."""
    send_duml(s, 0x0A, 0x06, 0x40, 0x06, STICK_CMD_ID, bytearray())


def request_aux(s):
    """Request the button/mode packet (0x27)."""
    send_duml(s, 0x0A, 0x06, 0x40, 0x06, AUX_CMD_ID, bytearray())


def request_battery(s):
    """Request the battery status packet (0x1E)."""
    send_duml(s, 0x0A, 0x06, 0x40, 0x06, BATTERY_CMD_ID, bytearray())


def parse_sticks(packet):
    """Decode the 0x01 packet into {axis_name: value} for the sticks and left dial."""
    return {name: parse_input(packet[off:off + 2]) for name, off in AXES.items()}


def parse_buttons(aux):
    """Decode the button bitfield (byte 29 of 0x27) into {name: bool}."""
    b = aux[29] if len(aux) > 29 else 0
    return {name: (b & mask) != 0 for name, mask in BUTTON_BITS.items()}


def parse_mode(aux):
    """Return the flight-mode name (sport/normal/cinematic) from the 0x27 packet."""
    if len(aux) > FLIGHT_MODE_OFFSET:
        return FLIGHT_MODES.get(aux[FLIGHT_MODE_OFFSET])
    return None


def parse_battery(pkt):
    """Return the RC battery percentage (0-100) from the 0x1E packet, or None."""
    if len(pkt) > BATTERY_OFFSET:
        return min(100, pkt[BATTERY_OFFSET])
    return None


ZERO_STICKS = {name: 0 for name in AXES}


class Controller:
    """Opens the RC port, enables reporting, and exposes decoded state."""

    def __init__(self, port=None):
        """Open the port (auto-detect if None), enable reporting, or raise if not found."""
        self.serial = open_port(port)
        if self.serial is None:
            raise RuntimeError("DJI RC 'For Protocol' port not found. Controller on and connected?")
        self.name = self.serial.name
        self.sticks = dict(ZERO_STICKS)
        self.buttons = {name: False for name in BUTTON_BITS}
        self.mode = None
        self.battery = None
        self.latest_stick = None
        self.latest_aux = None
        enable_simulator(self.serial)

    def poll(self, with_aux=True):
        """Request and read one round of packets. Returns True if sticks updated."""
        request_sticks(self.serial)
        if with_aux:
            request_aux(self.serial)
            request_battery(self.serial)
        got_sticks = False
        for _ in range(12):
            pkt = read_packet(self.serial)
            if pkt is None:
                break
            if len(pkt) < 13:
                continue
            if pkt[10] == STICK_CMD_ID and len(pkt) == STICK_LEN:
                self.latest_stick = bytes(pkt)
                self.sticks = parse_sticks(pkt)
                got_sticks = True
            elif pkt[10] == AUX_CMD_ID:
                self.latest_aux = bytes(pkt)
                self.buttons = parse_buttons(pkt)
                self.mode = parse_mode(pkt)
            elif pkt[10] == BATTERY_CMD_ID:
                self.battery = parse_battery(pkt)
        return got_sticks

    def reset_sticks(self):
        """Center all stick values (e.g. after a read timeout)."""
        self.sticks = dict(ZERO_STICKS)

    def close(self):
        """Close the serial port, ignoring errors."""
        try:
            self.serial.close()
        except (OSError, serial.SerialException):
            pass
