"""Switch the tablet to absolute mode and dump raw reports for N seconds."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes, sys, threading, time
from ctypes import wintypes as wt
from hidwin import *

secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15
path = next(p for p in find_aiptek() if "col03" in p.lower())
h = open_path(path)


def cmd(c, d):
    buf = (ctypes.c_ubyte * 3)(2, c, d)
    ok = hid.HidD_SetFeature(h, buf, 3)
    print(f"cmd 0x{c:02x},0x{d:02x} -> {'ok' if ok else 'FAIL err %d' % ctypes.get_last_error()}")
    time.sleep(0.05)


cmd(0x18, 0x04)  # resolution 500 lpi
cmd(0x10, 0x01)  # switch to tablet (absolute)
cmd(0x11, 0x02)  # enable macro keys
cmd(0x12, 0xFF)  # auto gain on

stats = {}
def reader():
    buf = (ctypes.c_ubyte * 8)()
    n = wt.DWORD()
    last = None
    while kernel32.ReadFile(h, buf, 8, ctypes.byref(n), None):
        b = bytes(buf[:n.value])
        stats.setdefault(b[0], [0, 65535, 0, 65535, 0, 0])
        if b[0] == 2:
            x, y, z = int.from_bytes(b[1:3], "little"), int.from_bytes(b[3:5], "little"), int.from_bytes(b[6:8], "little")
            s = stats[2]
            s[0] = max(s[0], x); s[1] = min(s[1], x); s[2] = max(s[2], y); s[3] = min(s[3], y); s[4] = max(s[4], z)
        stats[b[0]][5] += 1
        if b[5:6] != last or stats[b[0]][5] % 25 == 0:
            print(b.hex(" "))
            last = b[5:6]

threading.Thread(target=reader, daemon=True).start()
time.sleep(secs)
print("report counts/ranges:", {k: v for k, v in stats.items()})
