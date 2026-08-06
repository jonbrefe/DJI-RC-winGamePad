# PyInstaller spec: builds a single-file Windows .exe for the DJI RC adapter.
#
# Build (on Windows, with the backends installed):
#   pip install -e ".[all,build]"
#   python -m PyInstaller --clean --noconfirm DJI-RC-winGamePad.spec
# Output: dist/DJI-RC-winGamePad.exe and dist/DJI-RC-winGamePad-test.exe
#
# collect_all('vgamepad') bundles its ViGEmClient.dll and the ViGEmBusSetup MSI so the
# built-in "driver missing" hint can still point at the installer inside the bundle.
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for pkg in ("vgamepad",):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

# Backends are imported lazily inside __init__, so declare them explicitly.
hiddenimports += ["serial", "pydirectinput", "pynput", "pynput.keyboard", "pynput.mouse"]

# One-folder build: DLLs live next to the exes (no %TEMP% extraction), so machines with
# Smart App Control / WDAC that block temp-DLL loads can still run it. Both exes share one
# runtime folder via a single COLLECT.

# --- Adapter: main.py -> DJI-RC-winGamePad.exe (injects input) ---
a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DJI-RC-winGamePad",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# --- Tester: test_control.py -> DJI-RC-winGamePad-test.exe (GUI, no input injection) ---
test_a = Analysis(
    ["test_control.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["serial", "tkinter", "djirc.gui", "djirc.reader", "djirc.protocol"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

test_pyz = PYZ(test_a.pure)

test_exe = EXE(
    test_pyz,
    test_a.scripts,
    [],
    exclude_binaries=True,
    name="DJI-RC-winGamePad-test",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# Bundle both exes and their runtimes into one folder: dist/DJI-RC-winGamePad/
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    test_exe,
    test_a.binaries,
    test_a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DJI-RC-winGamePad",
)
