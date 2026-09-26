"""Import Claude Code transcripts (~/.claude/projects/*/*.jsonl) as good-cop sessions.

This is a test-data path only: it lets backtest run over sessions recorded before good-cop was
installed. Live mode never reads transcripts. Transcripts don't contain probe output, so the
only environment fact recovered is `git_branch` (from each record's `gitBranch`).
"""

import json
from pathlib import Path

from good_cop import context, hook, ledger as ledger_mod, store

PROJECTS = Path.home() / ".claude" / "projects"


def _records(path: Path) -> list[dict]:
    """Main transcript plus its subagent transcripts, ordered by timestamp."""
    out = []
    files = [(path, None)] + [(p, p.stem.removeprefix("agent-"))
                              for p in sorted(path.with_suffix("").glob("subagents/*.jsonl"))]
    for f, agent_id in files:
        for line in f.read_text(errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") in ("user", "assistant") and rec.get("timestamp"):
                rec["_agent_id"] = agent_id
                out.append(rec)
    return sorted(out, key=lambda r: r["timestamp"])


def _payload(name: str, rec: dict, **fields) -> dict:
    p = {"hook_event_name": name, "cwd": rec.get("cwd"), **fields}
    if rec.get("_agent_id"):
        p["agent_id"] = rec["_agent_id"]
    return p


def convert(path: Path) -> tuple[str, list[dict]]:
    """Return (session_id, events) for one transcript. Events carry seq and ts but no session_id."""
    records = _records(path)
    sid = next((r["sessionId"] for r in records if r.get("sessionId")), path.stem)
    events: list[dict] = []
    ledger = ledger_mod.empty()
    files: dict[str, str] = {}      # replayed file contents, for resolving script heads
    pending: dict[str, dict] = {}   # tool_use_id -> pre_tool event
    branch, turn_open = None, False

    def emit(event: dict, ts: str) -> None:
        nonlocal ledger
        event = {"seq": len(events) + 1, "ts": ts, **event}
        events.append(event)
        ledger = ledger_mod.fold(ledger, event)

    for rec in records:
        ts, sub = rec["timestamp"], rec.get("_agent_id")
        if not events and rec.get("cwd"):
            emit(hook.normalise(_payload("SessionStart", rec, source=f"import:{path.name}")), ts)
        if not sub and rec.get("gitBranch") and rec["gitBranch"] != branch:
            branch = rec["gitBranch"]
            emit({"type": "probe", "facts": {"git_branch": branch}}, ts)
        content = rec["message"].get("content")
        blocks = content if isinstance(content, list) else [{"type": "text", "text": content}]

        if rec["type"] == "assistant":
            for b in blocks:
                if b.get("type") != "tool_use":
                    continue
                e = hook.normalise(_payload("PreToolUse", rec, tool_name=b["name"],
                                            tool_input=b.get("input") or {}, tool_use_id=b["id"]))
                if b["name"] == "Bash":
                    script = context.resolve_script(e["input"], e["cwd"], ledger,
                                                    lambda p: files.get(p) or context.read_disk(p))
                    if script:
                        e["resolved"] = {"script": script}
                emit(e, ts)
                pending[b["id"]] = e
            continue

        # user record: tool results and/or a human prompt
        for b in blocks:
            if b.get("type") == "tool_result" and b.get("tool_use_id") in pending:
                pre = pending.pop(b["tool_use_id"])
                result = rec.get("toolUseResult") if len(blocks) == 1 and rec.get("toolUseResult") else b.get("content")
                emit(hook.normalise(_payload("PostToolUse", rec, tool_name=pre["tool"], tool_input=pre["input"],
                                             tool_response=result, tool_use_id=b["tool_use_id"])), ts)
                _track_file(files, pre)
            elif (b.get("type") == "text" and b.get("text") and not sub
                  and not rec.get("isMeta") and not rec.get("isCompactSummary")):
                if turn_open:
                    emit({"type": "stop", "cwd": rec.get("cwd")}, ts)
                emit(hook.normalise(_payload("UserPromptSubmit", rec, prompt=b["text"])), ts)
                turn_open = True
    if turn_open and events:
        emit({"type": "stop", "cwd": events[-1].get("cwd")}, events[-1]["ts"])
    return sid, events


def _track_file(files: dict, pre: dict) -> None:
    inp = pre.get("input") or {}
    path = inp.get("file_path")
    if not path:
        return
    key = ledger_mod.abspath(path, pre.get("cwd"))
    if pre["tool"] == "Write":
        files[key] = inp.get("content") or ""
    elif pre["tool"] == "Edit" and key in files and inp.get("old_string"):
        n = -1 if inp.get("replace_all") else 1
        files[key] = files[key].replace(inp["old_string"], inp.get("new_string", ""), n)


def import_transcript(path: Path, force: bool = False) -> tuple[str, int] | None:
    sid, events = convert(path)
    d = store.session_dir(sid)
    if not events or ((d / "events.jsonl").exists() and not force):
        return None
    d.mkdir(parents=True, exist_ok=True)
    for name in ("events.jsonl", "ledger.json", "decisions.jsonl", "summary.json"):
        (d / name).unlink(missing_ok=True)
    with open(d / "events.jsonl", "w") as f:
        for e in events:
            f.write(json.dumps({**e, "session_id": sid}, default=str) + "\n")
    (d / "seq").write_text(str(len(events)))
    store.write_json_atomic(d / "ledger.json", ledger_mod.rebuild(events))
    return sid, len(events)


def main(paths: list[str], all_: bool, project: str | None, force: bool) -> int:
    targets = [Path(p) for p in paths]
    if all_ or project:
        targets += sorted(p for p in PROJECTS.glob("*/*.jsonl") if not project or project in p.parent.name)
    for p in targets:
        try:
            res = import_transcript(p, force)
        except Exception as e:
            print(f"  skip {p.name}: {type(e).__name__}: {e}")
            continue
        if res:
            print(f"  {res[0]}  {res[1]:>6} events  <- {p.parent.name}/{p.name}")
    return 0
