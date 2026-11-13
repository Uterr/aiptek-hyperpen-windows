"""Bind the tablet to Microsoft's inbox WinUSB driver (or give it back to Windows' HID driver).

  python winusb_install.py --list       show which drivers Windows would offer (no changes, no admin)
  python winusb_install.py --install    switch the tablet to WinUSB      (asks for admin)
  python winusb_install.py --restore    switch the tablet back to HID    (asks for admin)

--restore removes the device node and rescans, so Windows re-picks its default (HID) driver.
"""
import ctypes, os, sys
from ctypes import wintypes as wt

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
newdev = ctypes.WinDLL("newdev", use_last_error=True)
cfgmgr = ctypes.WinDLL("cfgmgr32")

from tablet_io import id_of_path  # supported USB IDs
DIGCF_PRESENT, DIGCF_ALLCLASSES = 0x2, 0x4
DI_ENUMSINGLEINF = 0x00010000
DI_FLAGSEX_ALLOWEXCLUDEDDRVS = 0x00000800
SPDIT_CLASSDRIVER, SPDIT_COMPATDRIVER = 1, 2
SPDRP_CLASSGUID = 0x8
USBDEVICE_CLASS = "{88BAE032-5A81-49F0-BC3D-A4FF138216D6}"


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("ClassGuid", GUID), ("DevInst", wt.DWORD), ("Reserved", ctypes.c_size_t)]


class SP_DEVINSTALL_PARAMS_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("Flags", wt.DWORD), ("FlagsEx", wt.DWORD), ("hwndParent", wt.HWND),
                ("InstallMsgHandler", ctypes.c_void_p), ("InstallMsgHandlerContext", ctypes.c_void_p),
                ("FileQueue", wt.HANDLE), ("ClassInstallReserved", ctypes.c_size_t), ("Reserved", wt.DWORD),
                ("DriverPath", wt.WCHAR * 260)]


class SP_DRVINFO_DATA_V2_W(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("DriverType", wt.DWORD), ("Reserved", ctypes.c_size_t),
                ("Description", wt.WCHAR * 256), ("MfgName", wt.WCHAR * 256), ("ProviderName", wt.WCHAR * 256),
                ("DriverDate", wt.FILETIME), ("DriverVersion", ctypes.c_uint64)]


setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.HWND, wt.DWORD]
for f in ("SetupDiEnumDeviceInfo", "SetupDiGetDeviceInstanceIdW", "SetupDiGetDeviceInstallParamsW",
          "SetupDiSetDeviceInstallParamsW", "SetupDiBuildDriverInfoList", "SetupDiEnumDriverInfoW",
          "SetupDiSetDeviceRegistryPropertyW", "SetupDiGetDeviceRegistryPropertyW", "SetupDiRemoveDevice",
          "SetupDiDestroyDeviceInfoList"):
    getattr(setupapi, f).restype = wt.BOOL
setupapi.SetupDiEnumDeviceInfo.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.LPWSTR, wt.DWORD,
                                                 ctypes.c_void_p]
setupapi.SetupDiGetDeviceInstallParamsW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA),
                                                    ctypes.POINTER(SP_DEVINSTALL_PARAMS_W)]
setupapi.SetupDiSetDeviceInstallParamsW.argtypes = setupapi.SetupDiGetDeviceInstallParamsW.argtypes
setupapi.SetupDiBuildDriverInfoList.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.DWORD]
setupapi.SetupDiEnumDriverInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.DWORD, wt.DWORD,
                                            ctypes.POINTER(SP_DRVINFO_DATA_V2_W)]
setupapi.SetupDiSetDeviceRegistryPropertyW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.DWORD,
                                                       ctypes.c_void_p, wt.DWORD]
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA), wt.DWORD,
                                                       ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p]
setupapi.SetupDiRemoveDevice.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA)]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
newdev.DiInstallDevice.restype = wt.BOOL
newdev.DiInstallDevice.argtypes = [wt.HWND, wt.HANDLE, ctypes.POINTER(SP_DEVINFO_DATA),
                                   ctypes.POINTER(SP_DRVINFO_DATA_V2_W), wt.DWORD, ctypes.POINTER(wt.BOOL)]


def err(msg):
    e = ctypes.get_last_error()
    raise SystemExit(f"{msg} failed: error {e & 0xFFFFFFFF:#x} {ctypes.FormatError(e) if e < 0x10000 else ''}")


def find_devices():
    """All present device nodes of the tablet (one per USB port it is plugged into). -> (hdi, [(dd, id)])"""
    hdi = setupapi.SetupDiGetClassDevsW(None, "USB", None, DIGCF_PRESENT | DIGCF_ALLCLASSES)
    found, i = [], 0
    while True:
        dd = SP_DEVINFO_DATA(cbSize=ctypes.sizeof(SP_DEVINFO_DATA))
        if not setupapi.SetupDiEnumDeviceInfo(hdi, i, ctypes.byref(dd)):
            break
        i += 1
        buf = ctypes.create_unicode_buffer(512)
        setupapi.SetupDiGetDeviceInstanceIdW(hdi, ctypes.byref(dd), buf, 512, None)
        if id_of_path(buf.value) and "&MI_" not in buf.value.upper():
            found.append((dd, buf.value))
    return hdi, found


