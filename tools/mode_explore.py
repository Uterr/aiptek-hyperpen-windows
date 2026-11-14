"""Explore tablet modes: which command sequences change the report IDs or coordinate range?

Stop the driver first, hover the pen over the tablet's bottom-right corner, run:  python tools/mode_explore.py
All settings are volatile: replug the tablet afterwards to get back to the power-on state.
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import time
import tablet_io

BASE = [(0x18, 0x04), (0x10, 0x01), (0x11, 0x02), (0x12, 0xFF)]
CONFIGS = [
    ("baseline (driver default)", BASE),
    ("tablet mode, THEN 1000 lpi", [(0x10, 0x01), (0x18, 0x06)]),
    ("tablet mode, THEN 3048 lpi", [(0x10, 0x01), (0x18, 0x0C)]),
    ("tablet mode only", [(0x10, 0x01)]),
    ("baseline + auto gain off", BASE + [(0x12, 0x00)]),
    ("mode 0x10 0x02", [(0x10, 0x02)]),
    ("mode 0x10 0x03", [(0x10, 0x03)]),
    ("mode 0x10 0x04", [(0x10, 0x04)]),
    ("baseline again", BASE),
]

tab = tablet_io.open_tablet()
if not tab:
    sys.exit("tablet not found (or busy - stop the driver first)")
tablet_io.set_mode(tab, True)
print("Waiting for the pen (hover it over the bottom-right corner)...", flush=True)
end = time.time() + 90
while time.time() < end:
    r = tab.read()
    if r and r[0] == 2 and len(r) >= 8 and r[5] & 0x07:
        break
else:
    sys.exit("no pen seen in 90 s")
print("Pen seen, testing.\n", flush=True)
for label, cmds in CONFIGS:
    ok = all(tab.command(c, d) or time.sleep(0.03) for c, d in cmds)
    time.sleep(0.2)
    seen, end = {}, time.time() + 2.0
    while time.time() < end:
        r = tab.read()
        if not r:
            continue
        rid = r[0]
        s = seen.setdefault(rid, {"n": 0, "x": 0, "y": 0, "len": len(r), "sample": r})
        s["n"] += 1
        if len(r) >= 5:
            s["x"] = max(s["x"], r[1] | r[2] << 8)
            s["y"] = max(s["y"], r[3] | r[4] << 8)
        s["sample"] = r
    desc = "; ".join(f"id {k}: n={v['n']} max x={v['x']} y={v['y']} len={v['len']} e.g. {v['sample'].hex(' ')}"
                     for k, v in sorted(seen.items())) or "no reports"
    print(f"{label:28s} accepted={ok}  {desc}", flush=True)
tab.close()
print("\nDone - please unplug and replug the tablet to reset it.")
