"""Try the Linux aiptek query protocol (command via feature 2, answer via feature 3)."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes, time
from hidwin import *

h = open_path(next(p for p in find_aiptek() if "col03" in p.lower()))


def query(c, d):
    hid.HidD_SetFeature(h, (ctypes.c_ubyte * 3)(2, c, d), 3)
    time.sleep(0.4)
    for rid in (3, 2):
        buf = (ctypes.c_ubyte * 3)(rid, 0, 0)
        if hid.HidD_GetFeature(h, buf, 3):
            return rid, bytes(buf).hex(" ")
    return None, "err %d" % ctypes.get_last_error()


hid.HidD_SetFeature(h, (ctypes.c_ubyte * 3)(2, 0x18, 0x04), 3)
for name, c, d in (("model", 0x02, 0), ("odm", 0x03, 0), ("firmware", 0x04, 0), ("xext", 0x01, 0), ("yext", 0x01, 1),
                   ("pressure", 0x08, 0)):
    print(name, query(c, d))
hid.HidD_SetFeature(h, (ctypes.c_ubyte * 3)(2, 0x10, 0x01), 3)
