"""Use a DJI RC-N1/N3 remote controller as Windows input.

Reads the controller over its VCOM "For Protocol" port (via djirc.protocol) and
injects input. Pick the backend with --backend:
  vgamepad     virtual Xbox gamepad for drone/FPV sims (default; needs the ViGEmBus driver)
  directinput  keyboard/mouse for games (DirectInput / raw-input, e.g. Minecraft)
  pynput       keyboard/mouse for normal desktop apps
"""
import argparse
import os
import sys
from threading import Event, Thread

import serial

from djirc import protocol as dji

DEADZONE_KEYBOARD = 5000
DEADZONE_MOUSE = 10000
MOUSE_SENSITIVITY = 0.000043

# Momentary buttons -> tapped keys (drone-friendly: reset/menu/camera).
BUTTON_KEYS = {
    "record": "r",         # reset / respawn
    "rth": "backspace",    # restart
    "fn": "esc",           # menu
    "photo_video": "c",    # camera
}
# Flight-mode switch positions -> tapped keys.
MODE_KEYS = {"sport": "1", "normal": "2", "cinematic": "3"}


class DirectInputBackend:
    """Injects input via PyDirectInput (works in DirectInput / raw-input games)."""

    def __init__(self):
        import pydirectinput
        pydirectinput.PAUSE = 0
        self._m = pydirectinput

    def key_down(self, key):
        self._m.keyDown(key)

    def key_up(self, key):
        self._m.keyUp(key)

    def move(self, dx, dy):
        self._m.moveRel(dx, dy)

    def tap(self, key):
        self._m.press(key)


class PynputBackend:
    """Injects input via pynput (works in normal desktop apps)."""

    def __init__(self):
        from pynput.keyboard import Controller as Keyboard
        from pynput.keyboard import Key
        from pynput.mouse import Controller as Mouse
        self._k = Keyboard()
        self._mouse = Mouse()
        self._special = {
            "esc": Key.esc, "backspace": Key.backspace,
            "enter": Key.enter, "space": Key.space, "tab": Key.tab,
        }

    def key_down(self, key):
        self._k.press(key)

    def key_up(self, key):
        self._k.release(key)

    def move(self, dx, dy):
        self._mouse.move(dx, dy)

    def tap(self, key):
        k = self._special.get(key, key)
        self._k.press(k)
        self._k.release(k)


