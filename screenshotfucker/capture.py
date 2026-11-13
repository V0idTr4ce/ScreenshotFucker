# -*- coding: utf-8 -*-
"""Find the terminal HWND, screenshot it, crop above the pink handshake bar."""

import os
import time

from screenshotfucker.consolewin import _get_console_window, window_title
from screenshotfucker.protocol import BAR_RGB, BAR_TOL

_TERM_HINTS = (
    "windowsterminal",
    "mobaxterm",
    "mintty",
    "wezterm",
    "alacritty",
    "tabby",
    "openconsole",
    "conhost",
    "moba",
    "powershell",
    "pwsh",
    "cmd.exe",
    "windowsterm",
)

_BLACKLIST = (
    "explorer.exe",
    "lockapp.exe",
    "searchhost.exe",
    "searchapp.exe",
    "startmenuexperiencehost.exe",
    "shellexperiencehost.exe",
    "applicationframehost.exe",
    "dwm.exe",
    "textinputhost.exe",
    "widgetservice.exe",
    "widgets.exe",
    "systemsettings.exe",
    "logonui.exe",
    "bingwallpaper",
    "wallpaperengine",
)

_TERM_CLASSES = (
    "cascadia_hosting_window_class",
    "consolewindowclass",
    "mintty",
    "tmobaxtermform",
    "thunderrt6formdc",
    "putty",
    "cygwin",
    "wezterm",
    "alacritty",
    "org.wezfurlong.wezterm",
)

_BAD_CLASSES = (
    "progman",
    "workerw",
    "shell_traywnd",
    "cabinetwclass",
    "windows.ui.core.corewindow",
    "applicationframewindow",
    "foregroundstaging",
    "multitaskingviewframe",
    "notifyiconoverflowwindow",
    "dummydax2.0",
)


def _win_process_table():
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    TH32CS_SNAPPROCESS = 0x2
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == ctypes.c_void_p(-1).value or snap == -1:
        return {}
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    table = {}
    ok = k32.Process32FirstW(snap, ctypes.byref(pe))
    while ok:
        table[int(pe.th32ProcessID)] = (
            int(pe.th32ParentProcessID),
            (pe.szExeFile or "").lower(),
        )
        ok = k32.Process32NextW(snap, ctypes.byref(pe))
    k32.CloseHandle(snap)
    return table


def _windows_for_pid(pid):
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        cpid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(cpid))
        if int(cpid.value) != int(pid):
            return True
        if not user32.IsWindowVisible(hwnd):
            return True
        if user32.IsIconic(hwnd):
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        if w < 200 or h < 120:
            return True
        found.append((w * h, hwnd))
        return True

    user32.EnumWindows(cb, 0)
    found.sort(reverse=True)
    return [hwnd for _area, hwnd in found]


def _window_title(hwnd):
    import ctypes

    user32 = ctypes.windll.user32
    n = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    user32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value or ""


def _class_name(hwnd):
    import ctypes

    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
    return buf.value or ""


def _pid_of_hwnd(hwnd):
    import ctypes
    from ctypes import wintypes

    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _exe_of_pid(pid, table=None):
    if table is None:
        table = _win_process_table()
    return table.get(pid, (0, ""))[1]


def _is_blacklisted(name):
    n = (name or "").lower()
    return any(b in n for b in _BLACKLIST)


def _is_terminal_name(name, title=""):
    blob = ((name or "") + " " + (title or "")).lower()
    return any(h in blob for h in _TERM_HINTS)


def _is_term_class(cls):
    c = (cls or "").lower()
    return any(h in c for h in _TERM_CLASSES)


def _is_bad_class(cls):
    c = (cls or "").lower()
    return any(h in c for h in _BAD_CLASSES)


def _window_rect(hwnd):
    import ctypes
    from ctypes import wintypes

    rect = wintypes.RECT()
    try:
        dwmapi = ctypes.windll.dwmapi
        ok = dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if ok == 0 and rect.right > rect.left and rect.bottom > rect.top:
            return rect.left, rect.top, rect.right, rect.bottom
    except Exception:
        pass
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def _hwnd_usable(hwnd):
    if not hwnd:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    if not user32.IsWindow(hwnd):
        return False
    if not user32.IsWindowVisible(hwnd):
        return False
    if user32.IsIconic(hwnd):
        return False
    try:
        left, top, right, bottom = _window_rect(hwnd)
    except Exception:
        return False
    w, h = right - left, bottom - top
    return w >= 240 and h >= 140


