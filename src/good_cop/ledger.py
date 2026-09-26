"""Deterministic ledger: fold/rebuild plus per-tool extractors. See plan.md §3."""

import copy
import os
import re
import shlex

URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)")
SCRIPT_RUNNERS = {"bash", "sh", "zsh", "source", ".", "python", "python3", "node", "tsx", "deno", "bun", "ruby", "perl"}
SCRIPT_EXT = (".sh", ".bash", ".zsh", ".py", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl")
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


HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n.*?\n\s*\2[ \t]*(?=\n|$)", re.S)
ASSIGN_RE = re.compile(r"^(?:export\s+)?([A-Za-z_]\w*)=(\S*)$")
VAR_RE = re.compile(r"\$\{?([A-Za-z_]\w*)\}?")
REDIRECT_RE = re.compile(r"^\d?>>?(?!&)(.*)$")


def segments(command: str, cwd: str | None) -> list[tuple[list[str], str | None]]:
    """Split a shell command into simple-command token lists, each with its effective cwd.

    Best effort, not a shell: heredoc bodies are dropped, `cd dir` updates the cwd for later
    segments, and `VAR=value` assignments made earlier in the command are substituted.
    """
    text = HEREDOC_RE.sub(lambda m: m.group(3), command or "")
    env: dict[str, str] = {}
    out = []
    for segment in re.split(r"&&|\|\||;|\||\n|\(|\)", text):
        try:
            tokens = shlex.split(segment, comments=True)
        except ValueError:
            tokens = segment.split()
        tokens = [VAR_RE.sub(lambda m: env.get(m.group(1), m.group(0)), t) for t in tokens]
        while tokens and ASSIGN_RE.match(tokens[0]):
            name, value = ASSIGN_RE.match(tokens[0]).groups()
            env[name] = value
            tokens = tokens[1:]
        if tokens[:1] == ["cd"] and len(tokens) > 1:
            cwd = abspath(tokens[1], cwd)
            continue
        if tokens:
            out.append((tokens, cwd))
    return out


def _unwrap(tokens: list[str]) -> list[str]:
    """Strip launchers so tokens[0] is the program: `uv run`, `npx`, `env`, `time`, `sudo`."""
    while tokens:
        if tokens[0] in ("uv", "poetry", "pnpm", "yarn", "bun") and tokens[1:2] == ["run"]:
            tokens = tokens[2:]
        elif tokens[0] in ("npx", "env", "time", "sudo", "exec", "nohup"):
            tokens = tokens[1:]
        else:
            return tokens
    return tokens


def executed_scripts(command: str, cwd: str | None = None) -> list[str]:
    """Absolute paths of local files a shell command executes: ./x, bash x.sh, python x.py, …"""
    out = []
    for tokens, seg_cwd in segments(command, cwd):
        tokens = _unwrap(tokens)
        if not tokens:
            continue
        head = tokens[0]
        if "/" in head and not head.startswith(("/usr/", "/bin/", "/opt/", "/sbin/")) and "$" not in head:
            out.append(abspath(head, seg_cwd))
        elif os.path.basename(head) in SCRIPT_RUNNERS:
            args = [t for t in tokens[1:] if not t.startswith("-")]
            if args and args[0].endswith(SCRIPT_EXT) and "$" not in args[0]:
                out.append(abspath(args[0], seg_cwd))
    return out


def shell_writes(command: str, cwd: str | None = None) -> list[str]:
    """Absolute paths a shell command writes via `>`/`>>`, `tee` or `cp`/`mv`."""
    out = []
    for tokens, seg_cwd in segments(command, cwd):
        targets = []
        for i, t in enumerate(tokens):
            m = REDIRECT_RE.match(t)
            if m:
                targets.append(m.group(1) or (tokens[i + 1] if i + 1 < len(tokens) else ""))
        prog = _unwrap(tokens)
        args = [t for t in prog[1:] if not t.startswith("-") and not REDIRECT_RE.match(t)]
        if prog[:1] == ["tee"]:
            targets += args
        elif prog[:1] in (["cp"], ["mv"]) and len(args) >= 2:
            targets.append(args[-1])
        out += [abspath(p, seg_cwd) for p in targets if p]
    return [p for p in dict.fromkeys(out) if p != "/dev/null" and "$" not in p and "*" not in p]


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
    for path in shell_writes(cmd, e.get("cwd")):
        _record_write(ledger, path, e["seq"], "Bash")
    for script in executed_scripts(cmd, e.get("cwd")):
        if script in ledger["files_written"]:
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
    info = _record_write(ledger, abspath(path, e.get("cwd")), e["seq"], e["tool"])
    if (inp.get("content") or "").startswith("#!"):
        info["executable_hint"] = True


def _record_write(ledger: dict, key: str, seq: int, tool: str) -> dict:
    info = ledger["files_written"].setdefault(
        key, {"first_seq": seq, "last_seq": seq, "tool": tool, "executable_hint": False})
    info["last_seq"] = seq
    info["tool"] = tool
    if key.endswith(SCRIPT_EXT):
        info["executable_hint"] = True
    return info


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
