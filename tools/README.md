# Developer tools

Scripts used to reverse-engineer the tablet and calibrate the driver. They need Python 3.12 and run
from the repo root (e.g. `python tools/probe.py`). **Stop the tray app / driver first**: only one program
can open the tablet through WinUSB.

| Script | Driver needed | What it does |
|---|---|---|
| `probe.py` | stock HID | Dumps the HID collections and report layout (usages, report IDs, ranges). |
| `sniff.py [s]` | stock HID | Switches to absolute mode and prints raw reports. |
| `query.py` | stock HID | Queries model, firmware, X/Y extent and pressure levels. |
| `diag_cursor.py [s]` | either | Tablet mode **without** injection: logs whether Windows moves the cursor by itself. |
| `diag_devices.py` | either | Lists Windows pointer devices and their display mapping; tests hover injection. |
| `diag_inject.py` | — | Injects pen hover at known points and reads back the cursor position. |
| `record.py S out.csv` | driver running | Records raw reports forwarded by the running driver (UDP 47812). Close the settings window first, since it uses the same port. |
| `analyze_lines.py [csv]` | — | Analyzes ruler strokes: noise vs. periodic wobble, report rate. |
| `fit_calib.py csv...` | — | Fits the periodic coil correction (period scan, cross-validated) and writes `calib_candidate.json`. |

`data/ruler_strokes_12000U.csv` holds the ruler strokes the bundled 12000U calibration was fitted from.

## Calibrating coil correction for another tablet

1. Run the driver, close the settings window, then `python tools/record.py 30 strokes.csv` and draw slow
   straight lines along a ruler, in **both** diagonal directions, across the whole tablet.
2. `python tools/fit_calib.py strokes.csv`, which reports the before/after straightness on held-out strokes.
3. Copy `period`, `harmonics`, `x`, `y` from `calib_candidate.json` into `config.json` → `calibration`.
   (In `aiptek_driver.py` the correction is enabled only for PID `0x0010`; adjust that check.)
