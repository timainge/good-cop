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
SEPARATORS = {"&&", "||", ";", "|", "&", "(", ")", ";;", "|&", ";&"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<", "<<<", ">&", "<&"}
WRITE_REDIRECTS = {">", ">>", ">|", "&>", "&>>"}


WRITE_HEREDOC_RE = re.compile(r"(?:\bcat\b[^\n;&|]*>|\btee\b|>\s*\S+\s*$)")


def executed_text(command: str) -> str:
    """The command minus heredoc bodies that are only written to a file (`cat > x.sh <<EOF`, `tee`):
    that text is data until something runs it (then it's in `resolved.script`). Heredocs fed to an
    interpreter (`python3 - <<EOF`, `bash <<EOF`), or in a command that also runs a local script
    (`cat > x.sh <<EOF … EOF && ./x.sh`), are kept."""
    if executed_scripts(command):
        return command or ""

    def sub(m):
        line = command[command.rfind("\n", 0, m.start()) + 1:m.start()]
        return m.group(0)[:m.group(0).index("\n")] if WRITE_HEREDOC_RE.search(line) else m.group(0)
    return HEREDOC_RE.sub(sub, command or "")


def _newlines_to_semicolons(text: str) -> str:
    """Unquoted newlines separate commands; shlex would treat them as plain whitespace."""
    out, quote, escaped = [], None, False
    for ch in text:
        if escaped:
            escaped = False
        elif ch == "\\" and quote != "'":
            escaped = True
        elif quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "\n":
            ch = ";"
        out.append(ch)
    return "".join(out)


def _parse(command: str, cwd: str | None, assigned: list | None = None) -> list[tuple[list[str], str | None, list[str]]]:
    """(tokens, cwd, redirect write targets) per simple command. Quote-aware: operators inside
    quotes (`sed '/a(b)/p'`, `grep 'x|y'`) stay part of their word. `assigned` collects every
    `VAR=value` (prefix or standalone) as "VAR=value"."""
    text = _newlines_to_semicolons(HEREDOC_RE.sub(lambda m: m.group(3), command or ""))
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        raw = list(lex)
    except ValueError:  # unbalanced quotes: fall back to whitespace
        raw = text.split()
    groups: list[list[str]] = [[]]
    for t in raw:
        if t in SEPARATORS:
            groups.append([])
        else:
            groups[-1].append(t)
    env: dict[str, str] = {}
    out = []
    for g in groups:
        tokens, targets, i = [], [], 0
        while i < len(g):
            if g[i] in REDIRECTS:
                if tokens and tokens[-1].isdigit():  # `2>`: the fd, not an argument
                    tokens.pop()
                if g[i] in WRITE_REDIRECTS and i + 1 < len(g):
                    targets.append(g[i + 1])
                i += 2
                continue
            tokens.append(g[i])
            i += 1
        sub = lambda t: VAR_RE.sub(lambda m: env.get(m.group(1), m.group(0)), t)
        tokens, targets = [sub(t) for t in tokens], [sub(t) for t in targets]
        if tokens[:1] == ["export"] and len(tokens) > 1 and ASSIGN_RE.match(tokens[1]):
            tokens = tokens[1:]
        while tokens and ASSIGN_RE.match(tokens[0]):
            name, value = ASSIGN_RE.match(tokens[0]).groups()
            env[name] = value
            if assigned is not None:
                assigned.append(f"{name}={value}")
            tokens = tokens[1:]
        if tokens[:1] == ["cd"] and len(tokens) > 1:
            cwd = abspath(tokens[1], cwd)
            continue
        if tokens or targets:
            out.append((tokens, cwd, targets))
    return out


def segments(command: str, cwd: str | None) -> list[tuple[list[str], str | None]]:
    """Split a shell command into simple-command token lists, each with its effective cwd.

    Best effort, not a shell: heredoc bodies are dropped, redirections removed, `cd dir` updates
    the cwd for later segments, and `VAR=value` assignments earlier in the command are substituted.
    """
    return [(tokens, c) for tokens, c, _ in _parse(command, cwd) if tokens]


def inline_env(command: str) -> list[str]:
    """`VAR=value` assignments in a command (`AWS_PROFILE=prod aws …`, `export X=y; …`), as
    "VAR=value" strings. The hook's own environment never sees these."""
    out: list[str] = []
    _parse(command, None, out)
    return list(dict.fromkeys(out))


def normalised(command: str) -> list[str]:
    """Each simple command as the shell would see its words: quotes removed (`r''m` -> `rm`),
    earlier `VAR=value` substituted, re-joined with shlex quoting. For patterns that evasion beats."""
    word = lambda t: t if re.fullmatch(r"[\w@%+=:,./~*$-]+", t) else shlex.quote(t)
    return [" ".join(word(t) for t in tokens) for tokens, _ in segments(command, None)]


LAUNCHER_ARG_FLAGS = {"--with", "--from", "--python", "-p", "--project", "--directory", "-k", "-s"}


def _unwrap(tokens: list[str]) -> list[str]:
    """Strip launchers so tokens[0] is the program: `uv run --quiet`, `npx`, `env`, `timeout 60`, `sudo`."""
    while tokens:
        if tokens[0] in ("uv", "poetry", "pnpm", "yarn", "bun") and tokens[1:2] == ["run"]:
            tokens = tokens[2:]
        elif tokens[0] in ("npx", "env", "time", "sudo", "exec", "nohup", "timeout", "gtimeout"):
            tokens = tokens[1:]
            if tokens and tokens[0] != "--" and re.fullmatch(r"\d+[smhd]?", tokens[0]) and len(tokens) > 1:
                tokens = tokens[1:]  # timeout's duration
        elif tokens[0].startswith("-") and len(tokens) > 1:  # launcher flags: uv run --quiet, npx -y
            tokens = tokens[2:] if tokens[0] in LAUNCHER_ARG_FLAGS else tokens[1:]
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
    for tokens, seg_cwd, targets in _parse(command, cwd):
        prog = _unwrap(tokens)
        args = [t for t in prog[1:] if not t.startswith("-")]
        if prog[:1] == ["tee"]:
            targets = targets + args
        elif prog[:1] in (["cp"], ["mv"]) and len(args) >= 2:
            targets = targets + [args[-1]]
        elif prog[:1] == ["sed"] and any(t.startswith(("-i", "--in-place")) for t in prog[1:]):
            targets = targets + _sed_files(prog[1:])
        out += [abspath(p, seg_cwd) for p in targets if p]
    return [p for p in dict.fromkeys(out) if p != "/dev/null" and "$" not in p and "*" not in p]


def _sed_files(args: list[str]) -> list[str]:
    """Files `sed -i` edits: bare words, minus the script (the first bare word unless -e/-f gave
    one) and BSD's `-i ''` suffix."""
    words, script_given, skip = [], False, False
    for i, t in enumerate(args):
        if skip:
            skip = False
        elif t in ("-e", "-f", "--expression", "--file"):
            script_given, skip = True, True
        elif t == "-i" and i + 1 < len(args) and args[i + 1] == "":
            skip = True
        elif t and not t.startswith("-"):
            words.append(t)
    return words if script_given else words[1:]


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


def _apply_patch(ledger: dict, e: dict) -> None:
    from good_cop.harness import patch_paths
    patch = (e.get("input") or {}).get("command", "")
    for path in patch_paths(patch):
        info = _record_write(ledger, abspath(path, e.get("cwd")), e["seq"], "apply_patch")
        if f"*** Add File: {path}\n+#!" in patch:
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
    "apply_patch": _apply_patch,  # Codex
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
