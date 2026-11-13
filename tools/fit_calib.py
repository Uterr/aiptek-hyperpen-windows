"""Fit a periodic (coil-pitch) correction x' = x + fx(x), y' = y + fy(y) that makes ruler strokes straight.

python fit_calib.py data.csv [more.csv ...]
Each correction is a Fourier series with period P (scanned) and K harmonics. Each stroke gets its own
line (+ a gentle quadratic to absorb hand/ruler drift). Odd/even strokes are used for cross-validation.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import json, sys
import numpy as np


def load_strokes(files, min_len=60):
    out = []
    for f in files:
        d = np.genfromtxt(f, delimiter=",", names=True)
        tip = (d["st"].astype(int) & 4) > 0
        cur = []
        for i in range(len(d) + 1):
            if i < len(d) and tip[i]:
                cur.append(i)
            elif cur:
                if len(cur) >= min_len:
                    s = np.array(cur[3:-3])  # drop touch-down/lift-off samples
                    out.append(np.c_[d["x"][s], d["y"][s]].astype(float))
                cur = []
    return out


def basis(v, P, K):
    w = 2 * np.pi * v / P
    return np.column_stack([f(k * w) for k in range(1, K + 1) for f in (np.sin, np.cos)])


def fit(strokes, P, K, coef=None, iters=3):
    """Least squares for Fourier coefs; returns coef (2*2K) and per-stroke residuals."""
    nb = 2 * K
    for _ in range(iters):
        rows, rhs = [], []
        ns = len(strokes)
        for si, S in enumerate(strokes):
            C = S if coef is None else apply(S, coef, P, K)
            c = C.mean(0)
            _, _, vt = np.linalg.svd(C - c, full_matrices=False)
            d_, n = vt[0], vt[1]
            along = (S - S.mean(0)) @ d_
            along /= max(np.abs(along).max(), 1)
            Bx, By = basis(S[:, 0], P, K), basis(S[:, 1], P, K)
            A = np.zeros((len(S), 2 * nb + 3 * ns))
            A[:, :nb] = n[0] * Bx
            A[:, nb:2 * nb] = n[1] * By
            A[:, 2 * nb + 3 * si] = -1
            A[:, 2 * nb + 3 * si + 1] = -along
            A[:, 2 * nb + 3 * si + 2] = -along ** 2
            rows.append(A)
            rhs.append(-(S @ n))
        A, b = np.vstack(rows), np.concatenate(rhs)
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
        coef = sol[:2 * nb]
    return coef


def apply(S, coef, P, K):
    nb = 2 * K
    return np.c_[S[:, 0] + basis(S[:, 0], P, K) @ coef[:nb], S[:, 1] + basis(S[:, 1], P, K) @ coef[nb:]]


def straightness(strokes, coef=None, P=None, K=None):
    """RMS perpendicular residual after per-stroke line+quadratic fit."""
    tot, n = 0.0, 0
    for S in strokes:
        C = S if coef is None else apply(S, coef, P, K)
        c = C.mean(0)
        _, _, vt = np.linalg.svd(C - c, full_matrices=False)
        along, perp = (C - c) @ vt[0], (C - c) @ vt[1]
        r = perp - np.polyval(np.polyfit(along, perp, 2), along)
        tot += np.sum(r ** 2); n += len(r)
    return np.sqrt(tot / n)


if __name__ == "__main__":
    strokes = load_strokes(sys.argv[1:])
    print(len(strokes), "strokes")
    train, test = strokes[0::2], strokes[1::2]
    base_tr, base_te = straightness(train), straightness(test)
    print(f"before: train {base_tr:.2f}u  test {base_te:.2f}u")
    best = None
    for K in (1, 2, 3):
        for P in np.arange(60, 420, 2.0):
            coef = fit(train, P, K, iters=1)
            te = straightness(test, coef, P, K)
            if best is None or te < best[0]:
                best = (te, P, K, coef)
    te, P, K, coef = best
    coef = fit(train, P, K, coef)
    print(f"best: period {P:.0f}u, {K} harmonics -> test {straightness(test, coef, P, K):.2f}u"
          f" (train {straightness(train, coef, P, K):.2f}u)")
    full = fit(strokes, P, K, None)
    print(f"all strokes after: {straightness(strokes, full, P, K):.2f}u (before {straightness(strokes):.2f}u)")
    nb = 2 * K
    print("x amplitude:", np.round(np.hypot(full[:nb:2], full[1:nb:2]), 1),
          " y amplitude:", np.round(np.hypot(full[nb::2], full[nb + 1::2]), 1))
    json.dump({"period": float(P), "harmonics": K, "x": full[:nb].tolist(), "y": full[nb:].tolist()},
              open("calib_candidate.json", "w"), indent=1)
    print("wrote calib_candidate.json")
