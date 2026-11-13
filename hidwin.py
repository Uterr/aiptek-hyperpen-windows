"""Minimal ctypes wrapper around Windows SetupAPI / hid.dll (no third-party deps)."""
import ctypes
from ctypes import wintypes as wt

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 1
FILE_SHARE_WRITE = 2
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
DIGCF_PRESENT = 2
DIGCF_DEVICEINTERFACE = 0x10
HIDP_STATUS_SUCCESS = 0x00110000
HidP_Input, HidP_Output, HidP_Feature = 0, 1, 2


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
                ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
                ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17)] + \
               [(n, wt.USHORT) for n in ("NumberLinkCollectionNodes", "NumberInputButtonCaps", "NumberInputValueCaps",
                                         "NumberInputDataIndices", "NumberOutputButtonCaps", "NumberOutputValueCaps",
                                         "NumberOutputDataIndices", "NumberFeatureButtonCaps", "NumberFeatureValueCaps",
                                         "NumberFeatureDataIndices")]


class _Range(ctypes.Structure):
    _fields_ = [("UsageMin", wt.USHORT), ("UsageMax", wt.USHORT), ("StringMin", wt.USHORT), ("StringMax", wt.USHORT),
                ("DesignatorMin", wt.USHORT), ("DesignatorMax", wt.USHORT), ("DataIndexMin", wt.USHORT),
                ("DataIndexMax", wt.USHORT)]


class _U(ctypes.Union):
    _fields_ = [("Range", _Range)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wt.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wt.USHORT), ("LinkCollection", wt.USHORT), ("LinkUsage", wt.USHORT),
                ("LinkUsagePage", wt.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte), ("HasNull", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte), ("BitSize", wt.USHORT), ("ReportCount", wt.USHORT),
                ("Reserved2", wt.USHORT * 5), ("UnitsExp", wt.ULONG), ("Units", wt.ULONG),
                ("LogicalMin", wt.LONG), ("LogicalMax", wt.LONG), ("PhysicalMin", wt.LONG), ("PhysicalMax", wt.LONG),
                ("u", _U)]


class HIDP_BUTTON_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wt.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wt.USHORT), ("LinkCollection", wt.USHORT), ("LinkUsage", wt.USHORT),
                ("LinkUsagePage", wt.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte), ("ReportCount", wt.USHORT),
                ("Reserved2", wt.USHORT), ("Reserved", wt.ULONG * 9), ("u", _U)]


setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                                      ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
for f in ("HidD_GetAttributes", "HidD_GetPreparsedData", "HidD_FreePreparsedData", "HidD_SetFeature",
          "HidD_GetFeature", "HidD_SetOutputReport", "HidD_GetInputReport", "HidD_SetNumInputBuffers"):
    getattr(hid, f).restype = wt.BOOLEAN
hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_SetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_SetOutputReport.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetInputReport.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_SetNumInputBuffers.argtypes = [wt.HANDLE, wt.ULONG]
hid.HidP_GetCaps.restype = wt.LONG
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetValueCaps.restype = wt.LONG
hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.USHORT), ctypes.c_void_p]
hid.HidP_GetButtonCaps.restype = wt.LONG
hid.HidP_GetButtonCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.USHORT), ctypes.c_void_p]


def hid_guid():
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    return g


def enumerate_paths(g=None):
    g = g or hid_guid()
    h = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    paths = []
    i = 0
    while True:
        d = SP_DEVICE_INTERFACE_DATA()
        d.cbSize = ctypes.sizeof(d)
        if not setupapi.SetupDiEnumDeviceInterfaces(h, None, ctypes.byref(g), i, ctypes.byref(d)):
            break
        i += 1
        need = wt.DWORD()
        setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), None, 0, ctypes.byref(need), None)
        buf = ctypes.create_string_buffer(need.value)
        ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        if setupapi.SetupDiGetDeviceInterfaceDetailW(h, ctypes.byref(d), buf, need, None, None):
            paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    setupapi.SetupDiDestroyDeviceInfoList(h)
    return paths


def open_path(path, access=GENERIC_READ | GENERIC_WRITE, flags=0):
    h = kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, flags, None)
    if h == INVALID_HANDLE_VALUE or h is None:
        return None
    return h


def caps(h):
    pp = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
        return None, None, None
    c = HIDP_CAPS()
    hid.HidP_GetCaps(pp, ctypes.byref(c))
    vals, btns = {}, {}
    for kind, n_v, n_b in ((HidP_Input, c.NumberInputValueCaps, c.NumberInputButtonCaps),
                           (HidP_Feature, c.NumberFeatureValueCaps, c.NumberFeatureButtonCaps),
                           (HidP_Output, c.NumberOutputValueCaps, c.NumberOutputButtonCaps)):
        n = wt.USHORT(n_v)
        arr = (HIDP_VALUE_CAPS * max(n_v, 1))()
        if n_v:
            hid.HidP_GetValueCaps(kind, arr, ctypes.byref(n), pp)
        vals[kind] = list(arr)[:n.value] if n_v else []
        n = wt.USHORT(n_b)
        arr = (HIDP_BUTTON_CAPS * max(n_b, 1))()
        if n_b:
            hid.HidP_GetButtonCaps(kind, arr, ctypes.byref(n), pp)
        btns[kind] = list(arr)[:n.value] if n_b else []
    hid.HidD_FreePreparsedData(pp)
    return c, vals, btns


def find_aiptek(vid=0x08CA, pid=0x0010):
    out = []
    for p in enumerate_paths():
        if f"vid_{vid:04x}&pid_{pid:04x}" not in p.lower():
            continue
        out.append(p)
    return out
