#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ScreenshotFucker 本地边界测试（不连 SSH）。"""

from __future__ import print_function

import io
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from screenshotfucker.labfile import LabError, check_lab, expand_cmds, load_lab, subst  # noqa: E402
from screenshotfucker.protocol import BAR_RGB  # noqa: E402
from screenshotfucker.remote_runner import resolve_wait  # noqa: E402

PY = sys.executable
FAILED = []
PASSED = 0


def ok(name):
    global PASSED
    PASSED += 1
    print("PASS  %s" % name)


def fail(name, msg):
    FAILED.append((name, msg))
    print("FAIL  %s: %s" % (name, msg))


def expect(name, cond, msg=""):
    if cond:
        ok(name)
    else:
        fail(name, msg or "assertion failed")


def lab_path(*parts):
    return os.path.join(HERE, "labs", *parts)


def cli(args, extra_env=None):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [PY, "-u", os.path.join(ROOT, "ScreenshotFucker.py")] + args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_help_and_entry():
    r = cli(["--help"])
    blob = (r.stdout or "") + (r.stderr or "")
    expect("cli help rc", r.returncode == 0, blob)
    expect("cli help name", "ScreenshotFucker" in blob, blob)
    expect("cli help no labterm", "labterm" not in blob.lower(), blob)
    expect("entry file", os.path.isfile(os.path.join(ROOT, "ScreenshotFucker.py")))
    for name in ("labterm.py", "remote_runner.py", "run.cmd", "run.ps1", "run.sh"):
        expect("removed %s" % name, not os.path.exists(os.path.join(ROOT, name)))
    expect("removed labterm package", not os.path.isdir(os.path.join(ROOT, "labterm")))


def test_opengauss_check():
    r = cli(["--check", "--lab", os.path.join("labs", "opengauss-e5.json")])
    expect("cli check e5 rc", r.returncode == 0, r.stderr + r.stdout)
    expect("cli check e5 ok", "ok" in r.stdout, r.stdout)
    expect("cli check e5 34", "boxes: 34" in r.stdout, r.stdout)


def test_echo_list():
    r = cli(["--list", "--lab", os.path.join("labs", "example-echo.json")])
    expect("cli list echo rc", r.returncode == 0, r.stderr)
    expect("cli list echo boxes", "hostname" in r.stdout and "SFF_OK" in r.stdout, r.stdout)


def test_bad_labs():
    r = cli(["--check", "--lab", lab_path("bad-dup.json")])
    expect("cli dup rc", r.returncode == 1, r.stdout + r.stderr)
    expect("cli dup msg", "duplicate" in r.stdout.lower(), r.stdout)

    r = cli(["--check", "--lab", lab_path("bad-gap.json")])
    expect("cli gap rc", r.returncode == 1, r.stdout)
    expect("cli gap msg", "gap" in r.stdout.lower() or "without gaps" in r.stdout, r.stdout)

    r = cli(["--check", "--lab", lab_path("bad-var.json")])
    expect("cli unknown var rc", r.returncode == 1, r.stdout + r.stderr)
    expect(
        "cli unknown var msg",
        "no_such_var" in (r.stdout + r.stderr),
        r.stdout + r.stderr,
    )

    r = cli(["--check", "--lab", lab_path("bad-empty.json")])
    expect("cli empty box rc", r.returncode == 1, r.stdout)
    expect("cli empty box msg", "no commands" in r.stdout, r.stdout)

    r = cli(["--check", "--lab", lab_path("bad-schema.json")])
    expect("cli schema rc", r.returncode == 1, r.stdout + r.stderr)
    expect("cli schema msg", "schema_version" in (r.stdout + r.stderr), r.stdout + r.stderr)


def test_missing_lab():
    r = cli(["--check", "--lab", os.path.join("labs", "no-such.json")])
    expect("cli missing lab rc", r.returncode != 0, r.stdout + r.stderr)


def test_at_and_from():
    r = cli(
        [
            "--auto",
            "--no-relaunch",
            "--host",
            "127.0.0.1",
            "--user",
            "x",
            "--from",
            "2",
            "--at",
            "3",
            "--lab",
            os.path.join("labs", "example-echo.json"),
        ]
    )
    expect("cli at+from rc", r.returncode == 2, r.stdout + r.stderr)
    blob = (r.stdout + r.stderr).lower()
    expect(
        "cli at+from msg",
        "不能一起用" in (r.stdout + r.stderr) or "cannot be combined" in blob,
        r.stdout + r.stderr,
    )


def test_subst_and_override():
    text = subst("hello ${who}", {"who": "yzx"})
    expect("subst basic", text == "hello yzx", text)
    try:
        subst("hello ${missing}", {})
        fail("subst unknown", "should have raised")
    except LabError:
        ok("subst unknown")
    lab = load_lab(lab_path("boundaries.json"), extra_vars={"marker": "OVERRIDE_OK"})
    line = expand_cmds(lab["boxes"][0])[0]["text"]
    expect("extra_vars override", "OVERRIDE_OK" in line, line)
    expect("if key skipped", subst({"if": {"min": 2}, "text": "${x}"}, {"x": "1"})["if"]["min"] == 2)


