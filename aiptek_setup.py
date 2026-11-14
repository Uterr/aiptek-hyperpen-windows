"""Setup window for the Aiptek HyperPen 12000U driver.

Pick the monitor the tablet maps to and drag/resize the active area on the tablet.
Changes are saved to config.json immediately; a running aiptek_driver.py applies them live.
"""
import ctypes, socket, threading, time, tkinter as tk
from tkinter import ttk
import aiptek_driver as drv
import tablet_io

PAD = 12
TAB_CW = 640           # tablet canvas width
MON_CW, MON_CH = 640, 170
HANDLE = 7
MIN_W = 400            # smallest area width, tablet units (~0.8")
PC_W, PC_H = 260, 200  # pressure curve canvas


class PenReader(threading.Thread):
    """Shows where the pen is: listens to the running driver, or reads the tablet itself if no driver runs."""

    def __init__(self):
        super().__init__(daemon=True)
        self.latest = None          # (x, y, status, pressure, time)
        self.connected = False
        self.source = ""
        self.tab = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.bind(("127.0.0.1", drv.MONITOR_PORT))
        except OSError:  # another settings window already listens; this one just shows no live pen
            pass
        self.sock.settimeout(0.5)

    def feed(self, r):
        rep = drv.parse_report(r)
        if rep:
            self.latest = (*rep, time.monotonic())

    def run(self):
        while True:
            if driver_running():
                self.source, self.connected = "driver", True
                try:
                    self.feed(self.sock.recv(64))
                except OSError:
                    pass
                continue
            self.tab = tablet_io.open_tablet()
            if not self.tab:
                self.source, self.connected = "", False
                time.sleep(1)
                continue
            tablet_io.set_mode(self.tab, True)
            self.source, self.connected = "direct (" + self.tab.kind + ")", True
            checked = time.monotonic()
            try:
                while True:
                    r = self.tab.read()
                    if r:
                        self.feed(r)
                    if time.monotonic() - checked > 1:
                        checked = time.monotonic()
                        if driver_running():  # hand the tablet over to the driver
                            break
            except OSError:
                pass
            tab, self.tab = self.tab, None
            tab.close()


def driver_running():
    h = ctypes.windll.kernel32.OpenMutexW(0x00100000, False, drv.MUTEX_NAME)
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False


