"""User-mode driver for the Aiptek HyperPen 12000U on Windows 10/11.

Switches the tablet from relative "mouse mode" to absolute "tablet mode", reads the
stylus reports and injects them into Windows as a real pen (with pressure) via
InjectSyntheticPointerInput. On exit the tablet is put back into mouse mode.

Settings live in %APPDATA%\\AiptekTablet\\config.json; edit them with the setup window
(python aiptek_setup.py, or Settings in the tray app) -- the running driver picks changes up live.

Usage:  python aiptek_driver.py [--mouse] [--verbose]
"""
import argparse, ctypes, json, os, shutil, socket, sys, threading, time
from ctypes import wintypes as wt
from hidwin import kernel32
import tablet_io
from tablet_io import set_mode

user32 = ctypes.WinDLL("user32", use_last_error=True)
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(os.environ.get("APPDATA", HERE), "AiptekTablet")
os.makedirs(APP_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "driver.log")
if not os.path.exists(CONFIG_PATH) and os.path.exists(os.path.join(HERE, "config.json")):
    shutil.copy(os.path.join(HERE, "config.json"), CONFIG_PATH)  # migrate settings from the source folder


def log(*a):
    msg = " ".join(str(x) for x in a)
    if sys.stdout:
        print(msg, flush=True)
    try:
        if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 512 * 1024:
            os.replace(LOG_PATH, LOG_PATH + ".old")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass
MUTEX_NAME = "Local\\AiptekHP12000UDriver"
MONITOR_PORT = 47812   # driver forwards raw pen reports to 127.0.0.1:this for the setup window

# ---------------------------------------------------------------- tablet protocol
TAB_W, TAB_H = 6000, 4500          # active area at 500 lpi (queried from the tablet)
PRESSURE_MAX = 1023
ST_INRANGE, ST_NEAR, ST_TIP, ST_BTN_LOWER, ST_BTN_UPPER = 0x01, 0x02, 0x04, 0x08, 0x10


def parse_report(r):
    """-> (x, y, status, pressure) for stylus report 2, else None."""
    if len(r) < 8 or r[0] != 2:
        return None
    return r[1] | r[2] << 8, r[3] | r[4] << 8, r[5], r[6] | r[7] << 8


# ---------------------------------------------------------------- config
DEFAULT_CONFIG = {
    "monitor": "",                 # monitor device name (e.g. "\\\\.\\DISPLAY1"); "" = primary
    "area": None,                  # [x0, y0, x1, y1] in tablet units; null = largest area with the screen's aspect
    "tablet_size": [TAB_W, TAB_H],
    "barrel": "right",             # side button: right | middle | none
    "smoothing": "off",            # off | light | medium | strong  (adaptive 1-euro filter)
    "coil_correction": True,
    # raw pressure range actually produced by the pen (tip-down starts ~70; the tablet has 512 levels)
    # curve: output = f ** curve  (<1 soft: easy to reach full pressure, >1 firm)
    "pressure": {"min": 60, "max": 400, "curve": 1.0},
    # periodic coil-pitch error of this tablet, fitted from ruler strokes (fit_calib.py)
    "calibration": {"period": 124.0, "harmonics": 2,
                    "x": [1.764, -4.118, -0.303, -0.545], "y": [2.512, -2.314, 0.247, -0.944]},
}

# 1-euro filter presets: (min cutoff Hz, speed coefficient). Lower cutoff = smoother when slow.
SMOOTHING = {"off": None, "light": (4.0, 0.02), "medium": (2.0, 0.01), "strong": (1.0, 0.006)}


class OneEuro:
    """Casiez et al. 1-euro filter: heavy smoothing at low speed, little lag at high speed."""

    def __init__(self, mincutoff, beta, dcutoff=1.0):
        self.mincutoff, self.beta, self.dcutoff = mincutoff, beta, dcutoff
        self.x = self.dx = self.t = None

    @staticmethod
    def _alpha(cutoff, dt):
        tau = 1.0 / (2 * 3.141592653589793 * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, v, t):
        if self.t is None:
            self.x, self.dx, self.t = v, 0.0, t
            return v
        dt = max(t - self.t, 1e-3)
        self.t = t
        dx = (v - self.x) / dt
        a_d = self._alpha(self.dcutoff, dt)
        self.dx = a_d * dx + (1 - a_d) * self.dx
        a = self._alpha(self.mincutoff + self.beta * abs(self.dx), dt)
        self.x = a * v + (1 - a) * self.x
        return self.x


