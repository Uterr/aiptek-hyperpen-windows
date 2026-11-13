# Troubleshooting & known caveats

First check the tray icon's tooltip or menu, which shows the status (*Tablet connected*, *Waiting for the
tablet*, *Tablet needs setup on this USB port*), and the log: tray menu → **Open log**
(`%APPDATA%\AiptekTablet\driver.log`).

## No pressure in Clip Studio Paint (or another app)

The driver sends a **Windows Ink** pen. It does **not** provide **Wintab** (the older tablet API from Wacom).

* **Clip Studio Paint**: *File → Preferences → Tablet → Tablet service* → **TabletPC**, then restart Clip
  Studio. With *Wintab* selected you get lines without pressure.
* **Krita**: *Settings → Configure Krita → Tablet settings* → **Windows 8+ Pointer Input (Windows Ink)**.
* **Photoshop**: uses Windows Ink unless `UseSystemStylus 0` is set in a `PSUserConfig.txt`; remove it.
* **GIMP**: *Edit → Input Devices*, set the pen device to *Screen* mode.
* Apps that support **only Wintab** (some older software, e.g. old versions of Painter or SAI 1) won't get
  pressure. A Wintab layer may be added in the future.

## Pressure feels too weak or too strong

Open **Settings → 3. Pressure** and click **Measure my hardest press**, then press as hard as you normally
draw for 5 seconds. That raw value becomes 100%.

* Lines appear when you only hover or barely touch: raise **Light touch starts at**.
* Hard to reach full brush size: move **Curve** toward *soft*.
* Too sensitive for light strokes: move **Curve** toward *firm*.

Apps apply **their own pressure curve on top** of this one (Clip Studio: *File → Adjust pen pressure
detection level*; Krita: brush editor). Calibrate here first, then fine-tune in the app.

*Background:* the tablet's descriptor claims pressure 0–1023, but the pen really reports about 60–500 (512
levels). Scaling by 1023 makes even hard presses look like 10–20%, which is why calibration exists.

## Double cursor / strokes drawn twice / pen lands on the wrong monitor

This happens when the tablet is still on Windows' own **HID** driver. Windows then also treats it as a pen,
stretched over all monitors with the wrong coordinate range, while this driver sends the correct position.

* The tray shows *Tablet needs setup on this USB port* and offers to fix it. Accept the admin prompt.
* Or run the installer again, or `winusb_install.py --install` from source.

## Works on one USB port but not another

Windows assigns drivers **per USB port** (this tablet has no serial number). The first time you use a new
port, the tablet appears with Windows' default driver. The app notices and asks to set up that port (one
admin prompt per port). Until then you may get double input, as described above.

## The tablet does nothing at all

* Is the app running (tray icon)? With WinUSB installed, **the tablet only works while the app runs**. Even
  the plain mouse mode is gone, because Windows no longer drives it. Start it from the Start menu
  (*Aiptek HyperPen 12000U Tablet Driver*).
* Is the pen's battery OK? The HyperPen's pen has an AAA battery. A weak battery causes dropouts, jitter
  and a short hover range.
* Unplug and replug the tablet; the app reconnects automatically. Check the log for errors.
* Only one program can open the tablet through WinUSB at a time. Close other copies of the driver or
  tools from `tools/`.

## The cursor can't reach an edge of the screen

* Make sure the blue area in Settings covers the part of the tablet you use. The dotted box shows how far
  the pen has actually reported.
* After changing display resolution or arrangement, the driver picks up the new layout within a few seconds.

## Diagonal lines look wavy

Two effects add up:

1. **Coil ripple**: a small regular wave (period ≈ 0.25" on the tablet) caused by the grid of sensing coils.
   **Coil correction** (on by default for the 12000U) removes most of it.
2. **Pen tilt**: the position is sensed from a coil a few mm above the tip, so tilting the pen while
   drawing shifts the line slightly. This tablet doesn't report tilt, so it can't be corrected. Holding the
   pen at a constant angle helps.

**Smoothing** reduces jitter but not these slow waves, and it adds lag.

## SmartScreen / antivirus warnings

The exe is not code-signed, so SmartScreen warns on first run (*More info → Run anyway*). Some antivirus
products flag PyInstaller-packed programs generically. You can build the exe yourself from source (see the
README) or run the Python sources directly.

## After sleep / resume

The tablet may come back in relative mouse mode after the PC sleeps. The driver re-sends the absolute-mode
command when the tablet has been silent for a while, and reconnects if the USB device was reset. If the pen
doesn't respond after waking, lift it out of range for a few seconds or replug the tablet.

## Going back to the original Windows driver

Uninstall the app (Settings → Apps, or tray menu), which restores the driver automatically. Manually:
*Device Manager → Universal Serial Bus devices → USB Tablet Series → Uninstall device*, then replug the
tablet. From source: `python winusb_install.py --restore`.

## Reporting a problem

Please open an issue with:

* tablet model and USB ID (*Device Manager → device → Details → Hardware Ids*, e.g. `USB\VID_08CA&PID_0010`);
* Windows version;
* the relevant part of `%APPDATA%\AiptekTablet\driver.log`;
* for other tablet models: the output of `python tools/probe.py` taken **before** installing (stock driver).
