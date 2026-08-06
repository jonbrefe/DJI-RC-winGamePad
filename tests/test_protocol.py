"""Offline unit tests for the DUML protocol library (no hardware required)."""
from djirc import protocol as dji


class _Writer:
    """Captures bytes written by send_duml."""

    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        self.data += b


class _FakeSerial:
    """Minimal serial stub: read(n) returns up to n buffered bytes."""

    def __init__(self, data=b""):
        self._buf = bytes(data)
        self._pos = 0

    def read(self, n=1):
        chunk = self._buf[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk


def test_crc_tables_have_expected_shape():
    assert len(dji._CRC16) == 256
    assert len(dji._CRC8) == 256


def test_checksums_are_deterministic():
    header = bytearray.fromhex("55 0e 04")
    assert dji.calc_pkt55_hdr_checksum(0x77, header, 3) == dji.calc_pkt55_hdr_checksum(0x77, header, 3)
    body = bytearray(range(20))
    assert dji.calc_checksum(body, len(body)) == dji.calc_checksum(body, len(body))


def test_send_duml_roundtrips_through_read_packet():
    w = _Writer()
    dji.send_duml(w, 0x0A, 0x06, 0x40, 0x06, dji.STICK_CMD_ID, bytearray())
    pkt = dji.read_packet(_FakeSerial(w.data))
    assert pkt == w.data          # framing + header CRC-8 + body CRC-16 all valid
    assert pkt[0] == 0x55
    assert pkt[10] == dji.STICK_CMD_ID


def test_read_packet_rejects_corrupted_crc():
    w = _Writer()
    dji.send_duml(w, 0x0A, 0x06, 0x40, 0x06, dji.STICK_CMD_ID, bytearray())
    corrupted = bytearray(w.data)
    corrupted[-1] ^= 0xFF          # break the CRC-16
    assert dji.read_packet(_FakeSerial(corrupted)) is None


def test_read_packet_rejects_wrong_start_byte():
    assert dji.read_packet(_FakeSerial(b"\x00\x00\x00")) is None


def test_parse_input_center_is_zero_and_clamps_high():
    assert dji.parse_input((1024).to_bytes(2, "little")) == 0
    assert dji.parse_input((65535).to_bytes(2, "little")) == 32767
    assert dji.parse_input((0).to_bytes(2, "little")) < 0


def test_parse_sticks_neutral():
    pkt = bytearray(dji.STICK_LEN)
    for off in dji.AXES.values():
        pkt[off:off + 2] = (1024).to_bytes(2, "little")
    sticks = dji.parse_sticks(pkt)
    assert set(sticks) == set(dji.AXES)
    assert all(v == 0 for v in sticks.values())


def test_parse_buttons_bitfield():
    aux = bytearray(dji.AUX_LEN)
    aux[29] = dji.BUTTON_BITS["fn"] | dji.BUTTON_BITS["rth"]
    b = dji.parse_buttons(aux)
    assert b["fn"] and b["rth"]
    assert not b["photo_video"] and not b["record"]


def test_parse_mode():
    aux = bytearray(dji.AUX_LEN)
    aux[dji.FLIGHT_MODE_OFFSET] = 0x10
    assert dji.parse_mode(aux) == "normal"


def test_parse_battery_reads_and_clamps():
    pkt = bytearray(dji.BATTERY_OFFSET + 1)
    pkt[dji.BATTERY_OFFSET] = 0x64
    assert dji.parse_battery(pkt) == 100
    pkt[dji.BATTERY_OFFSET] = 200
    assert dji.parse_battery(pkt) == 100