def map_pressure(p, pc):
    """Raw tablet pressure -> 0..1 using the configured range and curve."""
    lo, hi = pc.get("min", 60), max(pc.get("max", 400), pc.get("min", 60) + 1)
    f = min(max((p - lo) / (hi - lo), 0.0), 1.0)
    return f ** pc.get("curve", 1.0)


def coil_correct(v, cal, axis):
    import math
    w = 2 * math.pi * v / cal["period"]
    c = cal[axis]
    return v + sum(c[2 * k] * math.sin((k + 1) * w) + c[2 * k + 1] * math.cos((k + 1) * w)
                   for k in range(cal["harmonics"]))


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg.update(json.load(f))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    for attempt in range(20):  # the driver may be reading the file at this instant
        try:
            os.replace(tmp, CONFIG_PATH)
            return
        except PermissionError:
            time.sleep(0.05)
    os.replace(tmp, CONFIG_PATH)


def max_area(tablet_size, aspect, align=(0.5, 0.5)):
    """Largest rectangle with the given aspect (w/h) fitting the tablet, positioned by align."""
    tw, th = tablet_size
    if tw / th > aspect:
        w, h = th * aspect, th
    else:
        w, h = tw, tw / aspect
    x0, y0 = (tw - w) * align[0], (th - h) * align[1]
    return [round(x0), round(y0), round(x0 + w), round(y0 + h)]


# ---------------------------------------------------------------- monitors
class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD),
                ("szDevice", wt.WCHAR * 32)]


MONITORENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)


def monitors():
    """[{name, rect(l,t,r,b) in physical pixels, primary}], primary first. Call after DPI awareness is set."""
    out = []

    def cb(hmon, hdc, rc, lp):
        mi = MONITORINFOEXW(cbSize=ctypes.sizeof(MONITORINFOEXW))
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        out.append({"name": mi.szDevice, "rect": (r.left, r.top, r.right, r.bottom), "primary": bool(mi.dwFlags & 1)})
        return True

    user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(cb), 0)
    out.sort(key=lambda m: (not m["primary"], m["rect"][0], m["rect"][1]))
    return out


def pick_monitor(name):
    mons = monitors()
    return next((m for m in mons if m["name"] == name), mons[0])


def make_dpi_aware():
    user32.SetProcessDpiAwarenessContext(wt.HANDLE(-4))  # per-monitor v2: physical pixel coordinates


# ---------------------------------------------------------------- pointer injection structs
PT_PEN = 3
POINTER_FEEDBACK_DEFAULT = 1
PF_INRANGE, PF_INCONTACT, PF_FIRSTBUTTON = 0x2, 0x4, 0x10
PF_DOWN, PF_UPDATE, PF_UP = 0x10000, 0x20000, 0x40000
PEN_FLAG_BARREL, PEN_MASK_PRESSURE = 0x1, 0x1
CHANGE_NONE, CHANGE_FIRST_DOWN, CHANGE_FIRST_UP = 0, 1, 2


class POINTER_INFO(ctypes.Structure):
    _fields_ = [("pointerType", wt.DWORD), ("pointerId", ctypes.c_uint32), ("frameId", ctypes.c_uint32),
                ("pointerFlags", ctypes.c_uint32), ("sourceDevice", wt.HANDLE), ("hwndTarget", wt.HWND),
                ("ptPixelLocation", wt.POINT), ("ptHimetricLocation", wt.POINT),
                ("ptPixelLocationRaw", wt.POINT), ("ptHimetricLocationRaw", wt.POINT),
                ("dwTime", wt.DWORD), ("historyCount", ctypes.c_uint32), ("InputData", ctypes.c_int32),
                ("dwKeyStates", wt.DWORD), ("PerformanceCount", ctypes.c_uint64), ("ButtonChangeType", ctypes.c_int)]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("penFlags", ctypes.c_uint32), ("penMask", ctypes.c_uint32),
                ("pressure", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("tiltX", ctypes.c_int32),
                ("tiltY", ctypes.c_int32)]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [("pointerInfo", POINTER_INFO), ("touchFlags", ctypes.c_uint32), ("touchMask", ctypes.c_uint32),
                ("rcContact", wt.RECT), ("rcContactRaw", wt.RECT), ("orientation", ctypes.c_uint32),
                ("pressure", ctypes.c_uint32)]


