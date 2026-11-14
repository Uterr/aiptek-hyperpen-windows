"""Compare the firmware's 0x17 filter setting on tiny circles (draw them continuously while this runs).

Stop the driver/tray app first.  python tools/filter_compare.py [seconds_per_setting]
Replug the tablet afterwards to reset the firmware to its power-on state.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import time
import numpy as np
import tablet_io

SECS = float(sys.argv[1]) if len(sys.argv) > 1 else 7
U = 3.125
SETTINGS = [("power-on default", None)] + [(f"0x17 0x{v:02X}", v) for v in range(8)] + [("default again", None)]


def axis_frac(P):
    seg = np.hypot(*np.diff(P, axis=0).T)
    s = np.r_[0, np.cumsum(seg)]
    if s[-1] < 5:
        return float("nan")
    q = np.arange(0, s[-1], 0.5 * U)
    R = np.c_[np.interp(q, s, P[:, 0]), np.interp(q, s, P[:, 1])]
    v = np.diff(R, axis=0)
    ang = np.degrees(np.arctan2(v[:, 1], v[:, 0])) % 90
    return np.mean((ang < 10) | (ang > 80))


tab = tablet_io.open_tablet()
if not tab:
    sys.exit("tablet not found (or busy - stop the driver first)")
tablet_io.set_mode(tab, True)
for label, val in SETTINGS:
    if val is not None:
        tab.command(0x17, val)
    time.sleep(0.1)
    strokes, cur, end = [], [], time.time() + SECS
    while time.time() < end:
        r = tab.read()
        if not r or len(r) < 8 or r[0] != 2:
            continue
        if r[5] & 0x04 and not r[5] & 0x18:
            cur.append((r[1] | r[2] << 8, r[3] | r[4] << 8))
        elif cur:
            strokes.append(cur); cur = []
    if cur:
        strokes.append(cur)
    strokes = [np.array(s, float) for s in strokes if len(s) > 15]
    n = sum(len(s) for s in strokes)
    if n < 50:
        print(f"{label:18s} too little tip-down data ({n})")
        continue
    d = np.concatenate([np.diff(s, axis=0) for s in strokes])
    none = np.mean((d[:, 0] == 0) & (d[:, 1] == 0))
    both = np.mean((d[:, 0] != 0) & (d[:, 1] != 0))
    af = np.nanmean([axis_frac(s) for s in strokes])
    span = np.mean([np.ptp(s, 0).mean() for s in strokes]) / U
    print(f"{label:18s} n={n:4d}  axis-aligned {af:.2f}  unchanged {none:.2f}  both-axes {both:.2f}"
          f"  avg stroke size {span:4.1f}px")
tab.close()
print("Done - please unplug and replug the tablet to reset its firmware state.")