def test_expand_script_cmds():
    lab = load_lab(lab_path("boundaries.json"))
    errs = check_lab(lab)
    expect("boundaries check", errs == [], str(errs))
    expect("boundaries 6 boxes", len(lab["boxes"]) == 6, str(len(lab["boxes"])))
    box3 = expand_cmds(lab["boxes"][2])
    expect("box3 one line", len(box3) == 1, str(box3))
    box6 = expand_cmds(lab["boxes"][5])
    expect("box6 skip_if kept", box6[0].get("skip_if") == "already_omm", str(box6[0]))
    box = {"n": 9, "timeout": 60, "script": ["SELECT 1;", "\\d x"]}
    cmds = expand_cmds(box)
    expect("timeout inherited", cmds[0].get("timeout") == 60 and cmds[1].get("timeout") == 60, str(cmds))


def test_resolve_wait():
    cases = [
        ({"text": "hostname"}, False, "shell"),
        ({"text": "gsql -d postgres -p 26000 -r", "wait": "shell"}, False, "gsql"),
        ({"text": "\\c DB_em"}, True, "gsql"),
        ({"text": "CREATE VIEW v AS"}, True, "gsql_more"),
        ({"text": "SELECT 1;"}, True, "gsql"),
        ({"text": "WHERE x < 1;"}, False, "gsql"),
        ({"text": "echo hi", "kind": "shell"}, False, "shell"),
    ]
    for cmd, in_gsql, want in cases:
        got = resolve_wait(cmd, in_gsql)
        expect("wait %s in_gsql=%s" % (cmd["text"][:24], in_gsql), got == want, "got %s want %s" % (got, want))


def test_crop():
    from PIL import Image, ImageDraw
    from screenshotfucker.capture import crop_by_bars, test_crop_synthetic

    syn_rc, syn_msg = test_crop_synthetic(os.path.join(ROOT, "shots"))
    expect("synthetic crop rc", syn_rc == 0, syn_msg)

    img = Image.new("RGB", (800, 360), (30, 30, 30))
    cropped, why = crop_by_bars(img)
    expect("crop no-bar", cropped is None and why == "no-bar", why)

    img = Image.new("RGB", (800, 420), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, 800, 40], fill=(230, 230, 230))
    draw.text((20, 80), "FIRST_BOX leftover", fill=(220, 220, 220))
    draw.rectangle([10, 140, 790, 170], fill=BAR_RGB)
    draw.text((20, 200), "SECOND_BOX keep me", fill=(220, 220, 220))
    draw.rectangle([10, 340, 790, 380], fill=BAR_RGB)
    cropped, why = crop_by_bars(img)
    expect("crop leftover rc", cropped is not None and why == "ok", why)
    if cropped is not None:
        pix = cropped.load()
        w, h = cropped.size
        pink = 0
        n = 0
        for y in range(h):
            for x in range(0, w, 10):
                p = pix[x, y]
                n += 1
                if abs(p[0] - 255) < 40 and p[1] < 80 and p[2] > 80:
                    pink += 1
        expect("crop leftover no pink", n and pink / float(n) < 0.08, "pink=%s n=%s h=%s" % (pink, n, h))
        expect("crop leftover height", 20 < h < 200, "h=%s" % h)

    wide = Image.new("RGB", (800, 280), (30, 30, 30))
    wdraw = ImageDraw.Draw(wide)
    wdraw.text((20, 40), "python3 -c print WIDE", fill=(220, 220, 220))
    for y in range(70, 130, 14):
        wdraw.text((0, y), "W" * 90, fill=(220, 220, 220))
    wdraw.text((20, 160), "prompt $", fill=(220, 220, 220))
    wdraw.rectangle([10, 230, 790, 265], fill=BAR_RGB)
    cropped, why = crop_by_bars(wide)
    expect("crop wide text rc", cropped is not None and why == "ok", why)
    if cropped is not None:
        expect("crop wide text height", cropped.size[1] > 80, "h=%s" % cropped.size[1])


def test_match_when():
    from screenshotfucker.remote_runner import _match_when

    expect("match min", _match_when({"min": 2, "max": 20}, 4) is True)
    expect("match below min", _match_when({"min": 2, "max": 20}, 1) is False)
    expect("match above max", _match_when({"min": 2, "max": 20}, 21) is False)
    expect("match min only", _match_when({"min": 22}, 22) is True)
    expect("match min only below", _match_when({"min": 22}, 21) is False)


def test_at_from_lab():
    lab = load_lab(lab_path("at-from.json"))
    expect("at-from check", check_lab(lab) == [], str(check_lab(lab)))
    expect("at-from 3", len(lab["boxes"]) == 3)


def main():
    print("ROOT", ROOT)
    test_help_and_entry()
    test_opengauss_check()
    test_echo_list()
    test_bad_labs()
    test_missing_lab()
    test_at_and_from()
    test_subst_and_override()
    test_expand_script_cmds()
    test_resolve_wait()
    test_crop()
    test_match_when()
    test_at_from_lab()
    print("")
    print("passed %d  failed %d" % (PASSED, len(FAILED)))
    for name, msg in FAILED:
        print("  - %s: %s" % (name, msg))
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