class _PTU(ctypes.Union):
    _fields_ = [("touchInfo", POINTER_TOUCH_INFO), ("penInfo", POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wt.DWORD), ("u", _PTU)]


user32.CreateSyntheticPointerDevice.restype = wt.HANDLE
user32.CreateSyntheticPointerDevice.argtypes = [wt.DWORD, ctypes.c_uint32, wt.DWORD]
user32.InjectSyntheticPointerInput.restype = wt.BOOL
user32.InjectSyntheticPointerInput.argtypes = [wt.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32]


# ---------------------------------------------------------------- mouse (SendInput)
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _I(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("_pad", ctypes.c_byte * 32)]
    _anonymous_ = ("i",)
    _fields_ = [("type", wt.DWORD), ("i", _I)]


MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x8000, 0x4000
MOUSE_BUTTONS = {"left": (0x2, 0x4), "right": (0x8, 0x10), "middle": (0x20, 0x40)}
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]


def send_mouse(flags, dx=0, dy=0):
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx, dy, 0, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


# ---------------------------------------------------------------- driver
class Driver:
    def __init__(self, args):
        self.a = args
        self.cfg = load_config()
        self.mapping = None
        self.recompute_mapping(announce=True)
        self.pen_dev = None if args.mouse else user32.CreateSyntheticPointerDevice(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
        if not args.mouse and not self.pen_dev:
            log("Pen injection unavailable (err %d); falling back to mouse mode" % ctypes.get_last_error())
            args.mouse = True
        self.in_range = self.down = self.button = False
        self.button_which = "none"
        self.last_xy = (0, 0)
        self.frame = 0
        self.pid = None
        self.make_filters()

    def recompute_mapping(self, announce=False):
        mon = pick_monitor(self.cfg["monitor"])
        sl, st, sr, sb = mon["rect"]
        area = self.cfg["area"] or max_area(self.cfg["tablet_size"], (sr - sl) / (sb - st))
        new = (tuple(area), mon["rect"])
        if new != self.mapping:
            self.mapping = new
            log(f"Mapping tablet area {list(area)} -> {mon['name']} {mon['rect']}")

    def set_tablet(self, vid, pid, size):
        """Adopt the connected model and its reported active area."""
        self.pid = pid
        if not size or list(size) == list(self.cfg.get("tablet_size", [])):
            return
        cfg = load_config()
        cfg["tablet_size"] = list(size)
        a = cfg.get("area")
        if a and (a[2] > size[0] or a[3] > size[1]):
            cfg["area"] = None  # doesn't fit this tablet: back to the largest area with the screen's shape
        save_config(cfg)
        self.cfg = cfg
        self.recompute_mapping()
        log(f"Tablet reports active area {size[0]}x{size[1]}; settings updated.")

    def make_filters(self):
        preset = SMOOTHING.get(self.cfg.get("smoothing"), None)
        self.filters = (OneEuro(*preset), OneEuro(*preset)) if preset else None

    def config_changed(self):
        self.cfg = load_config()
        self.recompute_mapping()
        self.make_filters()

    def refine(self, x, y, in_range):
        """Coil correction + smoothing in tablet units (float)."""
        if not in_range:
            if self.filters and self.filters[0].t is not None:
                self.make_filters()  # restart the filter on the next approach, no smear from the old position
            return x, y
        # the bundled calibration was measured on a HyperPen 12000U (08CA:0010)
        if self.cfg.get("coil_correction") and self.cfg.get("calibration") and self.pid == 0x0010:
            cal = self.cfg["calibration"]
            x, y = coil_correct(x, cal, "x"), coil_correct(y, cal, "y")
        if self.filters:
            t = time.perf_counter()
            x, y = self.filters[0](x, t), self.filters[1](y, t)
        return x, y

    def map(self, x, y):
        (x0, y0, x1, y1), (sl, st, sr, sb) = self.mapping
        fx = min(max((x - x0) / max(x1 - x0, 1), 0.0), 1.0)
        fy = min(max((y - y0) / max(y1 - y0, 1), 0.0), 1.0)
        return int(sl + fx * (sr - sl - 1) + 0.5), int(st + fy * (sb - st - 1) + 0.5)

    # ---- output back-ends
    def inject_pen(self, flags, xy, pressure, change=CHANGE_NONE):
        pti = POINTER_TYPE_INFO(type=PT_PEN)
        pi = pti.penInfo.pointerInfo
        pi.pointerType = PT_PEN
        self.frame += 1
        pi.frameId = self.frame
        pi.pointerFlags = flags
        # the synthetic pen spans the whole virtual desktop and Windows measures its coordinates from the
        # desktop's top-left corner (which is negative when a monitor sits above/left of the main one)
        pi.ptPixelLocation = wt.POINT(xy[0] - user32.GetSystemMetrics(76), xy[1] - user32.GetSystemMetrics(77))
        pi.ButtonChangeType = change
        pti.penInfo.penMask = PEN_MASK_PRESSURE
        pti.penInfo.pressure = pressure
        if not user32.InjectSyntheticPointerInput(self.pen_dev, ctypes.byref(pti), 1) and self.a.verbose:
            print("inject failed, err", ctypes.get_last_error(), hex(flags))

    @staticmethod
    def mouse_move(xy):
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        dx = int((xy[0] - vx) * 65535 / max(vw - 1, 1))
        dy = int((xy[1] - vy) * 65535 / max(vh - 1, 1))
        send_mouse(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, dx, dy)

    @staticmethod
    def mouse_button(which, press):
        if which in MOUSE_BUTTONS:
            send_mouse(MOUSE_BUTTONS[which][0 if press else 1])

    # ---- report handling
    def handle(self, r):
        rep = parse_report(r)
        if not rep:
            return
        x, y, st, p = rep
        in_range = bool(st & (ST_INRANGE | ST_NEAR | ST_TIP))
        tip = bool(st & ST_TIP)
        lower, upper = bool(st & ST_BTN_LOWER), bool(st & ST_BTN_UPPER)
        fx, fy = self.refine(x, y, in_range)
        xy = self.map(fx, fy) if in_range else self.last_xy
        pc = self.cfg.get("pressure") or DEFAULT_CONFIG["pressure"]
        pressure = max(1, round(1024 * map_pressure(p, pc))) if tip else 0
        if self.a.verbose:
            print(f"{r.hex(' ')}  -> {xy} tip={tip} p={pressure} btn={lower}{upper}")

        # side buttons -> mouse clicks (pressure reads garbage while they are held)
        btn = lower or upper
        if btn != self.button and not self.down:
            if btn:
                self.button_which = self.cfg["barrel"] if lower else "middle"
                self.mouse_move(xy)
            self.mouse_button(self.button_which, btn)
            self.button = btn
        if btn:
            tip, pressure = False, 0

        if self.a.mouse:
            if in_range:
                self.mouse_move(xy)
            if tip != self.down:
                self.mouse_button("left", tip)
                self.down = tip
        else:
            self.pen_handle(xy, in_range, tip, pressure)
        self.in_range = in_range
        self.last_xy = xy

    def pen_handle(self, xy, in_range, tip, pressure):
        if not in_range:
            if self.down:
                self.inject_pen(PF_INRANGE | PF_UP, xy, 0, CHANGE_FIRST_UP)
                self.down = False
            if self.in_range:
                self.inject_pen(PF_UPDATE, xy, 0)
            return
        if tip and not self.down:
            self.inject_pen(PF_INRANGE | PF_INCONTACT | PF_FIRSTBUTTON | PF_DOWN, xy, pressure, CHANGE_FIRST_DOWN)
            self.down = True
        elif tip:
            self.inject_pen(PF_INRANGE | PF_INCONTACT | PF_FIRSTBUTTON | PF_UPDATE, xy, pressure)
        elif self.down:
            self.inject_pen(PF_INRANGE | PF_UP, xy, 0, CHANGE_FIRST_UP)
            self.down = False
        else:
            self.inject_pen(PF_INRANGE | PF_UPDATE, xy, 0)

    def release_all(self):
        if self.down:
            if self.a.mouse:
                self.mouse_button("left", False)
            else:
                self.inject_pen(PF_INRANGE | PF_UP, self.last_xy, 0, CHANGE_FIRST_UP)
            self.down = False
        if self.in_range and not self.a.mouse:
            self.inject_pen(PF_UPDATE, self.last_xy, 0)
        self.in_range = False


class DriverService:
    """Runs the driver in background threads. status: 'waiting' | 'WinUSB' | 'HID'.
    on_status(status) is called when it changes (e.g. so the tray can offer WinUSB setup on 'HID')."""

    def __init__(self, mouse=False, verbose=False, on_status=None):
        import types
        self.args = types.SimpleNamespace(mouse=mouse, verbose=verbose)
        self.on_status = on_status
        self.status = "waiting"
        self.stop_event = threading.Event()
        self.state = {"tab": None, "last_report": 0.0}
        self.drv = None
        self.threads = []

    def _set_status(self, s):
        if s != self.status:
            self.status = s
            if self.on_status:
                try:
                    self.on_status(s)
                except Exception as e:  # never let UI callbacks kill the driver
                    log("status callback failed:", e)

    def start(self):
        make_dpi_aware()
        self.drv = Driver(self.args)
        for target in (self._housekeeping, self._run):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self.threads.append(t)
        log("Aiptek HyperPen 12000U driver started.")

    def stop(self):
        self.stop_event.set()
        tab = self.state.get("tab")
        if self.drv:
            self.drv.release_all()
        if tab and tab.kind == "HID":
            set_mode(tab, False)  # stock driver: leave the tablet usable as a mouse
        for t in self.threads:
            t.join(1.5)
        log("Driver stopped.")

    def _housekeeping(self):
        """Live config reload, display-change handling, and re-asserting tablet mode after sleep."""
        drv, state, stop = self.drv, self.state, self.stop_event
        mtime = None
        last_mode = 0.0
        tick = 0
        while not stop.wait(1.0):
            tick += 1
            try:
                m = os.path.getmtime(CONFIG_PATH)
            except OSError:
                m = None
            if m != mtime:
                if mtime is not None or m is not None:
                    drv.config_changed()
                mtime = m
            elif tick % 3 == 0:
                drv.recompute_mapping()  # resolution / layout changes
            now = time.monotonic()
            tab = state.get("tab")
            if tab and now - state["last_report"] > 5 and now - last_mode > 10:
                set_mode(tab, True)
                last_mode = now

    def _run(self):
        drv, state, stop = self.drv, self.state, self.stop_event
        mon = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        waiting_logged = False
        while not stop.is_set():
            tab = tablet_io.open_tablet()
            if not tab or not set_mode(tab, True):
                if tab:
                    tab.close()
                if not waiting_logged:
                    log("Waiting for the tablet...")
                    waiting_logged = True
                self._set_status("waiting")
                stop.wait(2)
                continue
            waiting_logged = False
            size = tablet_io.query_size(tab)
            set_mode(tab, True)
            drv.set_tablet(tab.vid, tab.pid, size)
            log(f"Tablet {tab.vid:04X}:{tab.pid:04X} connected via {tab.kind}, absolute mode enabled,"
                f" active area {size or 'unknown (using configured size)'}.")
            if tab.kind == "HID":
                log("  note: on the stock HID driver Windows also handles the pen itself (double input);"
                    " switch this USB port to WinUSB to fix it.")
            state.update(tab=tab, last_report=time.monotonic())
            self._set_status(tab.kind)
            try:
                while not stop.is_set():
                    r = tab.read()
                    if r is None:
                        continue
                    state["last_report"] = time.monotonic()
                    drv.handle(r)
                    try:
                        mon.sendto(r, ("127.0.0.1", MONITOR_PORT))
                    except OSError:
                        pass
            except OSError as e:
                log("Tablet disconnected:", e)
            finally:
                state["tab"] = None
                drv.release_all()
                if stop.is_set() and tab.kind == "HID":
                    set_mode(tab, False)
                tab.close()
            self._set_status("waiting")
            stop.wait(1)


def acquire_single_instance():
    """True if we are the only driver instance (holds a named mutex for the process lifetime)."""
    kernel32.CreateMutexW.restype = wt.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    global _MUTEX
    _MUTEX = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mouse", action="store_true", help="emulate an absolute mouse instead of a pen (no pressure)")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    if not acquire_single_instance():
        print("The driver is already running.")
        return
    svc = DriverService(args.mouse, args.verbose)
    svc.start()
    print("Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        svc.stop()


if __name__ == "__main__":
    main()
