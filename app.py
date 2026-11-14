"""AiptekTablet: tray app + self-installer for the Aiptek HyperPen 12000U driver.

  AiptekTablet.exe                 first run: installer; installed: tray driver (or opens Settings if running)
  AiptekTablet.exe --settings      settings window
  AiptekTablet.exe --uninstall     remove everything and give the tablet back to Windows
  AiptekTablet.exe --winusb install|restore   (internal, elevated) switch the tablet's Windows driver
"""
import ctypes, os, shutil, subprocess, sys, threading, time, winreg
from ctypes import wintypes as wt

if sys.stdout is None:  # windowed exe: no console
    sys.stdout = sys.stderr = open(os.devnull, "w")

APP_NAME = "AiptekTablet"
DISPLAY_NAME = "Aiptek HyperPen 12000U Tablet Driver"
VERSION = "1.1.0"
FROZEN = getattr(sys, "frozen", False)
INSTALL_DIR = os.path.join(os.environ["LOCALAPPDATA"], "Programs", APP_NAME)
INSTALLED_EXE = os.path.join(INSTALL_DIR, APP_NAME + ".exe")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\\" + APP_NAME
START_MENU_LNK = os.path.join(os.environ["APPDATA"], r"Microsoft\Windows\Start Menu\Programs", DISPLAY_NAME + ".lnk")
CREATE_NO_WINDOW = 0x08000000

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
MB_OK, MB_YESNO, MB_ICONINFO, MB_ICONWARN, MB_ICONERR, IDYES = 0, 4, 0x40, 0x30, 0x10, 6


def msgbox(text, flags=MB_ICONINFO):
    return user32.MessageBoxW(None, text, DISPLAY_NAME, flags | 0x10000)  # MB_SETFOREGROUND


def self_command(*args):
    """(executable, parameter string) that re-launches this app with args (exe or python script)."""
    if FROZEN:
        return sys.executable, " ".join(args)
    return sys.executable, " ".join([f'"{os.path.abspath(__file__)}"', *args])


def launch(*args):
    exe, params = self_command(*args)
    subprocess.Popen(f'"{exe}" {params}', creationflags=CREATE_NO_WINDOW if not FROZEN else 0, close_fds=True)


# ------------------------------------------------------------------ elevation
class SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("fMask", wt.ULONG), ("hwnd", wt.HWND), ("lpVerb", wt.LPCWSTR),
                ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR), ("lpDirectory", wt.LPCWSTR),
                ("nShow", ctypes.c_int), ("hInstApp", wt.HINSTANCE), ("lpIDList", ctypes.c_void_p),
                ("lpClass", wt.LPCWSTR), ("hkeyClass", wt.HKEY), ("dwHotKey", wt.DWORD), ("hIcon", wt.HANDLE),
                ("hProcess", wt.HANDLE)]


def run_elevated(*args):
    """Run this app elevated with args and wait. -> exit code, or None if the user declined UAC."""
    exe, params = self_command(*args)
    sei = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40, lpVerb="runas", lpFile=exe,
                            lpParameters=params, nShow=0)
    if not shell32.ShellExecuteExW(ctypes.byref(sei)):
        return None
    kernel32.WaitForSingleObject(sei.hProcess, 0xFFFFFFFF)
    code = wt.DWORD()
    kernel32.GetExitCodeProcess(sei.hProcess, ctypes.byref(code))
    kernel32.CloseHandle(sei.hProcess)
    return code.value


def result_file():
    import aiptek_driver
    return os.path.join(aiptek_driver.APP_DIR, "winusb_result.txt")


def winusb_mode(action):
    """Elevated helper: switch driver, write the outcome for the (non-elevated) caller."""
    import winusb_install
    try:
        msgs = winusb_install.install_all() if action == "install" else winusb_install.restore_all()
        text, code = "\n".join(msgs), 0
    except SystemExit as e:
        text, code = str(e.code), 1
    except Exception as e:
        text, code = f"{type(e).__name__}: {e}", 1
    with open(result_file(), "w", encoding="utf-8") as f:
        f.write(text)
    return code


def switch_driver(action):
    """-> (ok, message). Asks for admin via UAC."""
    try:
        os.remove(result_file())
    except OSError:
        pass
    code = run_elevated("--winusb", action)
    if code is None:
        return False, "Administrator permission was declined."
    try:
        text = open(result_file(), encoding="utf-8").read()
    except OSError:
        text = "(no details)"
    return code == 0, text


# ------------------------------------------------------------------ install / uninstall
def set_autostart(on):
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, f'"{INSTALLED_EXE}"')
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


def autostart_enabled():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except OSError:
        return False


def make_shortcut(lnk, target, args=""):
    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');$s.TargetPath='{target}';"
          f"$s.Arguments='{args}';$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], creationflags=CREATE_NO_WINDOW)


