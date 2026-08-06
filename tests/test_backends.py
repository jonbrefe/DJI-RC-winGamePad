"""Offline unit tests for the input backends and gamepad loop (no hardware/vgamepad)."""
import time
from threading import Event, Thread

import main


class _FakePad:
    is_gamepad = True

    def __init__(self):
        self.axes = None
        self.dial = None
        self.buttons = {}
        self.mode = None
        self.updates = 0
        self.reset_called = False

    def set_axes(self, lx, ly, rx, ry):
        self.axes = (lx, ly, rx, ry)

    def set_dial(self, v):
        self.dial = v

    def set_button(self, name, pressed):
        self.buttons[name] = pressed

    def set_mode(self, mode):
        self.mode = mode

    def update(self):
        self.updates += 1

    def reset(self):
        self.reset_called = True


class _FakeController:
    sticks = {"left_x": -32768, "left_y": 32767, "right_x": 100, "right_y": -100, "left_dial": -16000}
    buttons = {"fn": True, "photo_video": False, "record": False, "rth": True}
    mode = "sport"


def test_gamepad_loop_maps_state_and_resets_on_stop():
    pad = _FakePad()
    stop = Event()
    t = Thread(target=main.gamepad_loop, args=(pad, _FakeController(), stop), daemon=True)
    t.start()
    time.sleep(0.05)
    stop.set()
    t.join(timeout=1)

    assert pad.axes == (-32768, 32767, 100, -100)
    assert pad.dial == -16000
    assert pad.buttons == {"fn": True, "photo_video": False, "record": False, "rth": True}
    assert pad.mode == "sport"
    assert pad.updates > 0
    assert pad.reset_called


class _StubPad:
    def __init__(self):
        self.lt = None
        self.rt = None

    def right_trigger(self, value):
        self.rt = value

    def left_trigger(self, value):
        self.lt = value


def test_set_dial_maps_bidirectional_to_triggers():
    vb = main.VGamepadBackend.__new__(main.VGamepadBackend)  # skip vgamepad import
    vb.pad = _StubPad()

    vb.set_dial(32767)
    assert (vb.pad.rt, vb.pad.lt) == (255, 0)
    vb.set_dial(-32767)
    assert (vb.pad.rt, vb.pad.lt) == (0, 255)
    vb.set_dial(0)
    assert (vb.pad.rt, vb.pad.lt) == (0, 0)


def test_backend_registry_and_gamepad_flag():
    assert set(main.BACKENDS) == {"directinput", "pynput", "vgamepad"}
    assert getattr(main.VGamepadBackend, "is_gamepad", False) is True


def test_vigembus_installer_is_safe_without_vgamepad():
    result = main._vigembus_installer()
    assert result is None or result.endswith(".msi")
