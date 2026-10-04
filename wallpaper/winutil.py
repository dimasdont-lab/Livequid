"""Windows-only helpers (ctypes, no extra packages): monitors, cursor,
and embedding a window into the desktop behind the icons."""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
shcore = getattr(ctypes.windll, "shcore", None)

SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CHILD, WS_VISIBLE, WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x40000000, 0x10000000, 0x80000000, 0x00C00000, 0x00040000
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_TRANSPARENT = 0x80, 0x08000000, 0x20
SWP_NOACTIVATE, SWP_SHOWWINDOW, SWP_NOZORDER = 0x10, 0x40, 0x04
HWND_BOTTOM = 1
VK_CONTROL, VK_MENU, VK_Q = 0x11, 0x12, 0x51


def set_dpi_aware():
    """Must run before any window exists, so all coordinates are real pixels."""
    try:
        shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


def monitors():
    """Monitor rectangles (x0, y0, x1, y1) in virtual-desktop pixels."""
    out = []
    cb_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HANDLE, wintypes.HDC,
                              ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    def cb(_h, _dc, rc, _p):
        r = rc.contents
        out.append((r.left, r.top, r.right, r.bottom))
        return 1

    user32.EnumDisplayMonitors(None, None, cb_t(cb), 0)
    return out


def virtual_screen():
    g = user32.GetSystemMetrics
    return g(SM_XVIRTUALSCREEN), g(SM_YVIRTUALSCREEN), g(SM_CXVIRTUALSCREEN), g(SM_CYVIRTUALSCREEN)


def cursor_pos():
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def quit_hotkey_down():
    """Ctrl+Alt+Q."""
    s = user32.GetAsyncKeyState
    return bool(s(VK_CONTROL) & 0x8000 and s(VK_MENU) & 0x8000 and s(VK_Q) & 0x8000)


def _class(hwnd):
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value


def fullscreen_app_active():
    """True if a normal app covers a whole monitor (game, video) - we can sleep then."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd or _class(hwnd) in ("Progman", "WorkerW", "Shell_TrayWnd", "SysListView32"):
        return False
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return any(r.left <= m[0] and r.top <= m[1] and r.right >= m[2] and r.bottom >= m[3]
               for m in monitors())


def embed_in_desktop(hwnd):
    """Put hwnd behind the desktop icons, covering every monitor."""
    vx, vy, vw, vh = virtual_screen()
    progman = user32.FindWindowW("Progman", None)
    # ask Explorer to create the WorkerW layer that sits behind the icons
    res = wintypes.DWORD()
    user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, 0, 1000, ctypes.byref(res))
    user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ctypes.byref(res))

    found = []
    enum_t = ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)

    def enum(h, _):
        if user32.FindWindowExW(h, None, "SHELLDLL_DefView", None):
            w = user32.FindWindowExW(None, h, "WorkerW", None)   # classic layout (Win10 / early Win11)
            if w:
                found.append(w)
        return 1

    user32.EnumWindows(enum_t(enum), 0)
    parent = found[0] if found else (user32.FindWindowExW(progman, None, "WorkerW", None) or progman)  # 24H2 layout

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    style = (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD | WS_VISIBLE
    user32.SetWindowLongW(hwnd, GWL_STYLE, style)
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    user32.SetParent(hwnd, parent)

    pt = wintypes.POINT(vx, vy)                    # virtual-desktop origin in parent coordinates
    user32.ScreenToClient(parent, ctypes.byref(pt))
    user32.SetWindowPos(hwnd, HWND_BOTTOM, pt.x, pt.y, vw, vh, SWP_NOACTIVATE | SWP_SHOWWINDOW)