class Setup(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Aiptek Tablet Setup")
        self.resizable(False, False)
        self.cfg = drv.load_config()
        self.mons = drv.monitors()
        self.mon = drv.pick_monitor(self.cfg["monitor"])
        self.cfg["monitor"] = self.mon["name"]
        self.tw, self.th = self.cfg["tablet_size"]
        self.stretch = tk.BooleanVar(value=bool(self.cfg.get("stretch")))
        if not self.cfg["area"]:
            self.cfg["area"] = drv.max_area((self.tw, self.th), self.aspect())
        self.seen = [None, None, None, None]   # min x, min y, max x, max y reached by the pen
        self.beyond_count = 0  # consecutive reports beyond the tablet outline
        self.drag = None
        self.save_job = None

        frm = ttk.Frame(self, padding=10)
        frm.pack()
        self.build_pressure_panel(frm)
        ttk.Label(frm, text="1. Click the monitor the tablet should control", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.mc = tk.Canvas(frm, width=MON_CW, height=MON_CH, bg="#1e1e1e", highlightthickness=0)
        self.mc.pack(pady=(4, 10))
        self.mc.bind("<Button-1>", self.on_monitor_click)

        ttk.Label(frm, text="2. Drag the blue area to move it, drag a corner or scroll the wheel to resize",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.S = (TAB_CW - 2 * PAD) / self.tw
        self.tc = tk.Canvas(frm, width=TAB_CW, height=int(self.th * self.S) + 2 * PAD, bg="#2b2b2b",
                            highlightthickness=0)
        self.tc.pack(pady=(4, 6))
        self.tc.bind("<Button-1>", self.on_press)
        self.tc.bind("<B1-Motion>", self.on_drag)
        self.tc.bind("<ButtonRelease-1>", lambda e: (setattr(self, "drag", None), self.schedule_save()))
        self.tc.bind("<MouseWheel>", self.on_wheel)
        self.tc.bind("<Motion>", self.on_hover)

        row = ttk.Frame(frm)
        row.pack(fill="x", pady=4)
        ttk.Button(row, text="Largest size", command=self.maximize).pack(side="left")
        grid = ttk.Frame(row)
        grid.pack(side="left", padx=12)
        arrows = ["↖", "↑", "↗", "←", "●", "→", "↙", "↓", "↘"]
        for i, a in enumerate(arrows):
            ax, ay = (i % 3) / 2, (i // 3) / 2
            tk.Button(grid, text=a, width=2, command=lambda ax=ax, ay=ay: self.align(ax, ay)).grid(row=i // 3, column=i % 3)
        ttk.Label(row, text="snap\nposition").pack(side="left")
        ttk.Checkbutton(row, text="Stretch: use the whole tablet\n(shapes get distorted)", variable=self.stretch,
                        command=self.on_stretch).pack(side="left", padx=16)

        self.info = ttk.Label(frm, text="", font=("Consolas", 9))
        self.info.pack(anchor="w", pady=(6, 0))
        self.pen_lbl = ttk.Label(frm, text="", font=("Consolas", 9))
        self.pen_lbl.pack(anchor="w")
        self.status = ttk.Label(frm, text="", foreground="#3a7")
        self.status.pack(anchor="w", pady=(4, 0))

        self.reader = PenReader()
        self.reader.start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.redraw()
        self.after(15, self.poll_pen)

    # ------------------------------------------------------------ pressure
    def build_pressure_panel(self, parent):
        pc = dict(drv.DEFAULT_CONFIG["pressure"], **(self.cfg.get("pressure") or {}))
        self.cfg["pressure"] = pc
        self.p_peak = 0
        self.measure_until = 0
        pf = ttk.Frame(parent, padding=(16, 0, 0, 0))
        pf.pack(side="right", fill="y")
        ttk.Label(pf, text="3. Pressure", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(pf, text="Press as hard as you normally would\nwhen drawing, then click Measure.",
                  foreground="#666").pack(anchor="w")
        self.measure_btn = ttk.Button(pf, text="Measure my hardest press (5 s)", command=self.start_measure)
        self.measure_btn.pack(anchor="w", pady=(6, 6))
        self.pcv = tk.Canvas(pf, width=PC_W, height=PC_H, bg="#1e1e1e", highlightthickness=0)
        self.pcv.pack()
        self.p_lbl = ttk.Label(pf, text="", font=("Consolas", 9), justify="left")
        self.p_lbl.pack(anchor="w", pady=(4, 6))

        def scale(label, frm_, to, res, init, cmd):
            s = tk.Scale(pf, label=label, from_=frm_, to=to, resolution=res, orient="horizontal", length=PC_W,
                         command=lambda v: cmd(float(v)))
            s.set(init)
            s.pack(anchor="w")
            return s

        self.s_min = scale("Light touch starts at (raw)", 0, 300, 1, pc["min"], lambda v: self.set_p("min", v))
        self.s_max = scale("Full pressure at (raw)", 50, 1023, 1, pc["max"], lambda v: self.set_p("max", v))
        import math
        self.s_curve = scale("Curve:  soft  ← →  firm", -1, 1, 0.05,
                             round(math.log(pc["curve"], 3), 2), lambda v: self.set_p("curve", round(3 ** v, 3)))
        ttk.Button(pf, text="Reset pressure defaults", command=self.reset_pressure).pack(anchor="w", pady=(6, 0))
        self.draw_curve()
        self.build_options_panel(pf)

    def build_options_panel(self, pf):
        # option buttons instead of drop-down menus: Tk posts menus on the main monitor when the window is on a
        # monitor above/left of it (negative screen coordinates)
        ttk.Label(pf, text="4. Pen options", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(16, 2))

        def group(label, var, values, texts=None):
            ttk.Label(pf, text=label).pack(anchor="w", pady=(6, 0))
            row = ttk.Frame(pf)
            row.pack(anchor="w")
            for v, t in zip(values, texts or values):
                ttk.Radiobutton(row, text=t, value=v, variable=var, command=self.schedule_save).pack(side="left",
                                                                                                padx=(0, 8))

        self.barrel = tk.StringVar(value=self.cfg["barrel"])
        group("Side button:", self.barrel, ["right", "middle", "none"], ["right click", "middle click", "nothing"])
        self.lpi = tk.StringVar(value=f"{self.cfg.get('resolution_lpi', 3048)} lpi")
        group("Sensor resolution (finer = rounder small strokes):", self.lpi,
              ["500 lpi", "1000 lpi", "2000 lpi", "3048 lpi"], ["500", "1000", "2000", "3048 lpi"])
        self.smoothing = tk.StringVar(value=self.cfg.get("smoothing", "off"))
        group("Smoothing (adds a little lag):", self.smoothing, list(drv.SMOOTHING.keys()))
        self.rounding = tk.StringVar(
            value={0: "off", 1: "light", 2: "strong"}.get(int(self.cfg.get("rounding", 0)), "off"))
        group("Small-stroke rounding:", self.rounding, ["off", "light", "strong"])
        self.coil = tk.BooleanVar(value=bool(self.cfg.get("coil_correction", True)))
        ttk.Checkbutton(pf, text="Coil correction (straighter diagonals)", variable=self.coil,
                        command=self.schedule_save).pack(anchor="w", pady=(8, 0))

    def set_p(self, key, v):
        pc = self.cfg["pressure"]
        if key in ("min", "max"):
            v = int(v)
        if pc.get(key) == v:
            return
        pc[key] = v
        self.draw_curve()
        self.schedule_save()

    def reset_pressure(self):
        d = drv.DEFAULT_CONFIG["pressure"]
        self.s_min.set(d["min"]); self.s_max.set(d["max"]); self.s_curve.set(0)

    def start_measure(self):
        self.p_peak = 0
        self.measure_until = time.monotonic() + 5
        self.measure_btn.config(state="disabled")

    def finish_measure(self):
        self.measure_until = 0
        self.measure_btn.config(state="normal", text="Measure my hardest press (5 s)")
        if self.p_peak > self.cfg["pressure"]["min"] + 20:
            self.s_max.set(self.p_peak)
            self.status.config(text=f"Full pressure set to raw {self.p_peak}.")
        else:
            self.status.config(text="No firm press detected - try again, pressing during the 5 seconds.")

    def draw_curve(self, raw=None):
        c = self.pcv
        c.delete("all")
        pc = self.cfg["pressure"]
        top = max(512, pc["max"] + 50, self.p_peak + 20)
        X = lambda r: 6 + r / top * (PC_W - 12)
        Y = lambda f: PC_H - 6 - f * (PC_H - 12)
        c.create_rectangle(X(0), Y(1), X(top), Y(0), outline="#444")
        c.create_line(X(pc["min"]), Y(0), X(pc["min"]), Y(1), fill="#666", dash=(2, 3))
        c.create_line(X(pc["max"]), Y(0), X(pc["max"]), Y(1), fill="#666", dash=(2, 3))
        pts = []
        for i in range(81):
            r = top * i / 80
            pts += [X(r), Y(drv.map_pressure(r, pc))]
        c.create_line(*pts, fill="#5b9bff", width=2)
        if self.p_peak:
            c.create_line(X(self.p_peak), Y(0), X(self.p_peak), Y(1), fill="#ffd040")
        if raw is not None:
            f = drv.map_pressure(raw, pc)
            c.create_oval(X(raw) - 5, Y(f) - 5, X(raw) + 5, Y(f) + 5, fill="#ff4040", outline="")
        c.create_text(X(0) + 4, Y(1) + 4, anchor="nw", fill="#888", font=("Segoe UI", 8), text="output to app")
        c.create_text(X(top) - 4, Y(0) - 4, anchor="se", fill="#888", font=("Segoe UI", 8), text="raw pen pressure")

    def update_pressure(self, tip, p):
        now = time.monotonic()
        if tip:
            self.p_peak = max(self.p_peak, p)
        if self.measure_until:
            left = self.measure_until - now
            if left <= 0:
                self.finish_measure()
            else:
                self.measure_btn.config(text=f"Press hard now... {left:.0f} s  (peak {self.p_peak})")
        f = drv.map_pressure(p, self.cfg["pressure"]) if tip else 0
        self.p_lbl.config(text=f"raw now: {p if tip else 0:4d}  ->  app gets {f * 100:3.0f}%\n"
                               f"hardest seen: {self.p_peak}")
        self.draw_curve(p if tip else None)

    # ------------------------------------------------------------ geometry helpers
    def aspect(self):
        l, t, r, b = self.mon["rect"]
        return (r - l) / (b - t)

    def t2c(self, x, y):
        return PAD + x * self.S, PAD + y * self.S

    def c2t(self, cx, cy):
        return (cx - PAD) / self.S, (cy - PAD) / self.S

    def fit(self, x0, y0, w):
        """Clamp an aspect-locked rect (top-left + width) into the tablet."""
        a = self.aspect()
        w = max(MIN_W, min(w, self.tw, self.th * a))
        h = w / a
        x0 = min(max(x0, 0), self.tw - w)
        y0 = min(max(y0, 0), self.th - h)
        self.cfg["area"] = [round(x0), round(y0), round(x0 + w), round(y0 + h)]

    # ------------------------------------------------------------ actions
    def maximize(self):
        x0, y0, x1, y1 = self.cfg["area"]
        self.stretch.set(False)
        self.fit(x0, y0, 10 ** 9)
        self.changed()

    def align(self, ax, ay):
        self.stretch.set(False)
        x0, y0, x1, y1 = self.cfg["area"]
        w, h = x1 - x0, y1 - y0
        if w > self.tw or h > self.th or abs(w / h - self.aspect()) > 0.01:
            self.fit(0, 0, 10 ** 9)
            x0, y0, x1, y1 = self.cfg["area"]
            w, h = x1 - x0, y1 - y0
        self.fit((self.tw - w) * ax, (self.th - h) * ay, w)
        self.changed()

    def on_stretch(self):
        if self.stretch.get():
            self.cfg["area"] = [0, 0, self.tw, self.th]
        else:
            self.fit(0, 0, 10 ** 9)
            self.align(0.5, 0.5)
        self.changed()

    def on_monitor_click(self, e):
        for m, (l, t, r, b) in self.mon_boxes:
            if l <= e.x <= r and t <= e.y <= b:
                self.mon = m
                self.cfg["monitor"] = m["name"]
                if self.stretch.get():
                    self.cfg["area"] = [0, 0, self.tw, self.th]
                else:  # keep center and width, adapt to the new aspect ratio
                    x0, y0, x1, y1 = self.cfg["area"]
                    w = x1 - x0
                    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
                    w = min(w, self.th * self.aspect())
                    self.fit(cx - w / 2, cy - w / self.aspect() / 2, w)
                self.changed()
                return

    def hit(self, cx, cy):
        x0, y0, x1, y1 = self.cfg["area"]
        (ax, ay), (bx, by) = self.t2c(x0, y0), self.t2c(x1, y1)
        for name, (hx, hy) in (("tl", (ax, ay)), ("tr", (bx, ay)), ("bl", (ax, by)), ("br", (bx, by))):
            if abs(cx - hx) <= HANDLE + 2 and abs(cy - hy) <= HANDLE + 2:
                return name
        if ax <= cx <= bx and ay <= cy <= by:
            return "move"
        return None

    def on_hover(self, e):
        h = None if self.stretch.get() else self.hit(e.x, e.y)
        self.tc.config(cursor={"tl": "size_nw_se", "br": "size_nw_se", "tr": "size_ne_sw", "bl": "size_ne_sw",
                               "move": "fleur"}.get(h, ""))

    def on_press(self, e):
        if self.stretch.get():
            return
        kind = self.hit(e.x, e.y)
        if not kind:
            return
        x0, y0, x1, y1 = self.cfg["area"]
        tx, ty = self.c2t(e.x, e.y)
        anchor = {"tl": (x1, y1), "tr": (x0, y1), "bl": (x1, y0), "br": (x0, y0)}.get(kind)
        self.drag = (kind, tx - x0, ty - y0, anchor)

    def on_drag(self, e):
        if not self.drag:
            return
        kind, ox, oy, anchor = self.drag
        tx, ty = self.c2t(e.x, e.y)
        x0, y0, x1, y1 = self.cfg["area"]
        if kind == "move":
            self.fit(tx - ox, ty - oy, x1 - x0)
        else:
            a = self.aspect()
            axx, ayy = anchor
            sx = 1 if kind in ("tr", "br") else -1
            sy = 1 if kind in ("bl", "br") else -1
            w = max(sx * (tx - axx), sy * (ty - ayy) * a, MIN_W)
            # room available on that side of the anchor
            w = min(w, (self.tw - axx) if sx > 0 else axx, ((self.th - ayy) if sy > 0 else ayy) * a)
            h = w / a
            nx0 = axx if sx > 0 else axx - w
            ny0 = ayy if sy > 0 else ayy - h
            self.fit(nx0, ny0, w)
        self.redraw()

    def on_wheel(self, e):
        if self.stretch.get():
            return
        x0, y0, x1, y1 = self.cfg["area"]
        f = 1.05 if e.delta > 0 else 1 / 1.05
        w = x1 - x0
        nw = min(max(w * f, MIN_W), self.tw, self.th * self.aspect())
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.fit(cx - nw / 2, cy - nw / self.aspect() / 2, nw)
        self.changed()

    def changed(self):
        self.redraw()
        self.schedule_save()

    def schedule_save(self):
        if self.save_job:
            self.after_cancel(self.save_job)
        self.save_job = self.after(250, self.save)

    def save(self):
        self.save_job = None
        self.cfg["barrel"] = self.barrel.get()
        self.cfg["smoothing"] = self.smoothing.get()
        self.cfg["coil_correction"] = self.coil.get()
        self.cfg["resolution_lpi"] = int(self.lpi.get().split()[0])
        self.cfg["rounding"] = {"off": 0, "light": 1, "strong": 2}[self.rounding.get()]
        self.cfg["stretch"] = self.stretch.get()
        self.cfg["tablet_size"] = [self.tw, self.th]
        drv.save_config(self.cfg)
        msg = "Saved. The running driver applies it right away." if driver_running() else \
            "Saved. (The driver isn't running - start AiptekTablet to use the tablet.)"
        self.status.config(text=msg + "  " + time.strftime("%H:%M:%S"))

    def on_close(self):
        if self.save_job:
            self.after_cancel(self.save_job)
            self.save()
        tab = self.reader.tab
        if tab and tab.kind == "HID":  # stock driver: give it back to Windows as a mouse
            tablet_io.set_mode(tab, False)
        self.destroy()

    # ------------------------------------------------------------ drawing
    def redraw(self):
        self.draw_monitors()
        tc = self.tc
        tc.delete("all")
        ax, ay = self.t2c(0, 0)
        bx, by = self.t2c(self.tw, self.th)
        tc.create_rectangle(ax, ay, bx, by, fill="#3a3a3a", outline="#888")
        tc.create_text(bx - 4, by - 4, anchor="se", fill="#777", font=("Segoe UI", 8),
                       text=f"tablet {self.tw / 500:.1f}\" × {self.th / 500:.1f}\"")
        tc.create_rectangle(0, 0, 0, 0, outline="#999", dash=(2, 3), tags="seen")
        self.update_seen()
        x0, y0, x1, y1 = self.cfg["area"]
        (px0, py0), (px1, py1) = self.t2c(x0, y0), self.t2c(x1, y1)
        tc.create_rectangle(px0, py0, px1, py1, fill="#2d6cdf", stipple="gray50", outline="#5b9bff", width=2)
        tc.create_text((px0 + px1) / 2, (py0 + py1) / 2, fill="white", font=("Segoe UI", 10, "bold"),
                       text=self.mon["name"].replace("\\\\.\\", ""))
        if not self.stretch.get():
            for hx, hy in ((px0, py0), (px1, py0), (px0, py1), (px1, py1)):
                tc.create_rectangle(hx - HANDLE, hy - HANDLE, hx + HANDLE, hy + HANDLE, fill="#5b9bff", outline="white")
        tc.create_oval(0, 0, 0, 0, tags="pen", state="hidden")
        w, h = x1 - x0, y1 - y0
        l, t, r, b = self.mon["rect"]
        self.info.config(text=f"Area: {w / 500:.2f}\" × {h / 500:.2f}\"  ({w * h * 100 / (self.tw * self.th):.0f}% of tablet)"
                              f"   tablet units [{x0}, {y0}, {x1}, {y1}]  ->  {r - l}×{b - t} px"
                              f"   ({w / max(r - l, 1):.2f} tablet units per pixel)")

    def draw_monitors(self):
        mc = self.mc
        mc.delete("all")
        L = min(m["rect"][0] for m in self.mons); T = min(m["rect"][1] for m in self.mons)
        R = max(m["rect"][2] for m in self.mons); B = max(m["rect"][3] for m in self.mons)
        s = min((MON_CW - 2 * PAD) / (R - L), (MON_CH - 2 * PAD) / (B - T))
        ox = (MON_CW - (R - L) * s) / 2
        oy = (MON_CH - (B - T) * s) / 2
        self.mon_boxes = []
        self.mon_xform = (L, T, s, ox, oy)
        for m in self.mons:
            l, t, r, b = m["rect"]
            box = (ox + (l - L) * s + 2, oy + (t - T) * s + 2, ox + (r - L) * s - 2, oy + (b - T) * s - 2)
            sel = m["name"] == self.mon["name"]
            mc.create_rectangle(*box, fill="#2d6cdf" if sel else "#444", outline="#5b9bff" if sel else "#777", width=2)
            mc.create_text((box[0] + box[2]) / 2, (box[1] + box[3]) / 2, fill="white", font=("Segoe UI", 9),
                           text=f"{m['name'].replace(chr(92) * 2 + '.' + chr(92), '')}\n{r - l}×{b - t}"
                                f"{'  (main)' if m['primary'] else ''}", justify="center")
            self.mon_boxes.append((m, box))
        mc.create_oval(0, 0, 0, 0, tags="pen", state="hidden")

    def update_seen(self):
        if self.seen[0] is not None:
            self.tc.coords("seen", *self.t2c(self.seen[0], self.seen[1]), *self.t2c(self.seen[2], self.seen[3]))

    def poll_pen(self):
        lat = self.reader.latest
        if not self.reader.connected:
            self.pen_lbl.config(text="Tablet not found - is it plugged in?")
        elif lat and time.monotonic() - lat[4] < 0.3 and lat[2] & 0x07:
            x, y, st, p, _ = lat
            # tablet reaches further than it claims: grow the outline, but only for a sustained, plausible overshoot
            # (a few stray reports, e.g. while the resolution is being switched, must not resize the tablet)
            beyond = (self.tw < x <= self.tw * 1.25) or (self.th < y <= self.th * 1.25)
            self.beyond_count = self.beyond_count + 1 if beyond else 0
            if self.beyond_count >= 40:
                self.beyond_count = 0
                self.tw, self.th = max(self.tw, x), max(self.th, y)
                self.S = (TAB_CW - 2 * PAD) / self.tw
                self.tc.config(height=int(self.th * self.S) + 2 * PAD)
                self.redraw()
                self.schedule_save()
            if self.seen[0] is None:
                self.seen = [x, y, x, y]
            else:
                self.seen = [min(self.seen[0], x), min(self.seen[1], y), max(self.seen[2], x), max(self.seen[3], y)]
            self.update_seen()
            tip = bool(st & 0x04) and not st & 0x18  # side buttons make the pressure field read 1023
            self.update_pressure(tip, p)
            col = "#ff4040" if tip else "#ffd040"
            cx, cy = self.t2c(x, y)
            r = 4 + (p / 1023 * 6 if tip else 0)
            self.tc.coords("pen", cx - r, cy - r, cx + r, cy + r)
            self.tc.itemconfig("pen", fill=col, outline="", state="normal")
            # where it lands on the selected monitor
            x0, y0, x1, y1 = self.cfg["area"]
            fx = min(max((x - x0) / (x1 - x0), 0), 1); fy = min(max((y - y0) / (y1 - y0), 0), 1)
            l, t, rr, b = self.mon["rect"]
            L, T, s, ox, oy = self.mon_xform
            mx, my = ox + (l - L + fx * (rr - l)) * s, oy + (t - T + fy * (b - t)) * s
            self.mc.coords("pen", mx - 4, my - 4, mx + 4, my + 4)
            self.mc.itemconfig("pen", fill=col, outline="", state="normal")
            self.pen_lbl.config(text=f"[{self.reader.source}] Pen: x={x:5d} y={y:5d}  {'TOUCH' if tip else 'hover'}  pressure={p if tip else 0:4d}"
                                     f"   reached so far: x {self.seen[0]}..{self.seen[2]}, y {self.seen[1]}..{self.seen[3]}"
                                     " (dotted box)")
        else:
            if self.measure_until:
                self.update_pressure(False, 0)
            self.tc.itemconfig("pen", state="hidden")
            self.mc.itemconfig("pen", state="hidden")
            if self.reader.connected and not lat:
                self.pen_lbl.config(text="Tablet connected - hover the pen over it to see it here.")
        self.after(15, self.poll_pen)


if __name__ == "__main__":
    drv.make_dpi_aware()
    Setup().mainloop()
