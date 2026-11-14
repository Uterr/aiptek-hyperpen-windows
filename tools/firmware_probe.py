"""Probe firmware settings: which resolution codes (cmd 0x18) change the reported active area.

Stop the driver/tray app first.  python tools/firmware_probe.py
"""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import tablet_io

tab = tablet_io.open_tablet()
if not tab:
    sys.exit("tablet not found (or busy - stop the driver first)")
print("backend", tab.kind, f"{tab.vid:04X}:{tab.pid:04X}")
for name, c, d in (("model", 0x02, 0), ("odm", 0x03, 0), ("firmware", 0x04, 0), ("pressure levels", 0x08, 0)):
    v = tablet_io.query(tab, c, d)
    print(f"{name:16s} {v if v is None else hex(v)}")
for res in range(0, 0x0D):
    ok = tab.command(0x18, res)
    x, y = tablet_io.query(tab, 0x01, 0x00), tablet_io.query(tab, 0x01, 0x01)
    print(f"0x18 0x{res:02X}: accepted={ok}  extent x={x} y={y}")
tablet_io.set_mode(tab, True)  # back to the normal 500 lpi tablet mode
tab.close()
