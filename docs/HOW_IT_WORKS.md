# How it works

## The tablet

The HyperPen 12000U is a USB HID device with three top-level collections:

| Collection | Usage | Reports |
|---|---|---|
| COL01 | Generic Desktop / Mouse | id 1: relative mouse (what Windows uses by default) |
| COL02 | Generic Desktop / Mouse | id 7: absolute mouse, 0–11997 |
| COL03 | Digitizer | id 2: stylus absolute, id 3: puck, id 4–6: macro keys; **feature report 2** (3 bytes) |

It powers up in **relative "mouse mode"**. Commands are sent as `SET_REPORT(Feature, id 2) = [2, cmd, data]`
and queries are read back with `GET_REPORT(Feature, id 2)`, the same as the Linux `aiptek` driver:

| cmd, data | Meaning |
|---|---|
| `10 01` / `10 00` | **switch to tablet (absolute) mode** / back to mouse mode. *Resets the resolution to 500 lpi.* |
| `18 nn` | resolution (send **after** `10 01`), see below |
| `11 02` | enable macro keys |
| `12 FF` | auto gain on |
| `01 00` / `01 01` | query X / Y extent at the current resolution (12000U: 6000 × 4500 at 500 lpi) |
| `08 00` | query pressure levels (512) |
| `02 00` | query model code |

### Resolution: up to 3048 lpi

The Linux driver uses `18 04` (500 lpi). The firmware accepts more codes, and the reported extent and the pen
coordinates change accordingly, **but only if the resolution command comes after the switch to tablet mode**.
`10 01` silently resets the resolution to 500 lpi, so sending `18 nn` first (as Linux does) always ends up at
500 lpi.

| `18 nn` | lpi | active area (12000U) |
|---|---|---|
| `00` / `01` / `02` / `03` | 100 / 200 / 254 / 400 | 1200×900 / 2400×1800 / 3048×2286 / 4800×3600 |
| `04` | 500 | 6000 × 4500 |
| `05` | 508 | 6096 × 4572 |
| `06` / `07` | 1000 / 1016 | 12000 × 9000 / 12192 × 9144 |
| `08` / `09` | 2000 / 2032 | 24000 × 18000 / 24384 × 18288 |
| `0A` / `0B` | 2540 / 3000 | 30480 × 22860 / 36000 × 27000 |
| `0C` | **3048** | **36576 × 27432** |

Why it matters: the firmware only reports a new X (or Y) once the pen has moved by a minimum number of
*output units*, a per-axis hold. At 500 lpi that is about 0.1–0.2 mm, so slow, tiny strokes come out as
staircases and small circles look like rounded squares. At 3048 lpi the hold band is six times smaller. Measured
on tiny circles (`tools/resolution_compare.py`): the share of the path running exactly horizontal or vertical
drops from **0.75 to 0.44** (a true circle: ~0.22), and reports where both axes changed rise from ~8% to ~50%.

The driver uses 3048 lpi by default (setting *Sensor resolution*). It measures the scale factor from the
extents reported at both resolutions and falls back to 500 lpi if a model doesn't respond the same way. All
settings stay in 500-lpi units, and the extra precision is kept as fractions.

### Other commands tried

* `17 nn` (*FilterOn* in the Linux driver): no value made strokes smoother than the power-on default. `17 00`
  freezes the pen completely, and `17 01` / `17 03` make it much more "sticky". Not used.
* `12 00` (auto gain off): the pen is barely detected. Keep `12 FF`.
* `10 02` / `10 03` / `10 04`: no reports at all.

All of these are volatile: replugging the tablet restores the power-on state.

### Reports

In tablet mode the stylus sends 8-byte reports at about 125 Hz:

```
02  xL xH  yL yH  status  pL pH
status: 01 in range | 02 near/light contact | 04 tip down | 08 lower side button | 10 upper side button
```

Pressure really spans about 60–500, even though the descriptor says 0–1023. While a side button is held,
the pressure field reads `0x3FF`, so it's ignored.

## Why WinUSB

Once the tablet is in absolute mode, Windows' own HID stack *also* recognizes the digitizer collection as an
external pen. It maps that pen over the **whole virtual desktop** using the descriptor's 0–12000 range,
while the real range is 0–6000 / 0–4500. Every stroke then arrives twice: once from this driver at the right
place, and once from Windows, shrunk into a corner. A user-mode program can't switch that off.

So the app binds the device to Microsoft's inbox **WinUSB** driver (`winusb.inf`, "WinUsb Device").
Device Manager hides that choice for HID devices, so `winusb_install.py` uses SetupAPI directly: it moves
the device node to the *USBDevice* class, builds a driver list from `winusb.inf`, and calls
`DiInstallDevice`. With WinUSB the driver talks to the tablet with raw control transfers (mode commands)
and interrupt-IN reads (endpoint `0x81`), and Windows itself no longer sees a mouse or pen.

Without a USB serial number, Windows keys the device node to the **USB port**, so each new port has to be
switched once. The tray app detects that case and offers to do it.

## Injecting the pen

Positions are sent with `CreateSyntheticPointerDevice(PT_PEN)` + `InjectSyntheticPointerInput`, which
apps see as a Windows Ink pen with pressure. One subtlety: the synthetic pen spans the virtual desktop,
and its pixel coordinates are measured **from the virtual desktop's top-left corner**, not from the
primary monitor's origin. With a monitor above or left of the main one, that corner is negative (e.g.
`(0, -1200)`), so the driver subtracts `SM_XVIRTUALSCREEN` / `SM_YVIRTUALSCREEN`. Without that, the pen lands
on the wrong monitor and can't reach part of the screen.

The process is per-monitor DPI aware, so all coordinates are physical pixels.

## Pipeline

```
raw report ─► ÷ scale (to 500-lpi units) ─► small-stroke rounding (optional) ─► coil correction ─► smoothing (optional) ─► area → monitor mapping ─► pen injection
                (x += fx(x),       (1€ filter)              (aspect-locked rect      (pressure via
                 y += fy(y))                                 on the tablet)            range + curve)
```

* **Coil correction**: ruler-drawn diagonals on the 12000U show a periodic error with a period of about 124
  tablet units in X and Y (the coil pitch). A 2-harmonic Fourier correction per axis, fitted with
  `tools/fit_calib.py`, removes most of it (about 12% straighter lines overall). The rest is mostly pen tilt.
* **Pressure**: `out = clamp((raw − min) / (max − min)) ^ curve`, with min, max and curve set in Settings.

## Processes

* The tray app runs the driver (`DriverService`) in background threads and holds a named mutex, so only one
  instance runs.
* The settings window is a separate process. It writes `config.json`, which the driver reloads within a
  second. The driver forwards raw reports to `127.0.0.1:47812` (UDP) so the settings window can show the
  pen while the driver owns the device.
* Installing copies the exe to `%LOCALAPPDATA%\Programs\AiptekTablet`, adds an `HKCU\...\Run` entry, a
  Start menu shortcut and an `HKCU` uninstall entry. Only the WinUSB switch needs admin rights.