def register_uninstaller():
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in (("DisplayName", DISPLAY_NAME), ("DisplayVersion", VERSION), ("Publisher", "Community"),
                          ("DisplayIcon", INSTALLED_EXE), ("InstallLocation", INSTALL_DIR),
                          ("UninstallString", f'"{INSTALLED_EXE}" --uninstall')):
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)


def is_installed_copy():
    return FROZEN and os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(INSTALLED_EXE)


def stop_running_instance():
    """Ask a running tray instance to exit (closes its window message loop) and wait for it."""
    hwnd = user32.FindWindowW(APP_NAME + "Ctl", None)
    if hwnd:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        for _ in range(50):
            if not user32.FindWindowW(APP_NAME + "Ctl", None):
                break
            time.sleep(0.1)


def installer_ui():
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title(DISPLAY_NAME + " - Setup")
    root.resizable(False, False)
    f = ttk.Frame(root, padding=16)
    f.pack()
    ttk.Label(f, text=DISPLAY_NAME, font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(f, justify="left", text=(
        "This installs the driver for your Aiptek HyperPen 12000U tablet:\n\n"
        "  •  the pen works as a real pen (absolute position + pressure)\n"
        "  •  you choose the monitor and the part of the tablet in Settings\n"
        "  •  it runs from the tray icon next to the clock\n\n"
        "Windows will ask for administrator permission once: the tablet is switched to\n"
        "Microsoft's built-in \"WinUSB\" driver so Windows stops treating it as a mouse.\n"
        "Uninstall (Settings → Apps, or the tray menu) puts everything back.")).pack(anchor="w", pady=(8, 8))
    auto = tk.BooleanVar(value=True)
    ttk.Checkbutton(f, text="Start automatically when I sign in (recommended)", variable=auto).pack(anchor="w")
    status = ttk.Label(f, text="", foreground="#a40")
    status.pack(anchor="w", pady=(8, 0))
    btns = ttk.Frame(f)
    btns.pack(anchor="e", pady=(12, 0))
    result = {"ok": False}

    def do_install():
        for b in btns.winfo_children():
            b.config(state="disabled")
        status.config(text="Installing...")
        root.update()
        try:
            stop_running_instance()
            os.makedirs(INSTALL_DIR, exist_ok=True)
            if FROZEN:
                shutil.copy2(sys.executable, INSTALLED_EXE)
            set_autostart(auto.get())
            make_shortcut(START_MENU_LNK, INSTALLED_EXE)
            register_uninstaller()
        except OSError as e:
            status.config(text=f"Could not install: {e}")
            for b in btns.winfo_children():
                b.config(state="normal")
            return
        import winusb_install
        if any(not ok for _, ok in winusb_install.status()):
            status.config(text="Waiting for administrator permission...")
            root.update()
            ok, text = switch_driver("install")
            if not ok:
                msgbox("The tablet driver could not be switched:\n\n" + text +
                       "\n\nYou can retry later from the tray menu (“Set up tablet USB port”).", MB_ICONWARN)
        elif not winusb_install.status():
            msgbox("Installed. The tablet is not plugged in right now - when you plug it in, "
                   "the app will offer to set it up (needs administrator permission once per USB port).")
        result["ok"] = True
        root.destroy()

    ttk.Button(btns, text="Install", command=do_install).pack(side="left", padx=4)
    ttk.Button(btns, text="Cancel", command=root.destroy).pack(side="left")
    root.mainloop()
    if result["ok"]:
        if FROZEN:
            subprocess.Popen([INSTALLED_EXE], close_fds=True)
        else:
            launch()


def uninstall():
    if msgbox("Uninstall the Aiptek tablet driver?\n\nThe tablet goes back to Windows' own driver "
              "(it will act as a mouse again).", MB_YESNO | MB_ICONWARN) != IDYES:
        return
    stop_running_instance()
    import winusb_install
    if any(ok for _, ok in winusb_install.status()):
        ok, text = switch_driver("restore")
        if not ok:
            msgbox("Could not give the tablet back to Windows:\n\n" + text +
                   "\n\nYou can do it later in Device Manager (uninstall the 'USB Tablet' device and replug it).",
                   MB_ICONWARN)
    set_autostart(False)
    for path in (START_MENU_LNK,):
        try:
            os.remove(path)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    import aiptek_driver
    # files in use (this exe) are removed by a short-lived cmd after we exit
    subprocess.Popen(f'cmd /c timeout /t 2 /nobreak >nul & rmdir /s /q "{INSTALL_DIR}" & rmdir /s /q "{aiptek_driver.APP_DIR}"',
                     creationflags=CREATE_NO_WINDOW, close_fds=True, cwd=os.environ["TEMP"])
    msgbox("Uninstalled. If the tablet doesn't work as a mouse right away, unplug and replug it.")


# ------------------------------------------------------------------ tray
def icon_image(size=64):
    from PIL import Image, ImageDraw
    s = size / 64
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([2 * s, 10 * s, 62 * s, 56 * s], radius=7 * s, fill=(38, 42, 52, 255),
                        outline=(120, 130, 150, 255), width=max(1, int(2 * s)))
    d.rectangle([9 * s, 16 * s, 55 * s, 50 * s], fill=(52, 110, 220, 255))
    d.line([18 * s, 52 * s, 50 * s, 6 * s], fill=(245, 245, 245, 255), width=max(2, int(6 * s)))
    d.polygon([(15 * s, 58 * s), (16 * s, 49 * s), (22 * s, 53 * s)], fill=(255, 80, 80, 255))
    return im


def tray():
    import pystray
    import aiptek_driver
    import winusb_install

    if not aiptek_driver.acquire_single_instance():
        launch("--settings")  # already running: the user probably wants the settings
        return

    STATUS_TEXT = {"waiting": "Waiting for the tablet", "WinUSB": "Tablet connected",
                   "HID": "Tablet needs setup on this USB port"}
    asked = {"HID": False}
    icon = pystray.Icon(APP_NAME, icon_image(), DISPLAY_NAME)

    def setup_port(*_):
        ok, text = switch_driver("install")
        if not ok:
            msgbox("The tablet could not be set up:\n\n" + text, MB_ICONWARN)

    def on_status(st):
        icon.title = f"{DISPLAY_NAME}\n{STATUS_TEXT.get(st, st)}"
        icon.update_menu()
        if st == "HID" and not asked["HID"]:
            asked["HID"] = True

            def ask():
                if msgbox("The tablet is plugged into a USB port that hasn't been set up yet, so Windows "
                          "also handles it as a mouse (you'd get doubled input).\n\nSet up this USB port now? "
                          "Windows will ask for administrator permission.", MB_YESNO | MB_ICONINFO) == IDYES:
                    setup_port()
            threading.Thread(target=ask, daemon=True).start()
        elif st == "WinUSB":
            asked["HID"] = False

    svc = aiptek_driver.DriverService(on_status=on_status)

    def open_settings(*_):
        launch("--settings")

    def toggle_autostart(*_):
        set_autostart(not autostart_enabled())

    def open_log(*_):
        os.startfile(aiptek_driver.LOG_PATH) if os.path.exists(aiptek_driver.LOG_PATH) else None

    def do_uninstall(*_):
        launch("--uninstall")

    def quit_app(*_):
        icon.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem("Settings...", open_settings, default=True),
        pystray.MenuItem(lambda _: STATUS_TEXT.get(svc.status, svc.status), None, enabled=False),
        pystray.MenuItem("Set up tablet USB port (admin)...", setup_port, visible=lambda _: svc.status == "HID"),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Start with Windows", toggle_autostart, checked=lambda _: autostart_enabled(),
                         visible=is_installed_copy() or autostart_enabled()),
        pystray.MenuItem("Open log", open_log),
        pystray.MenuItem("Uninstall...", do_uninstall, visible=is_installed_copy()),
        pystray.MenuItem("Exit", quit_app),
    )

    # hidden control window so the installer/uninstaller can ask a running instance to exit
    ctl_thread = threading.Thread(target=control_window, args=(icon,), daemon=True)
    ctl_thread.start()
    svc.start()
    on_status(svc.status)
    try:
        icon.run()
    finally:
        svc.stop()