def _hwnd_is_terminal(hwnd, table=None):
    if not _hwnd_usable(hwnd):
        return False
    cls = _class_name(hwnd)
    if _is_bad_class(cls):
        return False
    pid = _pid_of_hwnd(hwnd)
    name = _exe_of_pid(pid, table)
    if _is_blacklisted(name):
        return False
    title = _window_title(hwnd)
    return _is_term_class(cls) or _is_terminal_name(name, title)


def describe_hwnd(hwnd):
    if not hwnd:
        return "none"
    table = _win_process_table()
    pid = _pid_of_hwnd(hwnd)
    name = _exe_of_pid(pid, table)
    title = _window_title(hwnd)
    cls = _class_name(hwnd)
    return "hwnd=%s pid=%s exe=%s class=%s title=%r" % (
        hwnd, pid, name, cls, title[:80]
    )


def find_terminal_hwnd():
    if os.name != "nt":
        return None
    import ctypes

    user32 = ctypes.windll.user32
    table = _win_process_table()
    candidates = []

    con = _get_console_window()
    if con:
        try:
            root = user32.GetAncestor(con, 2) or con
        except Exception:
            root = con
        if _hwnd_is_terminal(root, table):
            candidates.append((110, root, "console"))

    fg = user32.GetForegroundWindow()
    if fg and _hwnd_is_terminal(fg, table):
        candidates.append((200, fg, "foreground"))

    pid = os.getpid()
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        ppid, name = table.get(pid, (0, ""))
        if _is_blacklisted(name):
            pid = ppid
            continue
        for hwnd in _windows_for_pid(pid):
            if not _hwnd_is_terminal(hwnd, table):
                continue
            title = _window_title(hwnd)
            s = 100
            if _is_terminal_name(name, title) or _is_term_class(_class_name(hwnd)):
                s = 140
            candidates.append((s, hwnd, name))
        pid = ppid

    candidates.sort(key=lambda t: t[0], reverse=True)
    seen_hwnd = set()
    for _score, hwnd, _src in candidates:
        if hwnd in seen_hwnd:
            continue
        seen_hwnd.add(hwnd)
        if _hwnd_is_terminal(hwnd, table):
            return hwnd
    return None


def find_hwnd_by_title(substr):
    if os.name != "nt" or not substr:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    needle = substr.lower()
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _lp):
        if not user32.IsWindow(hwnd):
            return True
        title = (_window_title(hwnd) or "").lower()
        if needle in title and "grok" not in title:
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def _restore_window(hwnd, pixel_w=1280, pixel_h=980):
    import ctypes

    user32 = ctypes.windll.user32
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
        user32.ShowWindow(hwnd, 9)
        time.sleep(0.12)
    left, top, right, bottom = _window_rect(hwnd)
    w, h = right - left, bottom - top
    if left <= -10000 or top <= -10000 or w < 80 or h < 720:
        user32.ShowWindow(hwnd, 9)
        user32.SetWindowPos(hwnd, 0, 40, 20, pixel_w, pixel_h, 0x0040)
        time.sleep(0.15)
    return True


def _mean_luma(img):
    small = img.resize((64, 36))
    pix = list(small.getdata())
    if not pix:
        return 0
    s = 0
    for p in pix:
        s += (p[0] * 299 + p[1] * 587 + p[2] * 114) / 1000.0
    return s / len(pix)


def _print_window(hwnd, w, h):
    try:
        import ctypes
        from ctypes import wintypes
        from PIL import Image
    except Exception:
        return None
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd_dc = user32.GetWindowDC(hwnd)
    if not hwnd_dc:
        return None
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bmp = gdi32.CreateCompatibleBitmap(hwnd_dc, w, h)
    gdi32.SelectObject(mem_dc, bmp)
    if user32.PrintWindow(hwnd, mem_dc, 2) == 0:
        user32.PrintWindow(hwnd, mem_dc, 0)

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mem_dc, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)
    img = Image.frombuffer("RGBX", (w, h), buf, "raw", "BGRX", 0, 1)
    return img.convert("RGB")


