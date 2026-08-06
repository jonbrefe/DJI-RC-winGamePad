# Contributing

Thanks for your interest in improving this project! It turns a DJI RC-N1/N3 remote
controller into Windows input (a virtual gamepad, or keyboard/mouse).

## Development setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,all]"
```

- `pip install -e .` installs the `djirc` library plus the `djirc-run` / `djirc-test`
  console scripts in editable mode.
- The `dev` extra adds `pytest` and `ruff`; `all` adds every input backend.
- The default `vgamepad` backend is Windows-only and requires the
  **[ViGEmBus 1.22.0 installer](https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe)**.
  The `directinput` and `pynput` backends do not require it.

## Running tests

Tests are fully offline — no controller, driver, or `vgamepad` install required. They
mock the serial port and the virtual pad.

```powershell
pytest
ruff check .
```

Please add or update tests under `tests/` for any protocol or backend change.

## Building the Windows binary

The standalone `.exe` is built with PyInstaller from `DJI-RC-winGamePad.spec`. Build it
on Windows with every backend installed so they get bundled:

```powershell
pip install -e ".[all,build]"
python -m PyInstaller --clean --noconfirm DJI-RC-winGamePad.spec
```

The result is `dist/DJI-RC-winGamePad/` - a one-folder bundle containing both
`DJI-RC-winGamePad.exe` (the adapter) and `DJI-RC-winGamePad-test.exe` (the tester)
sharing one runtime. The one-folder layout avoids `%TEMP%` DLL extraction, but Smart App
Control or WDAC can still block the unsigned executable itself. Pushing a `v*` tag zips
this folder and attaches it, with a SHA-256 checksum, to a GitHub Release (see
`.github/workflows/release.yml`). The build still requires the VCOM driver and, for the
default `vgamepad` mode, the ViGEmBus 1.22.0 installer executable on the target machine.

## Testing with real hardware

- Connect the RC's bottom USB-C port, then run `python test_control.py` to visualize
  the sticks/buttons without injecting any input.
- Console explorers: `--discover`, `--sweep`, `--watch SET ID`, and `--diff` help map
  new packet bytes (see the README "Testing the controller" section).

## Notes on the dev environment

- The runtime is Windows (pyserial + tkinter + a backend). If you develop from WSL, use
  `python3 -m py_compile` for quick syntax checks, but run the real program and the
  hardware tools from a native Windows shell.
- Do **not** commit any DJI driver files (`*.inf`, `*.cat`, `*.sys`) or the extracted
  DJI Assistant 2 tree — they are vendor files and are git-ignored. Users extract those
  from their own DJI download (see [DRIVER_INSTALL.md](DRIVER_INSTALL.md)).

## Code style

- Follow the existing style; `ruff` enforces formatting-adjacent lint rules
  (`ruff check .`). Line length is 120.
- Keep the `djirc` library import-light: `djirc/__init__.py` deliberately does not import
  `tkinter`; keep GUI code inside `djirc.gui`.
- Backends import their heavy dependency lazily inside `__init__` so the CLI and tests
  load without every backend installed.

## Submitting changes

1. Create a branch, make your change, add tests.
2. Ensure `ruff check .` and `pytest` pass.
3. Update `CHANGELOG.md` under "Unreleased".
4. Open a pull request describing the change and how you tested it.
