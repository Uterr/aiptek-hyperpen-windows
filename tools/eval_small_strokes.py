"""Evaluate filters on small, slow strokes (tiny circles): how 'boxy' is the drawn path?

python tools/eval_small_strokes.py [csv]     (default: data/tiny_circles_12000U.csv, recorded with record.py)

The firmware holds each axis until the pen moved a few units, so tiny circles come out as rounded squares.
Metrics: share of the path (resampled at 0.5 px) running within 10 deg of horizontal/vertical (a circle: ~0.22),
average distance from a smoothed reference path, and how much of the stroke size is kept.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import numpy as np
import aiptek_driver as drv

HERE = os.path.dirname(os.path.abspath(__file__))
csv = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "tiny_circles_12000U.csv")
d = np.genfromtxt(csv, delimiter=",", names=True)
tip = (d["st"].astype(int) & 4) > 0
U = 3.125  # tablet units per screen pixel (6000 units -> 1920 px)
strokes, cur = [], []
for i in range(len(d) + 1):
    if i < len(d) and tip[i]:
        cur.append(i)
    elif cur:
        if len(cur) > 20:
            strokes.append(np.array(cur))
        cur = []


def axis_frac(P):
    seg = np.hypot(*np.diff(P, axis=0).T)
    s = np.r_[0, np.cumsum(seg)]
    if s[-1] < 5:
        return None
    q = np.arange(0, s[-1], 0.5 * U)
    R = np.c_[np.interp(q, s, P[:, 0]), np.interp(q, s, P[:, 1])]
    v = np.diff(R, axis=0)
    ang = np.degrees(np.arctan2(v[:, 1], v[:, 0])) % 90
    return np.mean((ang < 10) | (ang > 80))


def run(make):
    fr, err, keep = [], [], []
    for s in strokes:
        stages = make()
        raw = np.c_[d["x"][s], d["y"][s]].astype(float)
        out = []
        for i, k in enumerate(s):
            x, y = raw[i]
            for fx, fy in stages:
                x, y = fx(x, d["t"][k]), fy(y, d["t"][k])
            out.append((x, y))
        out = np.array(out)
        a = axis_frac(out)
        if a is not None:
            fr.append(a)
        k = 7
        ref = np.c_[np.convolve(raw[:, 0], np.ones(k) / k, "same"), np.convolve(raw[:, 1], np.ones(k) / k, "same")]
        err.append(np.mean(np.hypot(*(out[k:-k] - ref[k:-k]).T)) / U)
        keep.append(np.mean(np.ptp(out, 0) / np.maximum(np.ptp(raw, 0), 1)))
    return np.mean(fr), np.mean(err), np.mean(keep)


if __name__ == "__main__":
    print(f"{len(strokes)} strokes; a true circle is ~0.22 axis-aligned")
    cfgs = [("raw", lambda: [])]
    for h in (1.0, 1.5, 2.0, 3.0):
        cfgs.append((f"hold-interp h={h}", lambda h=h: [(drv.HoldInterp(h), drv.HoldInterp(h))]))
    for name, p in drv.SMOOTHING.items():
        if p:
            cfgs.append((f"1euro {name}", lambda p=p: [(drv.OneEuro(*p), drv.OneEuro(*p))]))
    for name, mk in cfgs:
        a, e, k = run(mk)
        print(f"{name:22s} axis-aligned {a:.2f}   off-path {e:4.2f} px   size kept {k * 100:3.0f}%")
