"""Talk to the tablet either through WinUSB (preferred: Windows itself no longer sees it as a mouse/pen)
or through the Windows HID driver (fallback, if the device is still on its stock driver).

Both backends expose: read() -> bytes | None (None = timeout), command(c, d) -> bool, close().
They raise OSError when the tablet goes away.
"""
import ctypes, time
from ctypes import wintypes as wt
import hidwin
from hidwin import kernel32, hid, GUID, open_path, GENERIC_READ, GENERIC_WRITE, FILE_FLAG_OVERLAPPED

# USB IDs handled by the Linux aiptek driver (same protocol family). Only 08CA:0010 (HyperPen 12000U) is tested.
DEVICE_IDS = [(0x08CA, 0x0001), (0x08CA, 0x0010), (0x08CA, 0x0020), (0x08CA, 0x0021), (0x08CA, 0x0022),
              (0x08CA, 0x0023), (0x08CA, 0x0024), (0x0458, 0x5003)]


def id_of_path(path):
    """(vid, pid) if a device path belongs to a supported tablet, else None."""
    p = path.lower()
    for vid, pid in DEVICE_IDS:
        if f"vid_{vid:04x}&pid_{pid:04x}" in p:
            return vid, pid
    return None
winusb = ctypes.WinDLL("winusb", use_last_error=True)
GUID_DEVINTERFACE_USB_DEVICE = GUID(0xA5DCBF10, 0x6530, 0x11D2, (ctypes.c_ubyte * 8)(0x90, 0x1F, 0x00, 0xC0, 0x4F, 0xB9, 0x51, 0xED))
ERROR_SEM_TIMEOUT = 121
PIPE_TRANSFER_TIMEOUT = 0x03


class USB_INTERFACE_DESCRIPTOR(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("bLength", ctypes.c_ubyte), ("bDescriptorType", ctypes.c_ubyte), ("bInterfaceNumber", ctypes.c_ubyte),
                ("bAlternateSetting", ctypes.c_ubyte), ("bNumEndpoints", ctypes.c_ubyte),
                ("bInterfaceClass", ctypes.c_ubyte), ("bInterfaceSubClass", ctypes.c_ubyte),
                ("bInterfaceProtocol", ctypes.c_ubyte), ("iInterface", ctypes.c_ubyte)]


class WINUSB_PIPE_INFORMATION(ctypes.Structure):
    _fields_ = [("PipeType", ctypes.c_int), ("PipeId", ctypes.c_ubyte), ("MaximumPacketSize", wt.USHORT),
                ("Interval", ctypes.c_ubyte)]


class WINUSB_SETUP_PACKET(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("RequestType", ctypes.c_ubyte), ("Request", ctypes.c_ubyte), ("Value", wt.USHORT),
                ("Index", wt.USHORT), ("Length", wt.USHORT)]


for f in ("WinUsb_Initialize", "WinUsb_Free", "WinUsb_QueryInterfaceSettings", "WinUsb_QueryPipe",
          "WinUsb_SetPipePolicy", "WinUsb_ReadPipe", "WinUsb_ControlTransfer", "WinUsb_FlushPipe"):
    getattr(winusb, f).restype = wt.BOOL
winusb.WinUsb_Initialize.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
winusb.WinUsb_Free.argtypes = [ctypes.c_void_p]
winusb.WinUsb_QueryInterfaceSettings.argtypes = [ctypes.c_void_p, ctypes.c_ubyte,
                                                 ctypes.POINTER(USB_INTERFACE_DESCRIPTOR)]
winusb.WinUsb_QueryPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_ubyte,
                                    ctypes.POINTER(WINUSB_PIPE_INFORMATION)]
winusb.WinUsb_SetPipePolicy.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, wt.ULONG, wt.ULONG, ctypes.c_void_p]
winusb.WinUsb_ReadPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte, ctypes.c_void_p, wt.ULONG,
                                   ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
