# -*- coding: utf-8 -*-
"""Windows console: title, size, QuickEdit off, clear, pin viewport to first lines."""

import os
import time

DEFAULT_COLS = 120
DEFAULT_ROWS = 52
DEFAULT_BUF_ROWS = 800
DEFAULT_PIXEL_W = 1280
DEFAULT_PIXEL_H = 980

SKIP_HINTS = (
    "###sff",
    "###lab5",
    "welcome to",
    "system information",
    "system load",
    "processes:",
    "memory used",
    "swap used",
    "usage on",
    "ip address",
    "users online",
    "authorized users",
    "last login",
    "alias ll",
    "non-ssl connection",
    "type \"help\"",
    "gsql (",
    "sff_ready",
    "sff_session_ok",
    "sff_ack",
)

HIT_HINTS = (
    "db_em=",
    "sd_db=",
    "sc_db=",
    "postgres=",
    "opengauss=#",
    "opengauss=>",
    "create ",
    "alter ",
    "select ",
    "insert ",
    "set role",
    "set search",
    "grant ",
    "refresh ",
    "\\c ",
    "\\d ",
    "echo ",
    "hostname",
    "whoami",
    "uname ",
    "date",
)


def window_title():
    return os.environ.get("SFF_WINDOW_TITLE") or "ScreenshotFucker"


def enable_vt(settings=None):
    if os.name != "nt":
        return
    settings = settings or {}
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            kernel32.SetConsoleMode(h, mode.value | 0x0004 | 0x0008)
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
        hin = kernel32.GetStdHandle(-10)
        imode = ctypes.c_uint()
        if kernel32.GetConsoleMode(hin, ctypes.byref(imode)):
            kernel32.SetConsoleMode(hin, (imode.value | 0x0080) & ~0x0040)
        try:
            kernel32.SetConsoleTitleW(window_title())
        except Exception:
            pass
        setup_console_geometry(settings)
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _coord(x, y):
    import ctypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    return COORD(int(x), int(y))


def _small_rect(left, top, right, bottom):
    import ctypes

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [
            ("Left", ctypes.c_short),
            ("Top", ctypes.c_short),
            ("Right", ctypes.c_short),
            ("Bottom", ctypes.c_short),
        ]

    return SMALL_RECT(int(left), int(top), int(right), int(bottom))


def _console_info(h=None):
    import ctypes
    from ctypes import wintypes

    class COORD(ctypes.Structure):
        _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

    class SMALL_RECT(ctypes.Structure):
        _fields_ = [
            ("Left", ctypes.c_short),
            ("Top", ctypes.c_short),
            ("Right", ctypes.c_short),
            ("Bottom", ctypes.c_short),
        ]

    class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
        _fields_ = [
            ("dwSize", COORD),
            ("dwCursorPosition", COORD),
            ("wAttributes", wintypes.WORD),
            ("srWindow", SMALL_RECT),
            ("dwMaximumWindowSize", COORD),
        ]

    kernel32 = ctypes.windll.kernel32
    if h is None:
        h = kernel32.GetStdHandle(-11)
    info = CONSOLE_SCREEN_BUFFER_INFO()
    if not kernel32.GetConsoleScreenBufferInfo(h, ctypes.byref(info)):
        return None
    return h, info


def _get_console_window():
    import ctypes

    for dll_name in ("kernel32", "user32"):
        try:
            dll = getattr(ctypes.windll, dll_name)
            fn = getattr(dll, "GetConsoleWindow", None)
            if fn is None:
                continue
            fn.restype = ctypes.c_void_p
            fn.argtypes = []
            val = fn()
            if val:
                return int(val)
        except Exception:
            continue
    return None


