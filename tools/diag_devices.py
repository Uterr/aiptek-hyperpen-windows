"""List Windows pointer devices and the display each is mapped to; re-run the hover injection test."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes, time, types
from ctypes import wintypes as wt
import aiptek_driver as drv

user32 = ctypes.WinDLL("user32", use_last_error=True)


class POINTER_DEVICE_INFO(ctypes.Structure):
    _fields_ = [("displayOrientation", wt.DWORD), ("device", wt.HANDLE), ("pointerDeviceType", wt.DWORD),
                ("monitor", wt.HANDLE), ("startingCursorId", wt.ULONG), ("maxActiveContacts", wt.USHORT),
                ("productString", wt.WCHAR * 520)]


drv.make_dpi_aware()
d = drv.Driver(types.SimpleNamespace(mouse=False, verbose=False))


def dump():
    n = ctypes.c_uint32(0)
    user32.GetPointerDevices(ctypes.byref(n), None)
    arr = (POINTER_DEVICE_INFO * max(n.value, 1))()
    user32.GetPointerDevices(ctypes.byref(n), arr)
    for i in range(n.value):
        p = arr[i]
        dr, sr = wt.RECT(), wt.RECT()
        user32.GetPointerDeviceRects(p.device, ctypes.byref(dr), ctypes.byref(sr))
        mi = drv.MONITORINFOEXW(cbSize=ctypes.sizeof(drv.MONITORINFOEXW))
        user32.GetMonitorInfoW(p.monitor, ctypes.byref(mi))
        print(f"  type={p.pointerDeviceType} dev={p.device} '{p.productString}' monitor={mi.szDevice} "
              f"deviceRect=({dr.left},{dr.top},{dr.right},{dr.bottom}) displayRect=({sr.left},{sr.top},{sr.right},{sr.bottom})")


pt = wt.POINT()
results = []
for target in [(100, 100), (960, 540), (960, 1300), (1800, 2200)]:
    for i in range(5):
        d.inject_pen(drv.PF_INRANGE | drv.PF_UPDATE, (target[0] + i, target[1]), 0)
        time.sleep(0.03)
    time.sleep(0.2)
    user32.GetCursorPos(ctypes.byref(pt))
    results.append(f"injected {target} -> cursor ({pt.x}, {pt.y})")
print(f"our synthetic device handle: {d.pen_dev}")
print("pointer devices:")
dump()
d.inject_pen(drv.PF_UPDATE, target, 0)
print("\n".join(results))