winusb.WinUsb_ControlTransfer.argtypes = [ctypes.c_void_p, WINUSB_SETUP_PACKET, ctypes.c_void_p, wt.ULONG,
                                          ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
winusb.WinUsb_FlushPipe.argtypes = [ctypes.c_void_p, ctypes.c_ubyte]


class WinUsbTablet:
    kind = "WinUSB"

    def __init__(self, path):
        self.file = kernel32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, 3, None, 3, FILE_FLAG_OVERLAPPED, None)
        if not self.file or self.file == hidwin.INVALID_HANDLE_VALUE:
            raise OSError(ctypes.get_last_error(), "CreateFile (device busy or not on WinUSB)")
        self.h = ctypes.c_void_p()
        if not winusb.WinUsb_Initialize(self.file, ctypes.byref(self.h)):
            e = ctypes.get_last_error()
            kernel32.CloseHandle(self.file)
            raise OSError(e, "WinUsb_Initialize")
        idesc = USB_INTERFACE_DESCRIPTOR()
        winusb.WinUsb_QueryInterfaceSettings(self.h, 0, ctypes.byref(idesc))
        self.iface = idesc.bInterfaceNumber
        self.pipe, self.size = None, 8
        for i in range(idesc.bNumEndpoints):
            pi = WINUSB_PIPE_INFORMATION()
            if winusb.WinUsb_QueryPipe(self.h, 0, i, ctypes.byref(pi)) and pi.PipeId & 0x80 and pi.PipeType == 3:
                self.pipe, self.size = pi.PipeId, max(pi.MaximumPacketSize, 8)
                break
        if self.pipe is None:
            self.close()
            raise OSError(0, "no interrupt IN endpoint")
        timeout = wt.ULONG(500)
        winusb.WinUsb_SetPipePolicy(self.h, self.pipe, PIPE_TRANSFER_TIMEOUT, 4, ctypes.byref(timeout))
        winusb.WinUsb_FlushPipe(self.h, self.pipe)
        self.buf = (ctypes.c_ubyte * self.size)()

    def read(self):
        n = wt.ULONG()
        if winusb.WinUsb_ReadPipe(self.h, self.pipe, self.buf, self.size, ctypes.byref(n), None):
            return bytes(self.buf[:n.value])
        e = ctypes.get_last_error()
        if e == ERROR_SEM_TIMEOUT:
            return None
        raise OSError(e, "WinUsb_ReadPipe")

    def command(self, c, d):
        # HID SET_REPORT(Feature, id 2) = class request to the interface, exactly what Linux aiptek.c sends
        data = (ctypes.c_ubyte * 3)(2, c, d)
        setup = WINUSB_SETUP_PACKET(0x21, 0x09, (3 << 8) | 2, self.iface, 3)
        n = wt.ULONG()
        return bool(winusb.WinUsb_ControlTransfer(self.h, setup, data, 3, ctypes.byref(n), None))

    def get_feature(self):
        # HID GET_REPORT(Feature, id 2)
        data = (ctypes.c_ubyte * 3)()
        setup = WINUSB_SETUP_PACKET(0xA1, 0x01, (3 << 8) | 2, self.iface, 3)
        n = wt.ULONG()
        if winusb.WinUsb_ControlTransfer(self.h, setup, data, 3, ctypes.byref(n), None) and n.value >= 3:
            return bytes(data)
        return None

    def close(self):
        if self.h:
            winusb.WinUsb_Free(self.h)
            self.h = None
        if self.file:
            kernel32.CloseHandle(self.file)
            self.file = None


class HidTablet:
    kind = "HID"

    def __init__(self, path):
        self.rd, self.cmd = open_path(path), open_path(path)
        if not self.rd or not self.cmd:
            self.close()
            raise OSError(ctypes.get_last_error(), "open HID")
        hid.HidD_SetNumInputBuffers(self.rd, 64)
        self.buf = (ctypes.c_ubyte * 8)()

    def read(self):
        n = wt.DWORD()
        if kernel32.ReadFile(self.rd, self.buf, 8, ctypes.byref(n), None):
            return bytes(self.buf[:n.value])
        raise OSError(ctypes.get_last_error(), "ReadFile")

    def command(self, c, d):
        return bool(hid.HidD_SetFeature(self.cmd, (ctypes.c_ubyte * 3)(2, c, d), 3))

    def get_feature(self):
        buf = (ctypes.c_ubyte * 3)(2, 0, 0)
        return bytes(buf) if hid.HidD_GetFeature(self.cmd, buf, 3) else None

    def close(self):
        for a in ("rd", "cmd"):
            h = getattr(self, a, None)
            if h:
                kernel32.CloseHandle(h)
                setattr(self, a, None)