def capture_hwnd(hwnd, pixel_w=1280, pixel_h=980):
    from PIL import ImageGrab

    if not hwnd:
        return None
    try:
        _restore_window(hwnd, pixel_w, pixel_h)
    except Exception:
        pass
    if not _hwnd_usable(hwnd):
        return None
    left, top, right, bottom = _window_rect(hwnd)
    w, h = right - left, bottom - top
    if w < 50 or h < 50:
        return None
    try:
        import ctypes

        user32 = ctypes.windll.user32
        fg = user32.GetForegroundWindow()
        if fg != hwnd and _hwnd_is_terminal(hwnd):
            user32.SetForegroundWindow(hwnd)
            time.sleep(0.12)
        else:
            time.sleep(0.05)
        left, top, right, bottom = _window_rect(hwnd)
        w, h = right - left, bottom - top
    except Exception:
        time.sleep(0.05)
    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        if img and _mean_luma(img) > 3:
            return img.convert("RGB")
    except TypeError:
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        if img and _mean_luma(img) > 3:
            return img.convert("RGB")
    except Exception:
        pass
    printed = _print_window(hwnd, w, h)
    if printed is not None:
        return printed
    return None


def grab_screen():
    from PIL import ImageGrab

    try:
        img = ImageGrab.grab(all_screens=True)
    except TypeError:
        img = ImageGrab.grab()
    except Exception:
        return None
    if img is None:
        return None
    return img.convert("RGB")


def _match(p, rgb, tol):
    return (
        abs(p[0] - rgb[0]) <= tol
        and abs(p[1] - rgb[1]) <= tol
        and abs(p[2] - rgb[2]) <= tol
    )


def _is_bar_px(p, rgb, tol):
    if _match(p, rgb, tol):
        return True
    r, g, b = p[0], p[1], p[2]
    return r >= 180 and b >= 70 and g <= 110 and (r - g) >= 70


def _luma(p):
    return (p[0] * 299 + p[1] * 587 + p[2] * 114) / 1000.0


def _row_mark_ratio(pix, y, w, rgb, tol):
    hit = 0
    n = 0
    step = max(1, w // 360)
    for x in range(0, w, step):
        n += 1
        if _is_bar_px(pix[x, y], rgb, tol):
            hit += 1
    return hit / float(n) if n else 0.0


def _band_xrange(pix, y0, y1, w, rgb, tol):
    y = (y0 + y1) // 2
    xs = []
    for x in range(w):
        if _is_bar_px(pix[x, y], rgb, tol):
            xs.append(x)
    if not xs:
        return 0, w
    return max(0, xs[0] - 6), min(w, xs[-1] + 6)


def _row_var(pix, y, x0, x1):
    vals = []
    for x in range(x0, x1, 3):
        vals.append(_luma(pix[x, y]))
    if not vals:
        return 0.0
    return max(vals) - min(vals)


def _row_mean_luma(pix, y, x0, x1):
    s = 0.0
    n = 0
    for x in range(x0, x1, 4):
        s += _luma(pix[x, y])
        n += 1
    return s / n if n else 0.0


def crop_by_bars(img, rgb=BAR_RGB, tol=BAR_TOL):
    pix = img.load()
    w, h = img.size
    bands = []
    y = 0
    while y < h:
        if _row_mark_ratio(pix, y, w, rgb, tol) < 0.32:
            y += 1
            continue
        y0 = y
        while y < h and _row_mark_ratio(pix, y, w, rgb, tol) >= 0.28:
            y += 1
        y1 = y
        if 2 <= (y1 - y0) <= 80:
            x0, x1 = _band_xrange(pix, y0, y1, w, rgb, tol)
            if x1 - x0 >= 120:
                bands.append((y0, y1, x0, x1))
    if not bands:
        return None, "no-bar"
    y0, y1, x0, x1 = bands[-1]
    prev_bar_bot = bands[-2][1] if len(bands) >= 2 else None
    last_text = None
    first_text = None
    empty_run = 0
    light_run = 0
    yy = y0 - 1
    stop_at = prev_bar_bot if prev_bar_bot is not None else -1
    while yy > stop_at:
        if _row_mark_ratio(pix, yy, w, rgb, tol) >= 0.32:
            stop_at = yy
            break
        mean = _row_mean_luma(pix, yy, x0, x1)
        var = _row_var(pix, yy, x0, x1)
        if mean > 140 and var < 25:
            light_run += 1
            if light_run >= 3 and first_text is not None:
                break
        else:
            light_run = 0
        if var > 16:
            if last_text is None:
                last_text = yy
            first_text = yy
            empty_run = 0
        else:
            empty_run += 1
            if first_text is not None and empty_run > 80:
                break
        yy -= 1
    if first_text is None:
        return None, "no-text"
    top = max(0, first_text - 8)
    if stop_at >= 0:
        top = max(stop_at + 1, top)
    bot = min(y0, (last_text or y0) + 8)
    if bot - top < 20:
        return None, "too-small"
    cropped = img.crop((x0, top, x1, bot))
    return cropped, "ok"


def _write_shot(full, cropped, out_dir, n, save_full, why):
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, "%02d.png" % n)
    if save_full:
        full.save(os.path.join(out_dir, "%02d_full.png" % n), "PNG")
    cropped.save(png_path, "PNG")
    return png_path, why


