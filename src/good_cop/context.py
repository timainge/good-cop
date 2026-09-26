"""Build the decision state for a PreToolUse call. See plan.md §5."""

import json

from good_cop import ledger as ledger_mod

SCRIPT_HEAD = 4096
RECENT = 5


def resolve_script(tool_input: dict, cwd: str | None, ledger: dict, read_file=None) -> dict | None:
    """If a Bash command runs a local script, return its path, head and whether we saw it written.

    `read_file(path) -> str | None` supplies the content: live mode reads disk, import mode
    replays Write/Edit contents. Called once, when the pre_tool event is recorded.
    """
    for path in ledger_mod.executed_scripts((tool_input or {}).get("command", ""), cwd):
        head = read_file(path) if read_file else None
        return {"path": path, "written_this_session": path in ledger["files_written"],
                "head": head[:SCRIPT_HEAD] if head else None}
    return None


def writes(event: dict) -> list[dict]:
    """Paths this call writes (Write/Edit file_path, shell redirects/tee/cp), flagged if outside cwd."""
    inp, cwd = event.get("input") or {}, event.get("cwd")
    if event.get("tool") == "Bash":
        paths = ledger_mod.shell_writes(inp.get("command", ""), cwd)
    elif inp.get("file_path") or inp.get("notebook_path"):
        paths = [ledger_mod.abspath(inp.get("file_path") or inp["notebook_path"], cwd)]
    else:
        return []
    root = (cwd or "/").rstrip("/") + "/"
    return [{"path": p, "outside_cwd": not p.startswith(root)} for p in paths]


def read_disk(path: str) -> str | None:
    try:
        with open(path, errors="replace") as f:
            return f.read(SCRIPT_HEAD)
    except OSError:
        return None


def _clip(value, n: int):
    s = value if isinstance(value, str) else json.dumps(value, default=str)
    return s if len(s) <= n else s[:n] + "…"


def compact(event: dict) -> dict:
    out = {"seq": event.get("seq"), "type": event.get("type")}
    if event.get("tool"):
        out["tool"] = event["tool"]
        out["input"] = _clip(event.get("input"), 300)
    if event.get("type") == "post_tool":
        out["result"] = _clip(event.get("result"), 300)
    if event.get("type") == "prompt":
        out["prompt"] = _clip(event.get("prompt"), 500)
    return out


def size(obj) -> int:
    """Estimated tokens (chars / 4)."""
    return len(json.dumps(obj, default=str)) // 4


def build_state(event: dict, ledger: dict, summary: dict | None, recent: list[dict],
                max_tokens: int = 8000) -> dict:
    ledger_view = {k: v for k, v in ledger.items() if k != "last_event_seq"}
    ledger_view["commands"] = {**ledger["commands"], "last": ledger["commands"]["last"][-5:]}
    state = {
        "call": {"tool": event.get("tool"), "input": event.get("input"), "cwd": event.get("cwd"),
                 "subagent": bool(event.get("agent_id"))},
        "resolved": {**(event.get("resolved") or {}), "writes": writes(event)},
        "ledger": ledger_view,
        "summary": {k: v for k, v in summary.items() if k != "last_event_seq"} if summary else None,
        "recent": [compact(e) for e in recent[-RECENT:]],
    }
    # Trim to the size cap: recent first, then summary notes, then long inputs.
    while size(state) > max_tokens and state["recent"]:
        state["recent"].pop(0)
    if size(state) > max_tokens and state["summary"]:
        state["summary"]["notable"] = []
    if size(state) > max_tokens:
        state["ledger"]["files_written"] = dict(list(state["ledger"]["files_written"].items())[-20:])
    if size(state) > max_tokens:
        state["call"]["input"] = _clip(state["call"]["input"], max_tokens * 2)
    return state
