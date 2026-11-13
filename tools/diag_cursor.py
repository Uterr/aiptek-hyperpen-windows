"""Tablet mode WITHOUT injection: does Windows move the cursor by itself? Logs raw pen vs cursor.

Useful on the stock HID driver to see Windows' own pen handling (this is how the double-input problem was found).
Stop the driver/tray app first.  python tools/diag_cursor.py [seconds]
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes, threading, time
from ctypes import wintypes as wt
import aiptek_driver as drv
import tablet_io

drv.make_dpi_aware()
secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15
tab = tablet_io.open_tablet()
if not tab:
    sys.exit("tablet not found (or busy - stop the driver first)")
tablet_io.set_mode(tab, True)
latest = [None]


def reader():
    try:
        while True:
            r = tab.read()
            if r:
                latest[0] = drv.parse_report(r)
    except OSError:
        pass


threading.Thread(target=reader, daemon=True).start()
pt = wt.POINT()
last = None
t_end = time.time() + secs
while time.time() < t_end:
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    cur = (pt.x, pt.y)
    if cur != last and latest[0]:
        x, y, st, p = latest[0]
        print(f"raw x={x:5d} y={y:5d} st={st:02x}  cursor={cur}")
        last = cur
    time.sleep(0.1)
if tab.kind == "HID":
    tablet_io.set_mode(tab, False)
    print("done, mouse mode restored")
