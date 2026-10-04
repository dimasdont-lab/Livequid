"""System-tray icon (ctypes only): Pause / Autostart / Exit.

New tray icons land in Windows' hidden-icons area (the ^ arrow) by default.
"""
import ctypes
import sys
import threading
from ctypes import wintypes
from pathlib import Path

user32, shell32, kernel32, gdi32 = ctypes.windll.user32, ctypes.windll.shell32, ctypes.windll.kernel32, ctypes.windll.gdi32

WM_CLOSE, WM_DESTROY, WM_NULL, WM_USER = 0x10, 0x02, 0x00, 0x400
WM_TRAY = WM_USER + 1
WM_LBUTTONDBLCLK, WM_RBUTTONUP = 0x203, 0x205
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
MF_STRING, MF_CHECKED, MF_SEPARATOR = 0, 8, 0x800
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x100, 0x2
ID_PAUSE, ID_AUTOSTART, ID_EXIT = 1, 2, 3
RUN_KEY, RUN_NAME = r"Software\Microsoft\Windows\CurrentVersion\Run", "Livequid"

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HANDLE),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT),
                ("szInfoTitle", wintypes.WCHAR * 64), ("dwInfoFlags", wintypes.DWORD),
                ("guidItem", ctypes.c_byte * 16), ("hBalloonIcon", wintypes.HANDLE)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


def _make_icon(size=32):
    """A little green glass droplet, drawn pixel by pixel (no image files needed)."""
    px = bytearray()
    c = (size - 1) / 2.0
    for y in range(size):
        for x in range(size):
            dx, dy = x - c, y - c
            r = (dx * dx + dy * dy) ** 0.5 / (size * 0.44)
            if r > 1.0:
                px += b"\x00\x00\x00\x00"
                continue
            edge = max(0.0, min(1.0, (1.0 - r) * 9))                       # soft rim
            rim = r ** 3
            hl = max(0.0, 1.0 - (((dx + size * 0.18) ** 2 + (dy + size * 0.2) ** 2) ** 0.5) / (size * 0.17))
            g = min(255, int(70 + 130 * rim + 255 * hl))
            rch = min(255, int(10 + 60 * rim + 255 * hl))
            b = min(255, int(40 + 90 * rim + 255 * hl))
            a = int(255 * edge * (0.55 + 0.45 * rim + 0.5 * hl))
            a = min(255, a)
            px += bytes((b * a // 255, g * a // 255, rch * a // 255, a))   # premultiplied BGRA
    color = gdi32.CreateBitmap(size, size, 1, 32, bytes(px))
    mask = gdi32.CreateBitmap(size, size, 1, 1, bytes(size * size // 8))
    ii = ICONINFO(True, 0, 0, mask, color)
    return user32.CreateIconIndirect(ctypes.byref(ii))


# ---- autostart (current user only, a single Run-key value) --------------------
def autostart_enabled():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            exe = Path(sys.executable)
            exe = exe.with_name("pythonw.exe") if exe.with_name("pythonw.exe").exists() else exe
            main = Path(__file__).with_name("main.py")
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{exe}" "{main}"')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


class Tray:
    def __init__(self):
        self.quit = threading.Event()
        self.paused = threading.Event()
        self.hwnd = None
        self._ready = threading.Event()
        self._wndproc = WNDPROC(self._proc)       # keep a reference alive

    def start(self):
        threading.Thread(target=self._run, daemon=True).start()
        self._ready.wait(3)

    def stop(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ------------------------------------------------------------------
    def _run(self):
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc, wc.hInstance, wc.lpszClassName = self._wndproc, hinst, "LivequidTray"
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "LivequidTray", "Livequid", 0, 0, 0, 0, 0, None, None, hinst, None)
        self.icon = _make_icon()
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd, nid.uID, nid.uFlags = self.hwnd, 1, NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage, nid.hIcon, nid.szTip = WM_TRAY, self.icon, "Livequid wallpaper"
        self._nid = nid
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        self._ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _proc(self, hwnd, msg, wp, lp):
        if msg == WM_TRAY and lp == WM_RBUTTONUP:
            self._menu(hwnd)
            return 0
        if msg == WM_TRAY and lp == WM_LBUTTONDBLCLK:
            self._toggle_pause()
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid))
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _toggle_pause(self):
        if self.paused.is_set():
            self.paused.clear()
        else:
            self.paused.set()

    def _menu(self, hwnd):
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if self.paused.is_set() else 0), ID_PAUSE, "Пауза")
        user32.AppendMenuW(m, MF_STRING | (MF_CHECKED if autostart_enabled() else 0), ID_AUTOSTART,
                           "Запускати разом з Windows")
        user32.AppendMenuW(m, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(m, MF_STRING, ID_EXIT, "Вийти")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(hwnd)               # so the menu closes when you click elsewhere
        cmd = user32.TrackPopupMenu(m, TPM_RETURNCMD | TPM_RIGHTBUTTON, pt.x, pt.y, 0, hwnd, None)
        user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(m)
        if cmd == ID_PAUSE:
            self._toggle_pause()
        elif cmd == ID_AUTOSTART:
            try:
                set_autostart(not autostart_enabled())
            except OSError:
                pass
        elif cmd == ID_EXIT:
            self.quit.set()