def setup_console_geometry(settings=None):
    """Tall visible window, long buffer so overflow keeps the first lines."""
    if os.name != "nt":
        return
    settings = settings or {}
    cols = int(settings.get("window_cols") or settings.get("cols") or DEFAULT_COLS)
    win_rows = int(settings.get("window_rows") or settings.get("rows") or DEFAULT_ROWS)
    buf_rows = int(settings.get("buffer_rows") or DEFAULT_BUF_ROWS)
    pixel_w = int(settings.get("window_width") or settings.get("width") or DEFAULT_PIXEL_W)
    pixel_h = int(settings.get("window_height") or settings.get("height") or DEFAULT_PIXEL_H)
    try:
        import ctypes

        got = _console_info()
        if not got:
            return
        h, info = got
        kernel32 = ctypes.windll.kernel32
        max_w = max(80, int(info.dwMaximumWindowSize.X) or cols)
        max_h = max(24, int(info.dwMaximumWindowSize.Y) or win_rows)
        cols = max(80, min(int(cols), max_w))
        win_rows = max(30, min(int(win_rows), max_h))
        buf_rows = max(win_rows + 20, int(buf_rows))
        cur_w = max(1, info.dwSize.X)
        cur_h = max(1, info.dwSize.Y)
        tmp = _small_rect(0, 0, min(cols, cur_w) - 1, min(win_rows, cur_h) - 1)
        kernel32.SetConsoleWindowInfo(h, True, ctypes.byref(tmp))
        kernel32.SetConsoleScreenBufferSize(h, _coord(cols, buf_rows))
        vis = _small_rect(0, 0, cols - 1, win_rows - 1)
        kernel32.SetConsoleWindowInfo(h, True, ctypes.byref(vis))
        hwnd = _get_console_window()
        if hwnd:
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 40, 20, pixel_w, pixel_h, 0x0040)
    except Exception:
        pass


def scroll_console_to_top(hit=None, skip=None):
    """Pin the visible window to the first real command line. Overflow stays below."""
    if os.name != "nt":
        return False
    skip = tuple(s.lower() for s in (skip or SKIP_HINTS))
    _ = hit
    try:
        import ctypes
        from ctypes import wintypes

        got = _console_info()
        if not got:
            return False
        h, info = got
        kernel32 = ctypes.windll.kernel32
        win_h = info.srWindow.Bottom - info.srWindow.Top
        win_w = info.srWindow.Right - info.srWindow.Left
        if win_h < 8 or win_w < 20:
            return False
        cols = max(1, int(info.dwSize.X))
        last_y = min(int(info.dwCursorPosition.Y) + 2, int(info.dwSize.Y) - 1)
        first_content = None
        for y in range(0, last_y + 1):
            buf = ctypes.create_unicode_buffer(cols + 1)
            n = wintypes.DWORD(0)
            kernel32.ReadConsoleOutputCharacterW(
                h, buf, cols, _coord(0, y), ctypes.byref(n)
            )
            line = (buf.value or "").strip().lower()
            if not line:
                continue
            if any(s in line for s in skip):
                continue
            first_content = y
            break
        top = first_content or 0
        if top + win_h >= info.dwSize.Y:
            top = max(0, info.dwSize.Y - 1 - win_h)
        rect = _small_rect(0, top, win_w, top + win_h)
        return bool(kernel32.SetConsoleWindowInfo(h, True, ctypes.byref(rect)))
    except Exception:
        return False


def clear_local_console_buffer():
    if os.name != "nt":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        got = _console_info()
        if not got:
            return False
        h, info = got
        kernel32 = ctypes.windll.kernel32
        cols = max(1, int(info.dwSize.X))
        rows = max(1, int(info.dwSize.Y))
        n = cols * rows
        written = wintypes.DWORD(0)
        origin = _coord(0, 0)
        kernel32.FillConsoleOutputCharacterW(
            h, ctypes.c_wchar(" "), n, origin, ctypes.byref(written)
        )
        kernel32.FillConsoleOutputAttribute(
            h, info.wAttributes, n, origin, ctypes.byref(written)
        )
        kernel32.SetConsoleCursorPosition(h, origin)
        scroll_console_to_top()
        return True
    except Exception:
        return False


def console_class_name():
    if os.name != "nt":
        return ""
    try:
        import ctypes

        hwnd = _get_console_window()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        return buf.value or ""
    except Exception:
        return ""


def running_in_conhost():
    cls = console_class_name().lower()
    return "consolewindowclass" in cls