class VGamepadBackend:
    """Presents the controller as a virtual Xbox 360 pad (needs the ViGEmBus driver)."""

    is_gamepad = True

    def __init__(self):
        import vgamepad as vg
        self.pad = vg.VX360Gamepad()
        self._buttons = {
            "record": vg.XUSB_BUTTON.XUSB_GAMEPAD_A,
            "rth": vg.XUSB_BUTTON.XUSB_GAMEPAD_B,
            "fn": vg.XUSB_BUTTON.XUSB_GAMEPAD_X,
            "photo_video": vg.XUSB_BUTTON.XUSB_GAMEPAD_Y,
        }
        self._mode_dpad = {
            "cinematic": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT,
            "normal": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP,
            "sport": vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT,
        }

    def set_axes(self, lx, ly, rx, ry):
        self.pad.left_joystick(x_value=lx, y_value=ly)
        self.pad.right_joystick(x_value=rx, y_value=ry)

    def set_dial(self, value):
        """Bidirectional left dial -> triggers (right for +, left for -; the Z axis)."""
        mag = min(255, abs(int(value)) * 255 // 32767)
        self.pad.right_trigger(value=mag if value >= 0 else 0)
        self.pad.left_trigger(value=mag if value < 0 else 0)

    def set_button(self, name, pressed):
        btn = self._buttons.get(name)
        if btn is not None:
            (self.pad.press_button if pressed else self.pad.release_button)(button=btn)

    def set_mode(self, mode):
        for name, btn in self._mode_dpad.items():
            (self.pad.press_button if name == mode else self.pad.release_button)(button=btn)

    def update(self):
        self.pad.update()

    def reset(self):
        self.pad.reset()
        self.pad.update()


BACKENDS = {
    "directinput": DirectInputBackend,
    "pynput": PynputBackend,
    "vgamepad": VGamepadBackend,
}


def _vigembus_installer():
    """Return the path to the ViGEmBus MSI bundled with vgamepad, or None if missing."""
    try:
        import vgamepad
    except ImportError:
        return None
    arch = "x64" if sys.maxsize > 2 ** 32 else "x86"
    msi = os.path.join(os.path.dirname(vgamepad.__file__),
                       "win", "vigem", "install", arch, f"ViGEmBusSetup_{arch}.msi")
    return msi if os.path.exists(msi) else None


def _apply_key(backend, pressed, key, active):
    """Press or release a key only on transitions, tracking state in `pressed`."""
    if active and not pressed[key]:
        backend.key_down(key)
        pressed[key] = True
    elif not active and pressed[key]:
        backend.key_up(key)
        pressed[key] = False


def input_loop(backend, controller, stop_event):
    """Map controller state to input on a worker thread.

    Sticks drive WASD + mouse (held while deflected); buttons and the flight-mode
    switch fire single key taps on the press edge. Held keys are released on exit.
    """
    pressed = {'w': False, 'a': False, 's': False, 'd': False}
    prev_buttons = {name: False for name in BUTTON_KEYS}
    prev_mode = None
    try:
        while not stop_event.is_set():
            sticks = controller.sticks
            _apply_key(backend, pressed, 'w', sticks['left_y'] > DEADZONE_KEYBOARD)
            _apply_key(backend, pressed, 's', sticks['left_y'] < -DEADZONE_KEYBOARD)
            _apply_key(backend, pressed, 'd', sticks['left_x'] > DEADZONE_KEYBOARD)
            _apply_key(backend, pressed, 'a', sticks['left_x'] < -DEADZONE_KEYBOARD)

            rx, ry = sticks['right_x'], sticks['right_y']
            move_x = int(rx * MOUSE_SENSITIVITY) if abs(rx) > DEADZONE_MOUSE else 0
            move_y = -int(ry * MOUSE_SENSITIVITY) if abs(ry) > DEADZONE_MOUSE else 0
            if move_x or move_y:
                backend.move(move_x, move_y)

            buttons = controller.buttons
            for name, key in BUTTON_KEYS.items():
                if buttons.get(name) and not prev_buttons[name]:
                    backend.tap(key)
                prev_buttons[name] = buttons.get(name, False)

            mode = controller.mode
            if mode is not None and mode != prev_mode:
                if prev_mode is not None and mode in MODE_KEYS:
                    backend.tap(MODE_KEYS[mode])
                prev_mode = mode

            stop_event.wait(0.01)
    finally:
        for key, is_pressed in pressed.items():
            if is_pressed:
                backend.key_up(key)


def gamepad_loop(backend, controller, stop_event):
    """Map controller state to a virtual gamepad: sticks -> analog axes, buttons -> pad buttons."""
    try:
        while not stop_event.is_set():
            s = controller.sticks
            backend.set_axes(s['left_x'], s['left_y'], s['right_x'], s['right_y'])
            backend.set_dial(s['left_dial'])
            for name, pressed in controller.buttons.items():
                backend.set_button(name, pressed)
            backend.set_mode(controller.mode)
            backend.update()
            stop_event.wait(0.01)
    finally:
        backend.reset()


def main(argv=None):
    """Open the controller, start the input thread, and poll until interrupted."""
    parser = argparse.ArgumentParser(description="DJI RC-N1/N3 as a Windows gamepad or keyboard/mouse.")
    parser.add_argument('-p', '--port', help='RC serial port (auto-detected by default)')
    parser.add_argument('--backend', choices=list(BACKENDS), default='vgamepad',
                        help="Input backend: vgamepad (drone sims, default), "
                             "directinput (games), or pynput (desktop apps).")
    args = parser.parse_args(argv)

    try:
        backend = BACKENDS[args.backend]()
    except ImportError as e:
        print(f"Backend '{args.backend}' is unavailable: {e}")
        if args.backend == 'vgamepad':
            print("Install it with:  pip install vgamepad")
        return 1
    except Exception as e:   # e.g. ViGEmBus driver missing for vgamepad
        print(f"Could not initialize backend '{args.backend}': {e}")
        if args.backend == 'vgamepad':
            print("The ViGEmBus driver is required but is not installed.")
            msi = _vigembus_installer()
            if msi:
                print("Install it (a UAC prompt will appear), then retry:")
                print(f'  Start-Process msiexec.exe -ArgumentList \'/i "{msi}"\' -Verb RunAs -Wait')
            else:
                print("Get it from https://github.com/nefarius/ViGEmBus/releases")
        return 1

    try:
        controller = dji.Controller(args.port)
    except (RuntimeError, OSError, serial.SerialException) as e:
        print("Could not open controller:", e)
        return 1

    is_gamepad = getattr(backend, 'is_gamepad', False)
    print(f"Connected: {controller.name}  (backend: {args.backend})")
    if is_gamepad:
        print("Virtual Xbox pad: left stick = throttle/yaw, right stick = pitch/roll.")
        print("Buttons -> A/B/X/Y, flight mode -> D-pad. Calibrate in the sim. Ctrl+C to stop.")
    else:
        print("Left stick = keys (WASD), right stick = mouse. Ctrl+C to stop.")
        print("Buttons: Record=R  RTH=Backspace  Fn=Esc  Photo/Video=C  Mode=1/2/3")

    stop_event = Event()
    loop = gamepad_loop if is_gamepad else input_loop
    thread = Thread(target=loop, args=(backend, controller, stop_event), daemon=True)
    thread.start()
    try:
        while True:
            if not controller.poll(with_aux=True):
                controller.reset_sticks()
    except serial.SerialException as e:
        print('\n\nCould not read/write:', e)
    except KeyboardInterrupt:
        print('\n\nStopping.')
    finally:
        controller.reset_sticks()
        stop_event.set()
        thread.join(timeout=1)
        controller.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