def control_window(icon):
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = ctypes.c_ssize_t

    def proc(h, msg, wp, lp):
        if msg == 0x0010:  # WM_CLOSE
            icon.stop()
            user32.DestroyWindow(h)
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(h, msg, wp, lp)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                    ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR)]

    cb = WNDPROC(proc)
    wc = WNDCLASSW(lpfnWndProc=cb, lpszClassName=APP_NAME + "Ctl", hInstance=kernel32.GetModuleHandleW(None))
    user32.RegisterClassW(ctypes.byref(wc))
    user32.CreateWindowExW.restype = wt.HWND
    user32.CreateWindowExW(0, APP_NAME + "Ctl", APP_NAME, 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def main():
    args = sys.argv[1:]
    if args[:1] == ["--winusb"] and len(args) > 1:
        sys.exit(winusb_mode(args[1]))
    if args[:1] == ["--settings"]:
        kernel32.CreateMutexW.restype = wt.HANDLE
        global _SETTINGS_MUTEX
        _SETTINGS_MUTEX = kernel32.CreateMutexW(None, False, "Local\\AiptekTabletSettings")
        if ctypes.get_last_error() == 183:  # already open: bring it to the front
            hwnd = user32.FindWindowW(None, "Aiptek Tablet Setup")
            if hwnd:
                user32.ShowWindow(hwnd, 9)
                user32.SetForegroundWindow(hwnd)
            return
        import aiptek_driver, aiptek_setup
        aiptek_driver.make_dpi_aware()
        aiptek_setup.Setup().mainloop()
        return
    if args[:1] == ["--uninstall"]:
        return uninstall()
    if args[:1] == ["--tray"] or is_installed_copy() or not FROZEN:
        return tray()
    return installer_ui()


if __name__ == "__main__":
    main()
