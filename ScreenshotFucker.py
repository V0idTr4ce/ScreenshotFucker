#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ScreenshotFucker：唯一入口。直接运行：python ScreenshotFucker.py"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

EXAMPLE_CONFIG = os.path.join(HERE, "config.example.json")
DEFAULT_CONFIG = os.path.join(HERE, "config.json")


def eprint(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def load_config(path):
    if not path or not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit("配置文件必须是 JSON 对象：%s" % path)
    return data


def ensure_config(path):
    if os.path.isfile(path):
        return load_config(path), False
    if os.path.isfile(EXAMPLE_CONFIG):
        config = load_config(EXAMPLE_CONFIG)
        for key in ("host", "user", "password"):
            config[key] = ""
        save_config(path, config)
        eprint("已根据 config.example.json 生成 config.json")
        return config, True
    return {}, False


def save_config(path, config):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")


def resolve_lab_path(value, config):
    raw = value or config.get("lab") or os.path.join("labs", "opengauss-e5.json")
    if os.path.isfile(raw):
        return os.path.abspath(raw)
    cand = os.path.join(HERE, raw)
    if os.path.isfile(cand):
        return os.path.abspath(cand)
    raise SystemExit("找不到实验 JSON：%s" % raw)


def merge_settings(lab, config, args):
    s = dict(lab.get("settings") or {})
    win = config.get("window") or {}
    if win.get("cols"):
        s["window_cols"] = win["cols"]
    if win.get("rows"):
        s["window_rows"] = win["rows"]
    if win.get("width"):
        s["window_width"] = win["width"]
    if win.get("height"):
        s["window_height"] = win["height"]
    if args.speed:
        s["speed"] = args.speed
    elif config.get("speed"):
        s["speed"] = config["speed"]
    return s


def should_relaunch(argv):
    if os.name != "nt":
        return False
    if os.environ.get("SFF_IN_CONHOST") == "1":
        return False
    skip = {
        "--list", "--check", "--shot-test", "--help", "-h",
        "--on-server", "--no-relaunch",
    }
    if any(a in skip for a in argv):
        return False
    try:
        from screenshotfucker.consolewin import running_in_conhost

        if running_in_conhost():
            return False
    except Exception:
        pass
    return True


def relaunch_in_conhost():
    conhost = shutil.which("conhost.exe") or os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "System32", "conhost.exe"
    )
    cmd_exe = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe"
    )
    if not os.path.isfile(conhost) or not os.path.isfile(cmd_exe):
        eprint("找不到 conhost.exe，继续在当前窗口运行。")
        return False
    rest = [a for a in sys.argv[1:] if a != "--no-relaunch"]
    py_cmd = subprocess.list2cmdline(
        [sys.executable, "-u", os.path.abspath(sys.argv[0]), "--no-relaunch"] + rest
    )
    inner = " & ".join(
        [
            "chcp 65001 >nul",
            "cd /d %s" % subprocess.list2cmdline([HERE]),
            "set SFF_IN_CONHOST=1",
            "set PYTHONUNBUFFERED=1",
            py_cmd,
        ]
    )
    eprint("正在打开专用控制台窗口（粉红边界条必须在 conhost 里才能被截到）...")
    subprocess.Popen(
        [conhost, cmd_exe, "/k", inner],
        cwd=HERE,
        close_fds=True,
    )
    return True


