"""Dump the HID collections / report layout of the Aiptek tablet."""
import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))  # repo root
import ctypes
from hidwin import *

KIND = {HidP_Input: "IN", HidP_Feature: "FEAT", HidP_Output: "OUT"}

for p in find_aiptek():
    print("=" * 80)
    print(p)
    h = open_path(p)
    mode = "rw"
    if h is None:
        h = open_path(p, 0)
        mode = "0-access"
    if h is None:
        print("  cannot open, err", ctypes.get_last_error())
        continue
    c, vals, btns = caps(h)
    print(f"  opened {mode}; TLC usage page 0x{c.UsagePage:02x} usage 0x{c.Usage:02x}; "
          f"in={c.InputReportByteLength} out={c.OutputReportByteLength} feat={c.FeatureReportByteLength}")
    for k in (HidP_Input, HidP_Feature, HidP_Output):
        for v in vals[k]:
            u = v.u.Range.UsageMin
            print(f"  {KIND[k]:4} VAL  rid={v.ReportID} page=0x{v.UsagePage:02x} usage=0x{u:02x}"
                  f"{'-0x%02x' % v.u.Range.UsageMax if v.IsRange else ''} bits={v.BitSize}x{v.ReportCount} "
                  f"logical={v.LogicalMin}..{v.LogicalMax} phys={v.PhysicalMin}..{v.PhysicalMax} abs={v.IsAbsolute} "
                  f"link=0x{v.LinkUsagePage:02x}/0x{v.LinkUsage:02x}")
        for b in btns[k]:
            r = b.u.Range
            print(f"  {KIND[k]:4} BTN  rid={b.ReportID} page=0x{b.UsagePage:02x} usage=0x{r.UsageMin:02x}"
                  f"{'-0x%02x' % r.UsageMax if b.IsRange else ''} link=0x{b.LinkUsagePage:02x}/0x{b.LinkUsage:02x}")
    kernel32.CloseHandle(h)
