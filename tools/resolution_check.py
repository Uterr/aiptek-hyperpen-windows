"""Do the cmd 0x18 resolution codes change the coordinates in pen reports, or only the reported extent?

Stop the driver first, hover the pen at the tablet's bottom-right corner, run:  python tools/resolution_check.py
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import time
import tablet_io

tab = tablet_io.open_tablet()
if not tab:
    sys.exit("tablet not found (or busy - stop the driver first)")
for lpi, code in ((500, 0x04), (3048, 0x0C), (1000, 0x06), (500, 0x04)):
    tablet_io.set_mode(tab, True, code)
    time.sleep(0.2)
    xs, ys, end = [], [], time.time() + 2
    while time.time() < end:
        r = tab.read()
        if r and len(r) >= 8 and r[0] == 2 and r[5] & 0x07:
            xs.append(r[1] | r[2] << 8); ys.append(r[3] | r[4] << 8)
    print(f"{lpi:5d} lpi (0x{code:02X}): {len(xs):3d} reports, x {min(xs, default=0)}..{max(xs, default=0)}"
          f"  y {min(ys, default=0)}..{max(ys, default=0)}")
tab.close()
