"""Tiny circles at 500 vs 3048 lpi: does the finer resolution make them rounder?

Stop the driver first, run:  python tools/resolution_compare.py
It waits until the pen touches, then alternates the resolution every few seconds; keep drawing tiny circles.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import time
import numpy as np
import tablet_io

SECS = 8
U = 3.125  # 500-lpi units per screen pixel


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
size500, scale3048 = tablet_io.setup_resolution(tab, 3048)
print(f"3048 lpi scale factor: {scale3048:.3f}")
tablet_io.set_mode(tab, True, 0x04)
print("Touch the tablet and keep drawing tiny circles (5-10 px)...", flush=True)
while True:
    r = tab.read()
    if r and r[0] == 2 and len(r) >= 8 and r[5] & 0x04:
        break
results = {500: [], 3048: []}
for rnd in range(4):
    for lpi, code, scale in ((500, 0x04, 1.0), (3048, 0x0C, scale3048)):
        tablet_io.set_mode(tab, True, code)
        strokes, cur, end = [], [], time.time() + SECS
        while time.time() < end:
            r = tab.read()
            if not r or len(r) < 8 or r[0] != 2:
                continue
            if r[5] & 0x04 and not r[5] & 0x18:
                cur.append(((r[1] | r[2] << 8) / scale, (r[3] | r[4] << 8) / scale))
            elif cur:
                strokes.append(cur); cur = []
        if cur:
            strokes.append(cur)
        strokes = [np.array(s) for s in strokes if len(s) > 15]
        if not strokes:
            print(f"round {rnd + 1} {lpi:4d} lpi: no strokes", flush=True)
            continue
        d = np.concatenate([np.diff(s, axis=0) for s in strokes])
        af = np.nanmean([axis_frac(s) for s in strokes])
        none = np.mean((d[:, 0] == 0) & (d[:, 1] == 0))
        both = np.mean((d[:, 0] != 0) & (d[:, 1] != 0))
        results[lpi].append(af)
        print(f"round {rnd + 1} {lpi:4d} lpi: axis-aligned {af:.2f}  unchanged {none:.2f}  both-axes {both:.2f}"
              f"  n={sum(len(s) for s in strokes)}", flush=True)
tablet_io.set_mode(tab, True, 0x04)
tab.close()
print("\nAverage axis-aligned (true circle ~0.22): " +
      ", ".join(f"{k} lpi {np.nanmean(v):.2f}" for k, v in results.items() if v))
print("Done.")
