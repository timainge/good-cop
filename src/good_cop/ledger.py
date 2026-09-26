"""Deterministic ledger: fold/rebuild plus per-tool extractors. See plan.md §3."""

import copy
import os
import re
import shlex

URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
SCRIPT_RUNNERS = {"bash", "sh", "zsh", "source", ".", "python", "python3", "node", "ruby", "perl"}
SCRIPT_EXT = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".rb", ".pl")
MAX_RECENT_COMMANDS = 10


def empty() -> dict:
    return {
        "env": {},
        "files_written": {},
        "commands": {"count": 0, "last": []},
        "hosts_contacted": [],
        "context_changes": [],
        "flags": {},
        "last_event_seq": 0,
    }


def abspath(path: str, cwd: str | None) -> str:
    return os.path.normpath(os.path.join(cwd or "/", os.path.expanduser(path)))


def executed_scripts(command: str) -> list[str]:
    """Local files a shell command executes: ./x, bash x.sh, python x.py, …"""
    out = []
    for segment in re.split(r"&&|\|\||;|\||\n", command or ""):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            tokens = segment.split()
        while tokens and re.match(r"^\w+=", tokens[0]):  # FOO=bar ./x.sh
            tokens = tokens[1:]
        if tokens and tokens[0] in ("uv", "poetry") and tokens[1:2] == ["run"]:
            tokens = tokens[2:]
        if not tokens:
            continue
        head = tokens[0]
        if head.startswith(("./", "../", "/", "~/")) and not head.startswith(("/usr/", "/bin/", "/opt/")):
            out.append(head)
        elif os.path.basename(head) in SCRIPT_RUNNERS:
            args = [t for t in tokens[1:] if not t.startswith("-")]
            if args and (args[0].endswith(SCRIPT_EXT) or "/" in args[0]):
                out.append(args[0])
    return out


def hosts_in(value) -> list[str]:
    text = value if isinstance(value, str) else repr(value)
    return [h.lower() for h in URL_RE.findall(text)]


# Extractors: (ledger, event) -> None, mutating the (already copied) ledger.

def _add_hosts(ledger: dict, hosts: list[str]) -> None:
    for h in hosts:
        if h not in ledger["hosts_contacted"]:
            ledger["hosts_contacted"].append(h)


def _bash(ledger: dict, e: dict) -> None:
    cmd = (e.get("input") or {}).get("command", "")
    c = ledger["commands"]
    c["count"] += 1
    c["last"] = (c["last"] + [cmd[:200]])[-MAX_RECENT_COMMANDS:]
    _add_hosts(ledger, hosts_in(cmd))
    for script in executed_scripts(cmd):
        if abspath(script, e.get("cwd")) in ledger["files_written"]:
            ledger["flags"]["ran_script_written_this_session"] = True
    if re.search(r"chmod\s+\+?[0-7]*x", cmd):
        for path, info in ledger["files_written"].items():
            if os.path.basename(path) in cmd:
                info["executable_hint"] = True


def _write(ledger: dict, e: dict) -> None:
    inp = e.get("input") or {}
    path = inp.get("file_path") or inp.get("notebook_path")
    if not path:
        return
    key = abspath(path, e.get("cwd"))
    content = inp.get("content") or ""
    info = ledger["files_written"].setdefault(
        key, {"first_seq": e["seq"], "last_seq": e["seq"], "tool": e["tool"], "executable_hint": False})
    info["last_seq"] = e["seq"]
    info["tool"] = e["tool"]
    if key.endswith(SCRIPT_EXT) or content.startswith("#!"):
        info["executable_hint"] = True


def _fetch(ledger: dict, e: dict) -> None:
    _add_hosts(ledger, hosts_in((e.get("input") or {}).get("url", "")))


def _mcp(ledger: dict, e: dict) -> None:
    _add_hosts(ledger, hosts_in(e.get("input") or {}))


EXTRACTORS = {
    "Bash": _bash,
    "Write": _write,
    "Edit": _write,
    "MultiEdit": _write,
    "NotebookEdit": _write,
    "WebFetch": _fetch,
}


def fold(ledger: dict, event: dict) -> dict:
    ledger = copy.deepcopy(ledger)
    t = event.get("type")
    if t == "session_start":
        ledger["env"]["cwd"] = event.get("cwd")
    elif t == "probe":
        env = ledger["env"]
        for fact, value in (event.get("facts") or {}).items():
            if fact in env and env[fact] != value:
                ledger["context_changes"].append(
                    {"seq": event["seq"], "fact": fact, "from": env[fact], "to": value})
            env[fact] = value
        env["probed_at"] = event.get("ts")
    elif t == "post_tool":
        tool = event.get("tool") or ""
        fn = EXTRACTORS.get(tool) or (_mcp if tool.startswith("mcp__") else None)
        if fn:
            fn(ledger, event)
    ledger["last_event_seq"] = max(ledger["last_event_seq"], event.get("seq", 0))
    return ledger


def rebuild(events: list[dict]) -> dict:
    ledger = empty()
    for e in events:
        ledger = fold(ledger, e)
    return ledger