# cmd 0x18 resolution codes (HyperPen 12000U; probed with tools/firmware_probe.py). 0x04 is what Linux uses.
# NOTE: switching to tablet mode (0x10 0x01) resets the resolution to 500 lpi, so 0x18 must come AFTER 0x10.
RESOLUTION_CODES = {500: 0x04, 1000: 0x06, 2000: 0x08, 3048: 0x0C}


def set_mode(tab, absolute, res_code=None):
    """Tablet/mouse mode, then resolution, macro keys on, auto gain on."""
    res_code = getattr(tab, "res_code", 0x04) if res_code is None else res_code
    for c, d in ((0x10, 0x01 if absolute else 0x00), (0x18, res_code), (0x11, 0x02), (0x12, 0xFF)):
        if not tab.command(c, d):
            return False
        time.sleep(0.02)
    return True


def query(tab, c, d, delay=0.4):
    """Linux aiptek_query(): send a command, wait, read the 16-bit answer from feature report 2."""
    if not tab.command(c, d):
        return None
    time.sleep(delay)
    r = tab.get_feature()
    return (r[1] | r[2] << 8) if r and r[0] == 2 else None


def query_size(tab, res_code=0x04):
    """(max x, max y) of the active area at the given resolution, or None if the tablet doesn't answer sensibly."""
    tab.command(0x18, res_code)
    x, y = query(tab, 0x01, 0x00), query(tab, 0x01, 0x01)
    if x and y and 500 <= x <= 65535 and 500 <= y <= 65535:
        return x, y
    return None


def setup_resolution(tab, lpi):
    """Pick the finest working resolution <= lpi. Returns (size at 500 lpi, scale = raw units per 500-lpi unit).

    The scale is measured from the reported extents, not assumed, so a model that ignores a code falls back to
    500 lpi. Call set_mode() afterwards: it applies tab.res_code after the mode switch.
    """
    base = query_size(tab, 0x04)
    tab.res_code, scale = 0x04, 1.0
    for want in sorted((v for v in RESOLUTION_CODES if 500 < v <= lpi), reverse=True):
        hi = query_size(tab, RESOLUTION_CODES[want])
        if base and hi:
            sx, sy = hi[0] / base[0], hi[1] / base[1]
            if sx > 1.05 and abs(sx - sy) / sx < 0.02:
                tab.res_code, scale = RESOLUTION_CODES[want], sx
                break
    tab.scale = scale
    return base, scale


def _digitizer_collection(path):
    """The HID collection that carries the stylus reports (usage page Digitizer)."""
    h = open_path(path, 0)
    if not h:
        return False
    try:
        c, _, _ = hidwin.caps(h)
        return bool(c) and c.UsagePage == 0x0D
    finally:
        kernel32.CloseHandle(h)


def open_tablet():
    """Open the first supported tablet: via WinUSB if bound to WinUSB, else via HID. None if not available."""
    for p in hidwin.enumerate_paths(GUID_DEVINTERFACE_USB_DEVICE):
        ids = id_of_path(p)
        if ids:
            try:
                t = WinUsbTablet(p)
                t.vid, t.pid = ids
                return t
            except OSError:
                pass  # present but not on WinUSB (or busy) -> try HID
    for p in hidwin.enumerate_paths():
        ids = id_of_path(p)
        if ids and _digitizer_collection(p):
            try:
                t = HidTablet(p)
                t.vid, t.pid = ids
                return t
            except OSError:
                pass
    return None