def save_shot(img, out_dir, n, save_full=False):
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, "%02d.png" % n)
    if save_full:
        img.save(os.path.join(out_dir, "%02d_full.png" % n), "PNG")
    cropped, why = crop_by_bars(img)
    if cropped is None:
        img.save(png_path, "PNG")
        return png_path, "fallback:%s" % why
    cropped.save(png_path, "PNG")
    return png_path, "ok"


def grab_one(hwnd, out_dir, n, save_full, pixel_w=1280, pixel_h=980):
    titled = find_hwnd_by_title(window_title())
    live = find_terminal_hwnd()
    if titled:
        hwnd = titled
    elif live:
        hwnd = live
    last_window = None
    for attempt in range(3):
        if attempt:
            time.sleep(0.22)
        if hwnd:
            img = capture_hwnd(hwnd, pixel_w, pixel_h)
            if img is not None:
                last_window = img
                cropped, why = crop_by_bars(img)
                if cropped is not None:
                    return _write_shot(img, cropped, out_dir, n, save_full, why)
        screen = grab_screen()
        if screen is not None:
            cropped, why = crop_by_bars(screen)
            if cropped is not None:
                return _write_shot(screen, cropped, out_dir, n, save_full, "screen-" + why)
    if last_window is not None:
        return save_shot(last_window, out_dir, n, save_full=save_full)
    return None, "capture-failed"


def test_crop_synthetic(out_dir):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (980, 420), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 980, 36], fill=(230, 230, 230))
    draw.text((20, 80), "db_em=> CREATE INDEX people_phone_uk ON people (peoplephone);", fill=(220, 220, 220))
    draw.text((20, 110), "CREATE INDEX", fill=(220, 220, 220))
    draw.rectangle([12, 330, 968, 372], fill=BAR_RGB)
    cropped, why = crop_by_bars(img)
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, "00_synthetic_full.png"), "PNG")
    if cropped is None:
        return 1, "synthetic crop failed: %s" % why
    path = os.path.join(out_dir, "00_synthetic.png")
    cropped.save(path, "PNG")
    if cropped.size[1] > 280 or cropped.size[1] < 40:
        return 1, "synthetic crop height odd: %s" % (cropped.size,)
    cpix = cropped.load()
    cw, ch = cropped.size
    pink = 0
    sample = 0
    for y in range(ch):
        for x in range(0, cw, 8):
            sample += 1
            if _is_bar_px(cpix[x, y], BAR_RGB, BAR_TOL):
                pink += 1
    if sample and pink / float(sample) > 0.08:
        return 1, "synthetic crop still has pink bar"
    return 0, path