def class_guid(hdi, dd):
    buf = ctypes.create_unicode_buffer(64)
    setupapi.SetupDiGetDeviceRegistryPropertyW(hdi, ctypes.byref(dd), SPDRP_CLASSGUID, None, buf, 128, None)
    return buf.value.upper()


def winusb_drivers(hdi, dd):
    """Driver entries from the inbox winusb.inf, offered for this device regardless of hardware-id match."""
    p = SP_DEVINSTALL_PARAMS_W(cbSize=ctypes.sizeof(SP_DEVINSTALL_PARAMS_W))
    setupapi.SetupDiGetDeviceInstallParamsW(hdi, ctypes.byref(dd), ctypes.byref(p)) or err("GetDeviceInstallParams")
    p.Flags |= DI_ENUMSINGLEINF
    p.FlagsEx |= DI_FLAGSEX_ALLOWEXCLUDEDDRVS
    p.DriverPath = os.path.join(os.environ["WINDIR"], "INF", "winusb.inf")
    setupapi.SetupDiSetDeviceInstallParamsW(hdi, ctypes.byref(dd), ctypes.byref(p)) or err("SetDeviceInstallParams")
    setupapi.SetupDiBuildDriverInfoList(hdi, ctypes.byref(dd), SPDIT_CLASSDRIVER) or err("BuildDriverInfoList")
    out, i = [], 0
    while True:
        di = SP_DRVINFO_DATA_V2_W(cbSize=ctypes.sizeof(SP_DRVINFO_DATA_V2_W))
        if not setupapi.SetupDiEnumDriverInfoW(hdi, ctypes.byref(dd), SPDIT_CLASSDRIVER, i, ctypes.byref(di)):
            break
        out.append(di)
        i += 1
    return out


def status():
    """[(instance id, on_winusb)] for the tablet's present device nodes. No admin needed."""
    hdi, devs = find_devices()
    try:
        return [(inst, class_guid(hdi, dd) == USBDEVICE_CLASS) for dd, inst in devs]
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdi)


def install_one(hdi, dd):
    old_class = class_guid(hdi, dd)

    def set_class(g):
        v = ctypes.create_unicode_buffer(g)
        return setupapi.SetupDiSetDeviceRegistryPropertyW(hdi, ctypes.byref(dd), SPDRP_CLASSGUID, v, ctypes.sizeof(v))

    # the inbox WinUSB entry belongs to the "USB devices" class; move the node there first
    if old_class != USBDEVICE_CLASS and not set_class(USBDEVICE_CLASS):
        err("Set class")
    try:
        drivers = [d for d in winusb_drivers(hdi, dd) if "winusb" in d.Description.lower()]
        if not drivers:
            raise SystemExit("WinUSB driver entry not found in winusb.inf")
        reboot = wt.BOOL()
        newdev.DiInstallDevice(None, hdi, ctypes.byref(dd), ctypes.byref(drivers[0]), 0,
                               ctypes.byref(reboot)) or err("DiInstallDevice")
        return bool(reboot.value)
    except BaseException:
        if old_class != USBDEVICE_CLASS:
            set_class(old_class)
            print("Install failed; device class restored.")
        raise


def install_all():
    """Bind every connected tablet node that isn't on WinUSB yet. Needs admin. -> list of messages."""
    hdi, devs = find_devices()
    if not devs:
        raise SystemExit("No supported tablet found - is it plugged in?")
    msgs = []
    try:
        for dd, inst in devs:
            if class_guid(hdi, dd) == USBDEVICE_CLASS:
                msgs.append(f"{inst}: already on WinUSB")
                continue
            reboot = install_one(hdi, dd)
            msgs.append(f"{inst}: now on WinUSB" + (" (reboot required)" if reboot else ""))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdi)
    return msgs


def restore_all():
    """Give every connected tablet node back to Windows' default (HID) driver. Needs admin."""
    hdi, devs = find_devices()
    msgs = []
    try:
        for dd, inst in devs:
            if class_guid(hdi, dd) != USBDEVICE_CLASS:
                msgs.append(f"{inst}: already on the Windows driver")
                continue
            setupapi.SetupDiRemoveDevice(hdi, ctypes.byref(dd)) or err("RemoveDevice")
            msgs.append(f"{inst}: removed, Windows will reinstall its default driver")
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(hdi)
    devinst = wt.DWORD()
    cfgmgr.CM_Locate_DevNodeW(ctypes.byref(devinst), None, 0)
    cfgmgr.CM_Reenumerate_DevNode(devinst, 0)
    return msgs


def is_admin():
    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def elevate():
    script = os.path.abspath(__file__)
    params = f'"{script}" {" ".join(sys.argv[1:])} --pause'
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, os.path.dirname(script), 1)
    print("Asked Windows for admin rights (UAC prompt)..." if r > 32 else "Elevation was cancelled.")


def main():
    args = set(sys.argv[1:])
    if "--list" in args:
        for inst, ok in status():
            print(f"{inst}: {'WinUSB' if ok else 'Windows HID driver'}")
        return
    if not is_admin():
        return elevate()
    if "--install" in args:
        print("\n".join(install_all()))
    elif "--restore" in args:
        print("\n".join(restore_all()))
        print("If the tablet doesn't come back as a mouse, unplug and replug it.")


if __name__ == "__main__":
    try:
        main()
    finally:
        if "--pause" in sys.argv:
            input("\nPress Enter to close...")
