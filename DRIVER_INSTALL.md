# Installing the DJI RC-N1/N3 VCOM Driver Manually

This guide covers the DJI **USB VCOM** driver that creates the serial (COM) port named
`... USB VCOM For Protocol`. The code opens that port and reads stick data from it. No
other driver in the DJI Assistant 2 package is required.

For most users, the recommended and simplest option is to install
**[DJI Assistant 2 (Consumer Drones Series)](https://www.dji.com/downloads/softwares/dji-assistant-2-consumer-drones-series)**
and then close it. Use this guide only if you prefer to extract and install the VCOM
driver without installing the full DJI application.

The default `vgamepad` mode separately requires the
**[ViGEmBus 1.22.0 installer](https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe)**.
Download and run that `.exe` once. It is unrelated to DJI and is not needed when using
the `directinput` or `pynput` modes.

You can extract just the driver files and install them manually as described below.

---

## Why only this driver

The scripts detect the controller by looking for a COM port whose description contains
`For Protocol`:

```python
if "For Protocol" in port.description:
    s = serial.Serial(port=port.name, baudrate=115200, timeout=0.25)
```

That exact port name is defined by the DJI VCOM driver INF. It maps DJI USB IDs
(for example `VID_2CA3&PID_1010&MI_02`) to the Windows built-in USB serial class driver.

Notably, the VCOM package **ships no driver binary of its own** — the folder contains
only `.inf` and `.cat` files. The INF binds the device to Microsoft's in-box
`usbser.sys` (in `C:\Windows\System32\drivers`) and `mdmcpq.inf`, both of which already
exist on Windows 10/11. This is why manual installation works without any extra downloads.

---

## Licensing note

This is not legal advice; review DJI's End User License Agreement / Terms of Use for
your region. That said:

- The VCOM package contains **no DJI binary** — only an `.inf` (text mapping) and a
  `.cat` (signature). The actual driver, `usbser.sys`, is Microsoft's and already ships
  with Windows. Installing it does not reverse-engineer or modify DJI's software; it
  uses DJI's INF and catalog exactly as shipped.
- **This repository does not redistribute any DJI files.** These steps have you extract
  the driver from **your own** copy of DJI Assistant 2, obtained from DJI. Do not commit
  the extracted `.inf`/`.cat` (or the installer) into this project.
- If you prefer to avoid DJI's files entirely, you can author your own `Ports`-class INF
  that binds the DJI USB IDs to `usbser.sys`; however, an unsigned INF may trigger
  Windows driver-signature enforcement, whereas DJI's `.cat` is already WHQL-signed.

---

## Step 1 - Extract the driver without running the installer

The DJI Assistant 2 installer is an Inno Setup executable. You can unpack it as data,
without executing it, using [innoextract](https://constexpr.org/innoextract/) 1.9 or
newer (older versions do not support the installer's Inno Setup 6.1 format).

**Windows (PowerShell):**

```powershell
# Download innoextract for Windows from the official site:
#   https://constexpr.org/innoextract/files/
# Unzip it, then from the folder containing innoextract.exe:

.\innoextract.exe --list  "path\to\DJI Assistant 2(Consumer Drones Series) 2.1.40.exe"
.\innoextract.exe --extract --output-dir extracted  "path\to\DJI Assistant 2(Consumer Drones Series) 2.1.40.exe"
```

**Linux / WSL:**

```bash
innoextract --list "DJI Assistant 2(Consumer Drones Series) 2.1.40.exe"
innoextract --extract --output-dir extracted "DJI Assistant 2(Consumer Drones Series) 2.1.40.exe"
```

The driver files you need are here:

```
extracted/app/Drivers/Drivers_Win10/VCOM/
├── dji_vcom_driver11.inf   # DJI-branded INF   -> "DJI USB VCOM For Protocol"
├── djidriver.cat           # signature catalog for dji_vcom_driver11.inf
├── vcom_driver11.inf       # generic INF       -> "DEVICE USB VCOM For Protocol"
└── vcom_driver.cat         # signature catalog for vcom_driver11.inf
```

Copy the whole `VCOM` folder somewhere convenient. Keep each `.inf` next to its `.cat`
file so the driver signature validates during installation.

> Use `dji_vcom_driver11.inf` for the cleaner port name "DJI USB VCOM For Protocol".
> Either INF works; both create the "For Protocol" port the code looks for.

---

## Step 2 - Install the driver

Connect and power on the RC-N1/N3 first (bottom USB-C port), then use one of the
methods below.

### Option A - pnputil (recommended)

This step **must** run in an elevated (Administrator) shell. Writing to the Windows
driver store requires it — a normal prompt fails with `Access is denied.`
(`pnputil` exit code `5`). To open one: press **Start**, type `PowerShell`,
right-click **Windows PowerShell**, and choose **Run as administrator**.

Then `cd` into the `VCOM` folder and run:

```powershell
pnputil /add-driver dji_vcom_driver11.inf /install
```

- `/add-driver` stages the INF into the Windows driver store.
- `/install` binds it to the currently connected DJI device. Omit `/install` to only
  stage the package when the controller is not attached.

A successful run reports `Added driver packages:  1`. The driver's `.cat` catalogs are
WHQL-signed by Microsoft, so it installs without signature warnings.

### Option B - Device Manager

1. Open **Device Manager**.
2. Find the DJI device (it may appear under **Other devices** with a warning icon).
3. Right-click it → **Update driver** → **Browse my computer for drivers**.
4. Point it at the `VCOM` folder and click **Next**.

---

## Step 3 - Verify

In Device Manager, expand **Ports (COM & LPT)**. You should see an entry like:

```
DJI USB VCOM For Protocol (COM9)
```

The `COMx` number is assigned automatically. The scripts auto-detect it, so you do not
need to hard-code it. To select a specific port explicitly:

```powershell
python main.py --port COM9
```

---

## Notes

- Do **not** run `installer_x64.exe` / `installer_x86.exe` from the extracted
  `Drivers` tree. Those install the BULK / Vision / WinUSB drivers, which this project
  does not use.
- If Windows reports the driver is already provided or up to date, the VCOM port is
  already available and no action is needed.
- Removing the driver later: find its published name with `pnputil /enum-drivers`, then
  run `pnputil /delete-driver oemNN.inf /uninstall` (replace `oemNN.inf` with the
  published name).
