"""Inject synthetic pen HOVER (no contact) at known points and read back where Windows puts the cursor."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes, time, types
from ctypes import wintypes as wt
import aiptek_driver as drv

drv.make_dpi_aware()
d = drv.Driver(types.SimpleNamespace(mouse=False, verbose=True))
pt = wt.POINT()
for target in [(100, 100), (960, 540), (1800, 1000), (100, -1100), (960, -600), (1800, -100)]:
    for i in range(5):
        d.inject_pen(drv.PF_INRANGE | drv.PF_UPDATE, (target[0] + i, target[1]), 0)
        time.sleep(0.03)
    time.sleep(0.2)
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    print(f"injected {target} -> cursor ({pt.x}, {pt.y})")
d.inject_pen(drv.PF_UPDATE, target, 0)
