# -*- coding: utf-8 -*-
"""Load a lab JSON file, substitute ${vars}, and expand each box into commands."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class LabError(ValueError):
    pass


def subst(text: Any, variables: Dict[str, Any]) -> Any:
    if isinstance(text, str):
        def repl(m):
            key = m.group(1)
            if key not in variables:
                raise LabError("unknown variable ${%s}" % key)
            return str(variables[key])

        return VAR_RE.sub(repl, text)
    if isinstance(text, list):
        return [subst(x, variables) for x in text]
    if isinstance(text, dict):
        return {k: subst(v, variables) if k != "if" else v for k, v in text.items()}
    return text


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise LabError("lab file must be a JSON object")
    return data


def load_lab(path: str, extra_vars: Optional[dict] = None) -> dict:
    lab = _read_json(path)
    if int(lab.get("schema_version", 1)) != 1:
        raise LabError("unsupported schema_version %s" % lab.get("schema_version"))
    variables = {}
    variables.update(lab.get("vars") or {})
    if extra_vars:
        variables.update(extra_vars)
    lab["vars"] = {str(k): str(v) for k, v in variables.items()}
    lab["session"] = subst(lab.get("session") or {}, lab["vars"])
    lab["settings"] = lab.get("settings") or {}
    boxes = lab.get("boxes")
    if not isinstance(boxes, list) or not boxes:
        raise LabError("lab file needs a non-empty boxes array")
    lab["boxes"] = [subst(b, lab["vars"]) for b in boxes]
    return lab


def expand_cmds(box: dict) -> List[dict]:
    """Turn script/cmds into a list of {text, wait?, timeout?, skip_if?, kind?}."""
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
        if not isinstance(item, dict):
            raise LabError("command must be a string or object in box %s" % box.get("n"))
        text = item.get("text")
        if text is None:
            raise LabError("command missing text in box %s" % box.get("n"))
        cmd = dict(item)
        cmd["text"] = str(text)
        if default_timeout and "timeout" not in cmd:
            cmd["timeout"] = default_timeout
        out.append(cmd)
    if not out:
        raise LabError("box %s has no commands" % box.get("n"))
    return out


def check_lab(lab: dict) -> List[str]:
    errors = []
    seen = set()
    for i, box in enumerate(lab.get("boxes") or []):
        n = box.get("n")
        if not isinstance(n, int) or n < 1:
            errors.append("boxes[%d] has invalid n" % i)
            continue
        if n in seen:
            errors.append("duplicate box n=%d" % n)
        seen.add(n)
        if not (box.get("title") or "").strip():
            errors.append("box %d missing title" % n)
        try:
            cmds = expand_cmds(box)
        except LabError as exc:
            errors.append(str(exc))
            continue
        leftover = [m.group(0) for cmd in cmds for m in VAR_RE.finditer(cmd["text"])]
        if leftover:
            errors.append("box %d still has variables: %s" % (n, ", ".join(leftover)))
    ns = sorted(seen)
    if ns and ns != list(range(1, ns[-1] + 1)):
        errors.append("box numbers should be 1..%d without gaps (got %s)" % (ns[-1], ns))
    return errors


def print_groups(lab: dict) -> None:
    boxes = lab.get("boxes") or []
    print("lab: %s" % (lab.get("name") or "(unnamed)"))
    print("boxes: %d" % len(boxes))
    for box in boxes:
        cmds = expand_cmds(box)
        joined = "  |  ".join(c["text"] for c in cmds)
        print("  %2d. %s" % (box["n"], box.get("title") or ""))
        print("      %s" % joined)
