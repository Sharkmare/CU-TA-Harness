import ctypes
import time
from ctypes import wintypes

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
KEYEVENTF_KEYUP = 0x0002
CLICK_HOLD_SECONDS = 0.08
SETTLE_SECONDS = 0.3
VIRTUAL_KEYS = {"PageUp": 0x21, "PageDown": 0x22, "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28, "Return": 0x0D, "Tab": 0x09, "Escape": 0x1B}


def unity_to_screen(client_origin, client_size, unity_size, x, y):
    """Unity screen coordinates have y up from the bottom; the desktop has y down from the top, and the client area may be scaled."""
    scale_x = client_size[0] / float(unity_size[0])
    scale_y = client_size[1] / float(unity_size[1])
    return int(round(client_origin[0] + x * scale_x)), int(round(client_origin[1] + (unity_size[1] - y) * scale_y))


def window_for_pid(pid):
    user32 = ctypes.windll.user32
    found = []

    def visit(hwnd, _):
        process = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        if process.value == pid and user32.IsWindowVisible(hwnd) and user32.GetParent(hwnd) == 0:
            found.append(hwnd)
        return True

    callback = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)(visit)
    user32.EnumWindows(callback, 0)
    if not found:
        raise RuntimeError("no visible window for pid %d" % pid)
    return found[0]


def client_geometry(hwnd):
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    return (origin.x, origin.y), (rect.right - rect.left, rect.bottom - rect.top)


def focus(hwnd):
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    time.sleep(SETTLE_SECONDS)
    return user32.GetForegroundWindow() == hwnd


def make_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def click_screen(x, y, hold=CLICK_HOLD_SECONDS):
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    time.sleep(SETTLE_SECONDS)
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(hold)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(SETTLE_SECONDS)


def press_key(name, hold=CLICK_HOLD_SECONDS):
    user32 = ctypes.windll.user32
    code = VIRTUAL_KEYS[name]
    user32.keybd_event(code, 0, 0, 0)
    time.sleep(hold)
    user32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(SETTLE_SECONDS)