def build_parser():
    p = argparse.ArgumentParser(
        prog="ScreenshotFucker",
        description="在真实终端里按 JSON 灰框自动敲命令，并逐框截图。直接运行：python ScreenshotFucker.py",
    )
    p.add_argument("--lab", default="", help="实验 JSON，默认读 config.json 里的 lab")
    p.add_argument("--config", default="", help="配置文件，默认 ./config.json")
    p.add_argument("--host", default="", help="SSH 主机")
    p.add_argument("--user", default="", help="SSH 用户")
    p.add_argument("--from", dest="start_from", type=int, default=1, help="从第 N 框开始，可回放前面的框")
    p.add_argument("--at", type=int, default=0, help="从第 N 框开始，不执行前面的语句")
    p.add_argument("--speed", type=float, default=0.0, help="越大越快，例如 2")
    p.add_argument("--no-clear", action="store_true", help="框与框之间不清屏")
    p.add_argument("--list", action="store_true", help="只列出全部灰框")
    p.add_argument("--check", action="store_true", help="校验实验 JSON")
    p.add_argument("--shot-dir", default="", help="截图目录，默认 ./shots")
    p.add_argument("--shot-test", action="store_true", help="不连服务器，只测本机裁切")
    p.add_argument("--save-full", action="store_true", help="额外保存未裁切的 NN_full.png")
    p.add_argument("--auto", action="store_true", help="不提问，只用配置文件和环境变量")
    p.add_argument("--on-server", action="store_true", help="已在 Linux 实验机上，不走 SSH")
    p.add_argument("--no-relaunch", action="store_true", help="不要再开 conhost 窗口")
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(argv)

    if should_relaunch(sys.argv[1:]):
        if relaunch_in_conhost():
            return 0

    if args.config:
        if not os.path.isfile(args.config):
            raise SystemExit("找不到配置文件：%s" % args.config)
        config, created = load_config(args.config), False
    else:
        config, created = ensure_config(DEFAULT_CONFIG)

    from screenshotfucker.labfile import LabError, check_lab, load_lab, print_groups

    try:
        lab_path = resolve_lab_path(args.lab, config)
    except SystemExit:
        if created:
            eprint("请先编辑 config.json 里的 host / user / lab，然后再次运行：")
            eprint("  python ScreenshotFucker.py")
        raise

    extra_vars = dict(config.get("vars") or {})
    try:
        lab = load_lab(lab_path, extra_vars=extra_vars)
    except LabError as exc:
        eprint("实验 JSON 有误：%s" % exc)
        return 1

    if args.check:
        errs = check_lab(lab)
        print("lab: %s" % lab_path)
        print("boxes: %d  vars: %s" % (len(lab.get("boxes") or []), ", ".join(lab.get("vars") or {})))
        if errs:
            for e in errs:
                print("ERROR:", e)
            return 1
        print("ok")
        return 0

    if args.list:
        print_groups(lab)
        return 0

    settings = merge_settings(lab, config, args)
    out_dir = args.shot_dir or config.get("shot_dir") or os.path.join(HERE, "shots")
    if not os.path.isabs(out_dir):
        out_dir = os.path.join(HERE, out_dir)

    if args.shot_test:
        from screenshotfucker.local import run_shot_test

        return run_shot_test(out_dir, True, settings)

    on_server = args.on_server or (
        os.name != "nt"
        and not (args.host or config.get("host") or os.environ.get("LAB_HOST") or os.environ.get("SFF_HOST"))
    )
    if on_server:
        from screenshotfucker.remote_runner import main as remote_main

        remote_argv = ["--lab", lab_path]
        if args.start_from and args.start_from != 1:
            remote_argv += ["--from", str(args.start_from)]
        if args.at:
            remote_argv += ["--at", str(args.at)]
        if args.speed:
            remote_argv += ["--speed", str(args.speed)]
        if args.no_clear:
            remote_argv.append("--no-clear")
        if args.auto:
            remote_argv.append("--no-pause")
        return remote_main(remote_argv)

    host = (
        args.host
        or config.get("host")
        or os.environ.get("SFF_HOST")
        or os.environ.get("LAB_HOST")
        or ""
    ).strip()
    user = (
        args.user
        or config.get("user")
        or os.environ.get("SFF_USER")
        or os.environ.get("LAB_USER")
        or ""
    ).strip()
    password = (
        config.get("password")
        or os.environ.get("SFF_SSH_PASS")
        or os.environ.get("LAB_SSH_PASS")
        or ""
    ).strip()

    cfg_path = os.path.abspath(args.config) if args.config else DEFAULT_CONFIG
    if not args.auto:
        if created:
            eprint("按提示填三项即可开跑，会写进 config.json。")
        if not host:
            typed = input("实验机地址 [192.168.1.10]: ").strip()
            host = typed or "192.168.1.10"
        if not user:
            typed = input("SSH 用户 [root]: ").strip()
            user = typed or "root"
        if not password:
            try:
                import getpass

                password = getpass.getpass("SSH 密码（空表示用密钥/手动输入）: ")
            except Exception:
                password = ""
        dirty = False
        if host and config.get("host") != host:
            config["host"] = host
            dirty = True
        if user and config.get("user") != user:
            config["user"] = user
            dirty = True
        if password and config.get("password") != password:
            config["password"] = password
            dirty = True
        if dirty:
            try:
                save_config(cfg_path, config)
                eprint("已写入 %s" % cfg_path)
            except Exception as exc:
                eprint("写配置失败：%s" % exc)
    if not host or not user:
        eprint("需要 host 和 user。写进 config.json，或加 --host / --user。")
        eprint("然后直接：  python ScreenshotFucker.py")
        return 2
    if args.at and args.start_from != 1:
        eprint("--at 和 --from 不能一起用")
        return 2

    eprint("启动 ScreenshotFucker  %s@%s" % (user, host))
    from screenshotfucker.local import run_local

    return run_local(args, lab_path, host, user, password, out_dir, settings)


if __name__ == "__main__":
    sys.exit(main())
