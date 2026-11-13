# -*- coding: utf-8 -*-
"""OpenSSH helpers: PATH, ASKPASS, scp/ssh with LF files."""

import os
import subprocess
import sys
import tempfile


def eprint(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def ensure_openssh_path():
    if shutil_which("ssh") and shutil_which("scp"):
        return True
    extra = [
        os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "OpenSSH"),
        r"C:\Program Files\OpenSSH",
        r"C:\Program Files (x86)\OpenSSH-Win64",
        r"C:\Program Files\Git\usr\bin",
    ]
    path = os.environ.get("PATH", "")
    parts = path.split(os.pathsep)
    changed = False
    for folder in extra:
        if os.path.isdir(folder) and folder not in parts:
            path = folder + os.pathsep + path
            changed = True
    if changed:
        os.environ["PATH"] = path
    return bool(shutil_which("ssh") and shutil_which("scp"))


def shutil_which(name):
    import shutil

    return shutil.which(name)


def unix_lf_copy(src, dst):
    data = open(src, "rb").read().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    with open(dst, "wb") as f:
        f.write(data)


def ensure_askpass(password=None):
    """Windows ssh.exe needs a .cmd ASKPASS. Only enable when a password is set."""
    if password:
        os.environ["SFF_SSH_PASS"] = password
        os.environ["LAB_SSH_PASS"] = password
    pw = os.environ.get("SFF_SSH_PASS") or os.environ.get("LAB_SSH_PASS") or ""
    if pw:
        os.environ["LAB_SSH_PASS"] = pw
        os.environ["SFF_SSH_PASS"] = pw
    if not os.environ.get("LAB_SSH_PASS"):
        return False
    if os.name != "nt":
        os.environ["SSH_ASKPASS_REQUIRE"] = "force"
        os.environ.setdefault("DISPLAY", ":0")
        return True
    wrap = os.path.join(tempfile.gettempdir(), "sff_askpass.cmd")
    py = sys.executable.replace('"', "")
    body = (
        "@echo off\r\n"
        "\"%s\" -c \"import os,sys; sys.stdout.write(os.environ.get('LAB_SSH_PASS',''))\"\r\n"
        % py
    )
    with open(wrap, "w", encoding="ascii", newline="") as f:
        f.write(body)
    os.environ["SSH_ASKPASS"] = wrap
    os.environ["SSH_ASKPASS_REQUIRE"] = "force"
    os.environ.setdefault("DISPLAY", "127.0.0.1:0")
    return True


def _password_auth_opts(ctl):
    if ctl:
        return []
    if os.name == "nt" or os.environ.get("SSH_ASKPASS") or os.environ.get("LAB_SSH_PASS"):
        return [
            "-o", "PreferredAuthentications=password",
            "-o", "PubkeyAuthentication=no",
            "-o", "NumberOfPasswordPrompts=1",
        ]
    return []


def ssh_prefix(user, host, ctl):
    cmd = ["ssh", "-o", "StrictHostKeyChecking=accept-new"]
    if ctl:
        cmd += ["-o", "ControlPath=" + ctl, "-o", "BatchMode=yes"]
    else:
        cmd += _password_auth_opts(ctl)
    cmd.append("%s@%s" % (user, host))
    return cmd


def scp_prefix(user, host, ctl):
    cmd = ["scp", "-o", "StrictHostKeyChecking=accept-new"]
    if ctl:
        cmd += ["-o", "ControlPath=" + ctl, "-o", "BatchMode=yes"]
    else:
        cmd += _password_auth_opts(ctl)
    return cmd


def open_control_master(user, host, ctl):
    cmd = [
        "ssh",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ControlMaster=yes",
        "-o", "ControlPath=" + ctl,
        "-o", "ControlPersist=60",
        "-o", "ServerAliveInterval=30",
        "%s@%s" % (user, host),
        "echo SFF_SSH_OK",
    ]
    eprint("SSH login (password once)...")
    rc = subprocess.call(cmd)
    if rc != 0:
        eprint("SSH login failed.")
        return False
    chk = [
        "ssh", "-O", "check",
        "-o", "ControlPath=" + ctl,
        "%s@%s" % (user, host),
    ]
    if subprocess.call(chk, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
        eprint("ControlMaster not usable on this OpenSSH; later hops may ask password again.")
        return False
    return True


def close_control_master(user, host, ctl):
    if not ctl:
        return
    subprocess.call(
        ["ssh", "-O", "exit", "-o", "ControlPath=" + ctl, "%s@%s" % (user, host)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def scp_lf(local_path, remote_spec, user, host, ctl):
    tmp = os.path.join(tempfile.gettempdir(), "sff_upload_%d" % os.getpid())
    unix_lf_copy(local_path, tmp)
    cmd = scp_prefix(user, host, ctl) + [tmp, remote_spec]
    rc = subprocess.call(cmd, stdin=subprocess.DEVNULL)
    try:
        os.remove(tmp)
    except Exception:
        pass
    return rc == 0
