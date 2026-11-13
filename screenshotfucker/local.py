# -*- coding: utf-8 -*-
"""Windows/local orchestrator: upload runner + lab JSON, SSH -tt, crop each box."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

from screenshotfucker.capture import describe_hwnd, find_terminal_hwnd, grab_one
from screenshotfucker.consolewin import (
    clear_local_console_buffer,
    enable_vt,
    scroll_console_to_top,
    setup_console_geometry,
    window_title,
)
from screenshotfucker.protocol import ACK_TOKEN, READY_MARK, SESSION_MARK
from screenshotfucker.sshutil import (
    close_control_master,
    ensure_askpass,
    ensure_openssh_path,
    eprint,
    open_control_master,
    scp_lf,
    _password_auth_opts,
)

SHOT_TOKEN_RE = re.compile(br"###SFF_SHOT\s+(\d+)###")
READY_MARK_B = READY_MARK.encode("ascii")
SESSION_MARK_B = SESSION_MARK.encode("ascii")


def here():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def term_size():
    try:
        cols, rows = shutil.get_terminal_size()
    except Exception:
        cols, rows = 120, 32
    cols = max(80, min(int(cols), 240))
    rows = max(24, min(int(rows), 80))
    return cols, rows


def upload_payload(user, host, ctl, lab_path):
    remote_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "remote_runner.py")
    if not os.path.isfile(remote_py):
        eprint("找不到 screenshotfucker/remote_runner.py")
        return False
    if not os.path.isfile(lab_path):
        eprint("missing lab file: %s" % lab_path)
        return False
    eprint("uploading remote_runner.py ...")
    if not scp_lf(remote_py, "%s@%s:/tmp/sff_remote.py" % (user, host), user, host, ctl):
        return False
    eprint("uploading lab JSON ...")
    if not scp_lf(lab_path, "%s@%s:/tmp/sff_lab.json" % (user, host), user, host, ctl):
        return False
    return True


def _forward_keys(proc, stop_evt, block_evt):
    if os.name != "nt":
        return
    try:
        import msvcrt
    except Exception:
        return
    while not stop_evt.is_set():
        if not msvcrt.kbhit():
            time.sleep(0.02)
            continue
        ch = msvcrt.getch()
        if ch in (b"\x00", b"\xe0"):
            if msvcrt.kbhit():
                msvcrt.getch()
            continue
        if ch == b"\x03":
            stop_evt.set()
            try:
                proc.terminate()
            except Exception:
                pass
            break
        if block_evt.is_set():
            continue
        if ch == b"\r":
            ch = b"\n"
        try:
            proc.stdin.write(ch)
            proc.stdin.flush()
        except Exception:
            break


def run_remote_session(user, host, ctl, remote_args, out_dir, hwnd, save_full, settings=None):
    settings = settings or {}
    pixel_w = int(settings.get("window_width") or 1280)
    pixel_h = int(settings.get("window_height") or 980)
    cols, rows = term_size()
    extra = " ".join(remote_args)
    remote = (
        "stty cols %d rows %d 2>/dev/null; "
        "export COLUMNS=%d LINES=%d COLORTERM=truecolor "
        "PYTHONIOENCODING=utf-8 TERM=${TERM:-xterm-256color}; "
        "if command -v python3 >/dev/null 2>&1; then PY=python3; "
        "elif command -v python >/dev/null 2>&1; then PY=python; "
        "else echo no-python3; exit 1; fi; "
        "exec $PY -u /tmp/sff_remote.py --lab /tmp/sff_lab.json --remote-shot %s"
        % (cols, rows, cols, rows, extra)
    )
    cmd = [
        "ssh", "-tt",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "RequestTTY=force",
        "-o", "ServerAliveInterval=30",
    ]
    if ctl:
        cmd += ["-o", "ControlPath=" + ctl, "-o", "BatchMode=yes"]
    else:
        cmd += _password_auth_opts(ctl)
    cmd += ["%s@%s" % (user, host), remote]
    eprint("remote session started. each box is captured at the pink bar. Ctrl+C stops.")
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    stop_evt = threading.Event()
    block_evt = threading.Event()
    t_in = threading.Thread(
        target=_forward_keys, args=(proc, stop_evt, block_evt), daemon=True
    )
    t_in.start()

    buf = b""
    saved = []
    capture_failed = False
    started = False
    try:
        while True:
            chunk = proc.stdout.read(4096)
            if not chunk:
                break
            try:
                os.write(sys.stdout.fileno(), chunk)
            except Exception:
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
            buf += chunk
            if len(buf) > 16384:
                buf = buf[-8192:]
            if (not started) and READY_MARK_B in buf:
                started = True
                try:
                    proc.stdin.write(b"\n")
                    proc.stdin.flush()
                except Exception:
                    pass
                clear_local_console_buffer()
            if SESSION_MARK_B in buf:
                buf = buf.replace(SESSION_MARK_B, b"")
                clear_local_console_buffer()
            if b"###SFF_SHOT" in buf:
                block_evt.set()
            while True:
                m = SHOT_TOKEN_RE.search(buf)
                if not m:
                    break
                n = int(m.group(1))
                buf = buf[m.end():]
                block_evt.set()
                scroll_console_to_top()
                time.sleep(0.28)
                scroll_console_to_top()
                try:
                    path, why = grab_one(
                        hwnd, out_dir, n, save_full, pixel_w=pixel_w, pixel_h=pixel_h
                    )
                    if path:
                        saved.append(path)
                        try:
                            with open(
                                os.path.join(out_dir, "progress.log"),
                                "a",
                                encoding="utf-8",
                            ) as lf:
                                lf.write("saved %d %s %s\n" % (n, path, why))
                        except Exception:
                            pass
                    else:
                        capture_failed = True
                        eprint("box %d screenshot failed: %s" % (n, why))
                except Exception as exc:
                    capture_failed = True
                    eprint("box %d screenshot error: %s" % (n, exc))
                try:
                    proc.stdin.write((ACK_TOKEN + "\n").encode("ascii"))
                    proc.stdin.flush()
                except Exception:
                    pass
                time.sleep(0.12)
                clear_local_console_buffer()
                time.sleep(0.05)
                clear_local_console_buffer()
                block_evt.clear()
    except KeyboardInterrupt:
        eprint("interrupted.")
        try:
            proc.terminate()
        except Exception:
            pass
    finally:
        stop_evt.set()
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    return proc.returncode or (1 if capture_failed else 0), saved


def collect_remote_args(args):
    out = []
    if args.start_from and args.start_from != 1:
        out += ["--from", str(args.start_from)]
    if args.at:
        out += ["--at", str(args.at)]
    if args.speed and args.speed != 0:
        out += ["--speed", str(args.speed)]
    if args.no_clear:
        out.append("--no-clear")
    return out


def require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageGrab  # noqa: F401
    except ImportError:
        eprint("Pillow is required on this machine:")
        eprint("  python -m pip install pillow")
        sys.exit(1)


def run_shot_test(out_dir, save_full, settings=None):
    from screenshotfucker.capture import grab_one, test_crop_synthetic
    from screenshotfucker.protocol import BAR_RGB

    enable_vt(settings)
    require_pillow()
    syn, syn_msg = test_crop_synthetic(out_dir)
    eprint("synthetic crop: %s" % syn_msg)
    hwnd = find_terminal_hwnd()
    if hwnd is None:
        eprint("no terminal window for live test.")
        return syn
    eprint("window: %s" % describe_hwnd(hwnd))
    os.makedirs(out_dir, exist_ok=True)
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.write("\033[32mdb_em=>\033[0m CREATE INDEX people_phone_uk ON people (peoplephone);\n")
    sys.stdout.write("CREATE INDEX\n")
    r, g, b = BAR_RGB
    cols, _rows = term_size()
    seq = "\033[38;2;%d;%d;%dm\033[48;2;%d;%d;%dm" % (r, g, b, r, g, b)
    bar = seq + ("█" * cols) + "\033[0m\n"
    sys.stdout.write("\n" + bar + bar + bar)
    sys.stdout.write("###SFF_SHOT 0###\n")
    sys.stdout.flush()
    time.sleep(0.28)
    pixel_w = int((settings or {}).get("window_width") or 1280)
    pixel_h = int((settings or {}).get("window_height") or 980)
    path, why = grab_one(hwnd, out_dir, 0, save_full=True, pixel_w=pixel_w, pixel_h=pixel_h)
    if path:
        eprint("live test: %s (%s)" % (path, why))
    else:
        eprint("live capture failed: %s" % why)
    return syn


def run_local(args, lab_path, host, user, password, out_dir, settings):
    require_pillow()
    if not ensure_openssh_path():
        eprint("ssh/scp not found. Install OpenSSH Client.")
        return 1
    if password:
        ensure_askpass(password)
    elif os.environ.get("SFF_SSH_PASS") or os.environ.get("LAB_SSH_PASS"):
        ensure_askpass(os.environ.get("SFF_SSH_PASS") or os.environ.get("LAB_SSH_PASS"))

    os.environ["SFF_WINDOW_TITLE"] = "%s@%s" % (user, host)
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleTitleW(os.environ["SFF_WINDOW_TITLE"])
    except Exception:
        pass
    enable_vt(settings)
    setup_console_geometry(settings)

    eprint("SSH %s@%s  lab=%s  shots=%s" % (user, host, lab_path, out_dir))
    eprint("keep this window visible. title = %s" % window_title())
    hwnd = find_terminal_hwnd()
    if hwnd is None:
        eprint("terminal HWND not found yet; will search the screen for the pink bar.")
    else:
        eprint("capture window: %s" % describe_hwnd(hwnd))

    ctl = os.path.join(tempfile.gettempdir(), "sff_ssh_%d" % os.getpid())
    if os.name == "nt":
        opened = False
        ctl = None
    else:
        ctl = ctl.replace("\\", "/")
        opened = open_control_master(user, host, ctl)
        if not opened:
            ctl = None
    try:
        if not upload_payload(user, host, ctl, lab_path):
            eprint("upload failed.")
            return 1
        remote_args = collect_remote_args(args)
        rc, saved = run_remote_session(
            user, host, ctl, remote_args, out_dir, hwnd, args.save_full, settings
        )
        eprint("finished. saved %d shots in %s" % (len(saved), out_dir))
        return rc
    finally:
        if ctl:
            close_control_master(user, host, ctl)
