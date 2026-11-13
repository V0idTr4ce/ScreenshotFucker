#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Linux-side runner. Opens a real bash PTY, types each lab box, then either:
  --remote-shot  draw pink bars and wait for ###SFF_ACK###
  (default)      pause so you can screenshot by hand
This file is uploaded to the lab host. It only needs Python 3 stdlib.
"""

import argparse
import json
import os
import re
import select
import signal
import struct
import sys
import threading
import time

if os.name != "nt":
    import fcntl
    import pty
    import termios

YEL = "\033[33m"
GRN = "\033[32m"
CYN = "\033[36m"
RED = "\033[31m"
BOLD = "\033[1m"
RST = "\033[0m"

BAR_RGB = (255, 20, 147)
SHOT_TOKEN_FMT = "###SFF_SHOT %d###"
READY_MARK = "SFF_READY"
SESSION_MARK = "SFF_SESSION_OK"
VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

RE_GSQL_READY = re.compile(r"\w+=[#>][ \t]*$")
RE_GSQL_ANY = re.compile(r"\w+[=()'\"*$^!-][#>][ \t]*$")
RE_SHELL = re.compile(r"[#$]\s*$")
RE_PASS = re.compile(r"(?i)(password:|口令[:：]|密码[:：])\s*$")
ANSI_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
ANSI_CSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ANSI_MISC = re.compile(r"\x1b[()][0-9AB]|\x1b[=><]")
GSQL_BIN = re.compile(r"^gsql(\s|$)")


def note(msg):
    sys.stderr.write(YEL + msg + RST + "\n")
    sys.stderr.flush()


def info(msg):
    sys.stderr.write(CYN + msg + RST + "\n")
    sys.stderr.flush()


def warn(msg):
    sys.stderr.write(RED + msg + RST + "\n")
    sys.stderr.flush()


def subst(text, variables):
    if isinstance(text, str):
        def repl(m):
            key = m.group(1)
            if key not in variables:
                raise ValueError("unknown variable ${%s}" % key)
            return str(variables[key])

        return VAR_RE.sub(repl, text)
    if isinstance(text, list):
        return [subst(x, variables) for x in text]
    if isinstance(text, dict):
        return {k: subst(v, variables) if k != "if" else v for k, v in text.items()}
    return text


def load_lab(path, extra_vars=None):
    with open(path, "r", encoding="utf-8") as f:
        lab = json.load(f)
    variables = {}
    variables.update(lab.get("vars") or {})
    if extra_vars:
        variables.update(extra_vars)
    lab["vars"] = {str(k): str(v) for k, v in variables.items()}
    lab["session"] = subst(lab.get("session") or {}, lab["vars"])
    lab["boxes"] = [subst(b, lab["vars"]) for b in (lab.get("boxes") or [])]
    return lab


def expand_cmds(box):
    default_timeout = box.get("timeout")
    raw = box.get("cmds")
    if raw is None:
        script = box.get("script") or []
        if isinstance(script, str):
            script = script.splitlines()
        raw = [{"text": line} for line in script if str(line).strip() != ""]
    out = []
    for item in raw:
        if isinstance(item, str):
            item = {"text": item}
        cmd = dict(item)
        cmd["text"] = str(cmd.get("text", ""))
        if default_timeout and "timeout" not in cmd:
            cmd["timeout"] = default_timeout
        out.append(cmd)
    return out


def strip_ansi(text):
    text = ANSI_OSC.sub("", text)
    text = ANSI_CSI.sub("", text)
    text = ANSI_MISC.sub("", text)
    return text.replace("\r", "")


def resolve_wait(cmd, in_gsql):
    wait = cmd.get("wait")
    text = (cmd.get("text") or "").strip()
    if wait == "shell":
        if GSQL_BIN.match(text):
            return "gsql"
        return "shell"
    if wait in ("gsql", "gsql_more"):
        if text.startswith("\\") or text.endswith(";") or GSQL_BIN.match(text):
            return "gsql"
        return "gsql_more"
    if GSQL_BIN.match(text):
        return "gsql"
    if text.startswith("\\") or text.endswith(";"):
        return "gsql" if in_gsql or text.startswith("\\") else "gsql"
    if in_gsql:
        return "gsql_more"
    kind = cmd.get("kind")
    if kind == "shell":
        return "shell"
    if in_gsql:
        return "gsql_more"
    return "shell"


def strip_ansi_last_line(plain):
    for ln in reversed(plain.split("\n")):
        if ln.strip():
            return ln.rstrip(" \t")
    return ""


class LiveSession(object):
    def __init__(self, speed=1.0):
        self.speed = max(0.3, float(speed))
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.mark = 0
        self.alive = True
        self.fd = None
        self.pid = None
        self.already_omm = False
        self.in_gsql = False
        self._in_password = False

    def start(self):
        pid, fd = pty.fork()
        if pid == 0:
            env = os.environ.copy()
            env["TERM"] = env.get("TERM") or "xterm-256color"
            os.execvpe("bash", ["bash", "-il"], env)
        self.pid = pid
        self.fd = fd
        try:
            import shutil

            cols, rows = shutil.get_terminal_size()
        except Exception:
            cols, rows = 120, 32
        try:
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except Exception:
            pass
        t = threading.Thread(target=self._reader, name="pty-reader")
        t.daemon = True
        t.start()

    def _reader(self):
        while self.alive:
            try:
                r, _, _ = select.select([self.fd], [], [], 0.1)
            except Exception:
                break
            if not r:
                continue
            try:
                data = os.read(self.fd, 4096)
            except OSError:
                break
            if not data:
                break
            with self.lock:
                self.buf.extend(data)
            try:
                os.write(sys.stdout.fileno(), data)
            except Exception:
                try:
                    sys.stdout.write(data.decode("utf-8", "replace"))
                    sys.stdout.flush()
                except Exception:
                    pass

    def _tail(self, n=1200):
        with self.lock:
            chunk = bytes(self.buf[self.mark :])[-n:]
        return chunk.decode("utf-8", "replace")

    def set_mark(self):
        with self.lock:
            self.mark = len(self.buf)

    def mark_at_current_prompt(self):
        with self.lock:
            data = bytes(self.buf)
        if not data:
            return 0
        trimmed = data.rstrip(b" \t")
        nl = trimmed.rfind(b"\n")
        if nl < 0:
            return 0
        return nl + 1

    def text_since(self, n):
        with self.lock:
            chunk = bytes(self.buf[n:])
        return chunk.decode("utf-8", "replace")

    def wait_prompt(self, kind, timeout=25):
        deadline = time.time() + timeout
        while time.time() < deadline:
            tail = self._tail()
            plain = strip_ansi(tail)
            last = strip_ansi_last_line(plain)
            if (not self._in_password) and RE_PASS.search(last):
                self._handle_password()
                deadline = time.time() + timeout
                continue
            ready = bool(RE_GSQL_READY.search(last))
            in_gsql = bool(RE_GSQL_ANY.search(last))
            if kind == "gsql" and ready:
                return True
            if kind == "gsql_more" and in_gsql:
                return True
            if kind == "any" and (in_gsql or RE_SHELL.search(last)):
                return True
            if kind == "shell" and RE_SHELL.search(last) and not in_gsql:
                return True
            time.sleep(0.05)
        return False

    def _handle_password(self):
        self._in_password = True
        try:
            pw = os.environ.get("OMM_PASSWORD")
            if pw is None:
                try:
                    import getpass

                    pw = getpass.getpass("")
                except Exception:
                    pw = ""
            self.set_mark()
            self.write_all(pw + "\n")
            time.sleep(0.3)
        finally:
            self._in_password = False

    def write_all(self, data):
        if not isinstance(data, bytes):
            data = data.encode("utf-8")
        off = 0
        while off < len(data):
            n = os.write(self.fd, data[off:])
            if n <= 0:
                break
            off += n

    def type_line(self, text):
        self.set_mark()
        self.write_all(text + "\n")

    def silent_line(self, text, wait="shell", timeout=25):
        self.set_mark()
        self.write_all(text + "\n")
        ok = self.wait_prompt(wait, timeout=timeout)
        if wait in ("gsql", "gsql_more"):
            self.in_gsql = True
        return ok

    def send_raw(self, data):
        self.write_all(data)

    def ctrl_l(self):
        self.set_mark()
        self.send_raw(b"\x0c")
        time.sleep(0.12)
        self.wait_prompt("any", timeout=3)

    def _echo_off(self):
        try:
            cur = termios.tcgetattr(self.fd)
            self._termios_saved = [
                cur[0], cur[1], cur[2], cur[3], cur[4], cur[5], list(cur[6])
            ]
            cur[3] = cur[3] & ~termios.ECHO
            termios.tcsetattr(self.fd, termios.TCSANOW, cur)
            return True
        except Exception:
            self._termios_saved = None
            return False

    def _echo_on(self):
        saved = getattr(self, "_termios_saved", None)
        if saved is None:
            return
        try:
            termios.tcsetattr(self.fd, termios.TCSANOW, saved)
        except Exception:
            pass
        self._termios_saved = None

    def ensure_ll_alias(self):
        self._echo_off()
        try:
            self.silent_line("alias ll='ls -lh --color=auto'", wait="shell", timeout=8)
        finally:
            self._echo_on()

    def run_cmd(self, cmd):
        if cmd.get("skip_if") == "already_omm" and self.already_omm:
            return True
        text = cmd["text"]
        wait = resolve_wait(cmd, self.in_gsql)
        self.type_line(text)
        ok = self.wait_prompt(wait, timeout=cmd.get("timeout", 25))
        if text.strip() == "su - omm":
            self.already_omm = True
        if wait in ("gsql", "gsql_more"):
            self.in_gsql = True
        if not ok:
            note("prompt timeout (continuing). Ctrl+C to stop.")
        time.sleep(0.25 / self.speed)
        return ok

    def close(self):
        self.alive = False
        if self.fd is not None:
            try:
                os.write(self.fd, b"\x03")
                time.sleep(0.08)
                os.write(self.fd, b"exit\n")
            except OSError:
                pass
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.pid:
            for _ in range(25):
                try:
                    wpid, _st = os.waitpid(self.pid, os.WNOHANG)
                    if wpid:
                        self.pid = None
                        break
                except OSError:
                    self.pid = None
                    break
                time.sleep(0.04)
            if self.pid:
                try:
                    os.kill(self.pid, signal.SIGKILL)
                    os.waitpid(self.pid, 0)
                except OSError:
                    pass
                self.pid = None


def print_remote_shot_bar():
    cols = 80
    try:
        import shutil

        cols = shutil.get_terminal_size().columns
    except Exception:
        pass
    cols = max(40, min(int(cols), 240))
    r, g, b = BAR_RGB
    seq = "\033[38;2;%d;%d;%dm\033[48;2;%d;%d;%dm" % (r, g, b, r, g, b)
    body = "█" * cols
    sys.stdout.write("\n")
    for _ in range(3):
        sys.stdout.write(seq + body + "\033[0m\n")
    sys.stdout.flush()


def _stty_echo(on):
    try:
        import subprocess

        subprocess.call(
            ["stty", "echo" if on else "-echo"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def finish_remote_shot(n):
    sys.stdout.flush()
    time.sleep(0.08)
    print_remote_shot_bar()
    sys.stdout.write(SHOT_TOKEN_FMT % n)
    sys.stdout.write("\n")
    sys.stdout.flush()
    _stty_echo(False)
    try:
        while True:
            try:
                line = sys.stdin.readline()
            except KeyboardInterrupt:
                return False
            if not line:
                return False
            s = line.strip().lower()
            if s in ("q", "quit", "exit"):
                return False
            if "sff_ack" in s or "lab5_ack" in s:
                return True
    finally:
        _stty_echo(True)


def pause_for_shot(n, total, title, no_pause):
    if no_pause:
        time.sleep(0.2)
        return True
    sys.stdout.write("\n" + YEL + BOLD)
    sys.stdout.write("────────────────────────────────────────────────────────────\n")
    sys.stdout.write("  screenshot the commands and output above this line\n")
    sys.stdout.write("────────────────────────────────────────────────────────────\n")
    sys.stdout.write(RST + GRN + BOLD)
    sys.stdout.write("  box %d / %d: %s\n" % (n, total, title))
    sys.stdout.write("  Enter = next box    q + Enter = quit\n")
    sys.stdout.write(RST)
    sys.stdout.flush()
    try:
        line = sys.stdin.readline()
    except KeyboardInterrupt:
        return False
    if line.strip().lower() in ("q", "quit", "exit"):
        return False
    return True


def run_group(sess, box, do_clear):
    sys.stdout.write("\033[3J\033[2J\033[H")
    sys.stdout.flush()
    if do_clear:
        sess.ctrl_l()
    start = sess.mark_at_current_prompt()
    for cmd in expand_cmds(box):
        sess.run_cmd(cmd)
    time.sleep(0.15)
    return sess.text_since(start)


def _match_when(spec, n):
    spec = spec or {}
    mn = spec.get("min")
    mx = spec.get("max")
    if mn is not None and n < int(mn):
        return False
    if mx is not None and n > int(mx):
        return False
    return True


def run_silent(sess, cmd):
    if cmd.get("skip_if") == "already_omm" and sess.already_omm:
        return True
    wait = resolve_wait(cmd, sess.in_gsql)
    ok = sess.silent_line(cmd["text"], wait=wait, timeout=cmd.get("timeout", 25))
    if (cmd.get("text") or "").strip() == "su - omm":
        sess.already_omm = True
    return ok


def session_open(sess, lab):
    for cmd in lab.get("session", {}).get("open") or []:
        run_silent(sess, cmd)


def prepare_at(sess, lab, start_from):
    note("starting at box %d without running earlier SQL" % start_from)
    if start_from <= 1:
        return
    session_open(sess, lab)
    for rule in lab.get("session", {}).get("prepare_at") or []:
        if _match_when(rule.get("if"), start_from):
            for cmd in rule.get("cmds") or []:
                run_silent(sess, cmd)


def restore_state(sess, lab, start_from):
    note("starting at box %d; restoring session first" % start_from)
    session_open(sess, lab)
    from_cfg = lab.get("session", {}).get("from") or {}
    connect_only_below = int(from_cfg.get("connect_only_below") or 1)
    replay_from = int(from_cfg.get("replay_from") or 1)
    if start_from < connect_only_below:
        for rule in lab.get("session", {}).get("prepare_at") or []:
            if _match_when(rule.get("if"), start_from):
                for cmd in rule.get("cmds") or []:
                    run_silent(sess, cmd)
        return
    for box in lab.get("boxes") or []:
        n = box.get("n")
        if n < replay_from or n >= start_from:
            continue
        for cmd in expand_cmds(box):
            run_silent(sess, cmd)


def print_groups(lab):
    print("lab: %s" % (lab.get("name") or "(unnamed)"))
    print("boxes: %d" % len(lab.get("boxes") or []))
    for box in lab.get("boxes") or []:
        cmds = expand_cmds(box)
        joined = "  |  ".join(c["text"] for c in cmds)
        print("  %2d. %s" % (box["n"], box.get("title") or ""))
        print("      %s" % joined)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run a lab JSON in a live bash/gsql PTY")
    parser.add_argument("--lab", required=True, help="path to lab JSON")
    parser.add_argument("--from", dest="start_from", type=int, default=1)
    parser.add_argument("--at", type=int, default=0)
    parser.add_argument("--speed", type=float, default=0.0)
    parser.add_argument("--no-clear", action="store_true")
    parser.add_argument("--no-pause", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--remote-shot", action="store_true")
    args = parser.parse_args(argv)

    lab = load_lab(args.lab)
    boxes = lab.get("boxes") or []
    if args.list:
        print_groups(lab)
        return 0

    if os.name == "nt":
        print("这段代码在 Linux 实验机上跑。")
        print("Windows 请执行：  python ScreenshotFucker.py")
        return 1

    if args.at and args.start_from != 1:
        warn("--at and --from cannot be combined")
        return 2
    if args.at:
        args.start_from = args.at
    numbers = [b["n"] for b in boxes]
    if args.start_from < 1 or args.start_from > max(numbers):
        warn("box number must be in 1..%d" % max(numbers))
        return 2

    speed = args.speed or float((lab.get("settings") or {}).get("speed") or 1.0)
    do_clear_default = (lab.get("settings") or {}).get("clear_between", True)
    if args.no_clear:
        do_clear_default = False

    info("lab: %s" % (lab.get("name") or args.lab))
    print_groups(lab)
    if args.remote_shot:
        note("local orchestrator will crop this window at the pink bar.")
    else:
        note("each box pauses so you can screenshot, then press Enter.")
    sys.stdout.write("%s\n" % READY_MARK)
    sys.stdout.write("press Enter to start box %d..." % args.start_from)
    sys.stdout.flush()
    try:
        sys.stdin.readline()
    except KeyboardInterrupt:
        print("")
        return 0

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or "?"
    sess = LiveSession(speed=speed)
    sess.already_omm = user == "omm"
    sess.start()
    if not sess.wait_prompt("shell", timeout=12):
        note("did not see a bash prompt, continuing.")
    sess.ensure_ll_alias()
    if args.at:
        prepare_at(sess, lab, args.start_from)
    elif args.start_from > 1:
        restore_state(sess, lab, args.start_from)
    if do_clear_default:
        sess.ctrl_l()
    sys.stdout.write("%s\n" % SESSION_MARK)
    sys.stdout.flush()
    time.sleep(0.08)

    def _cleanup(*_a):
        sess.close()
        sys.exit(1)

    signal.signal(signal.SIGINT, _cleanup)
    total = len(boxes)
    try:
        for box in boxes:
            if box["n"] < args.start_from:
                continue
            do_clear = (box["n"] > args.start_from) and do_clear_default
            run_group(sess, box, do_clear=do_clear)
            if args.remote_shot:
                if not finish_remote_shot(box["n"]):
                    break
                continue
            if not pause_for_shot(box["n"], total, box.get("title") or "", args.no_pause):
                break
    finally:
        sess.close()
    info("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
