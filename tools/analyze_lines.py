"""Analyze ruler-drawn strokes: noise vs systematic (coil) wobble."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import sys
import numpy as np

d = np.genfromtxt(sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ruler_strokes_12000U.csv"), delimiter=",", names=True)
tip = (d["st"].astype(int) & 4) > 0
# strokes = runs of tip-down
strokes, cur = [], []
for i in range(len(d)):
    if tip[i]:
        cur.append(i)
    elif cur:
        strokes.append(cur); cur = []
if cur:
    strokes.append(cur)
dt = np.diff(d["t"])
print(f"report interval median {np.median(dt)*1000:.1f} ms (~{1/np.median(dt):.0f} Hz)")
for s in strokes:
    if len(s) < 60:
        continue
    x, y, t = d["x"][s], d["y"][s], d["t"][s]
    P = np.c_[x, y].astype(float)
    c = P.mean(0)
    u, sv, vt = np.linalg.svd(P - c, full_matrices=False)
    along = (P - c) @ vt[0]
    perp = (P - c) @ vt[1]
    L = along.max() - along.min()
    # remove slow hand curvature (ruler can flex / hand lean): subtract a quadratic in 'along'
    q = np.polyfit(along, perp, 2)
    res = perp - np.polyval(q, along)
    hf = np.diff(res)
    only_x = np.sum((np.diff(x) != 0) & (np.diff(y) == 0)); only_y = np.sum((np.diff(x) == 0) & (np.diff(y) != 0))
    both = np.sum((np.diff(x) != 0) & (np.diff(y) != 0)); none = np.sum((np.diff(x) == 0) & (np.diff(y) == 0))
    ang = np.degrees(np.arctan2(vt[0][1], vt[0][0]))
    print(f"\nstroke n={len(s)} len={L:.0f}u ({L/500:.1f}in) angle={ang:.0f}deg dur={t[-1]-t[0]:.2f}s")
    print(f"  residual std {res.std():.1f}u  peak-peak {np.ptp(res):.0f}u   sample-to-sample std {hf.std():.1f}u")
    print(f"  steps: x-only {only_x}, y-only {only_y}, both {both}, none {none}")
    # periodicity of residual along the stroke (resample on uniform 'along' grid)
    order = np.argsort(along)
    a_s, r_s = along[order], res[order]
    grid = np.arange(a_s[0], a_s[-1], 5.0)
    rg = np.interp(grid, a_s, r_s)
    rg -= rg.mean()
    F = np.abs(np.fft.rfft(rg * np.hanning(len(rg))))
    freqs = np.fft.rfftfreq(len(rg), d=5.0)
    k = np.argsort(F[1:])[::-1][:3] + 1
    print("  strongest wobble periods (tablet units along stroke):",
          ", ".join(f"{1/freqs[i]:.0f}u (amp {F[i]/len(rg)*4:.1f})" for i in k))
    # residual vs absolute x and y to look for coil-pitch error
    for name, v in (("x", x), ("y", y)):
        bins = np.arange(v.min(), v.max(), 25)
        idx = np.digitize(v, bins)
        prof = [res[idx == b].mean() for b in range(1, len(bins)) if np.sum(idx == b) > 2]
        print(f"  residual binned by {name} (25u bins): " + " ".join(f"{p:+.0f}" for p in prof[:40]))
