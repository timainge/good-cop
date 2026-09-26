"""Environment probes (shell commands / env vars) with triggers. See plan.md §3."""

import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

DEFAULT_PROBES = [
    {"name": "git_branch", "cmd": "git branch --show-current", "trigger": r"git\s+(checkout|switch)\b"},
    {"name": "kube_context", "cmd": "kubectl config current-context", "trigger": r"kubectl\s+config\s+use-context|kubectx"},
    {"name": "tf_workspace", "cmd": "terraform workspace show", "trigger": r"terraform\s+workspace\s+(select|new)"},
    {"name": "aws_profile", "env": "AWS_PROFILE"},
]

TIMEOUT = 0.5


def run_one(probe: dict, cwd: str | None) -> str | None:
    if "env" in probe:
        return os.environ.get(probe["env"]) or None
    try:
        r = subprocess.run(probe["cmd"], shell=True, cwd=cwd or None, capture_output=True,
                           text=True, timeout=probe.get("timeout", TIMEOUT))
    except (subprocess.TimeoutExpired, OSError):
        return None
    out = r.stdout.strip()
    return out if r.returncode == 0 and out else None


def run(probes: list[dict], cwd: str | None) -> dict:
    if not probes:
        return {}
    with ThreadPoolExecutor(len(probes)) as ex:
        values = ex.map(lambda p: run_one(p, cwd), probes)
    return {p["name"]: v for p, v in zip(probes, values)}


def triggered(probes: list[dict], command: str) -> list[dict]:
    return [p for p in probes if p.get("trigger") and re.search(p["trigger"], command or "")]
