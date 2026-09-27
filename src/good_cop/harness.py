"""Adapters for coding-agent harnesses other than Claude Code. See https://github.com/timainge/good-cop/wiki/Harness-Research.

Everything inside good-cop speaks Claude Code's hook schema. `to_claude` translates an incoming
payload into it; `output` translates a decision back into what the harness understands.

- claude: native.
- codex:  Claude-shaped payloads (verified: tests/fixtures/codex). File edits arrive as
          `apply_patch` with the patch text in `tool_input.command`. No `ask`: degraded to deny.
- cursor: native `.cursor/hooks.json` events, snake_case fields (`conversation_id`,
          `workspace_roots`, `tool_output`). Output `permission` allow/deny. From docs; unverified.
- copilot: camelCase payloads (`sessionId`, `toolName`, `toolArgs`, `toolResult`) and flat
          `permissionDecision` output. From docs; unverified.
"""

import json

HARNESSES = ("claude", "codex", "cursor", "copilot")

# harness tool name -> Claude Code tool name
TOOL_ALIASES = {
    "Shell": "Bash", "bash": "Bash", "shell": "Bash", "powershell": "Bash",
    "edit": "Edit", "create": "Write", "view": "Read", "glob": "Glob", "grep": "Grep",
    "web_fetch": "WebFetch", "task": "Agent",
}

# harness event name -> Claude Code event name
EVENT_ALIASES = {
    "sessionStart": "SessionStart", "beforeSubmitPrompt": "UserPromptSubmit",
    "userPromptSubmitted": "UserPromptSubmit", "preToolUse": "PreToolUse",
    "postToolUse": "PostToolUse", "stop": "Stop", "agentStop": "Stop",
}

# (source key, Claude key), first present wins
FIELD_ALIASES = [
    ("sessionId", "session_id"), ("conversation_id", "session_id"),
    ("toolName", "tool_name"), ("toolArgs", "tool_input"),
    ("toolResult", "tool_response"), ("tool_result", "tool_response"), ("tool_output", "tool_response"),
    ("toolUseId", "tool_use_id"), ("hookEventName", "hook_event_name"),
]

SUPPORTS_ASK = {"claude": True, "codex": False, "cursor": False, "copilot": True}


def to_claude(payload: dict, harness: str = "claude", event: str | None = None) -> dict:
    """A Claude-Code-shaped hook payload. `event` covers harnesses that don't name the event."""
    if harness == "claude":
        return payload
    p = dict(payload)
    for src, dst in FIELD_ALIASES:
        if src in p and dst not in p:
            p[dst] = p[src]
    if isinstance(p.get("tool_input"), str):  # copilot sends toolArgs as a JSON string
        try:
            p["tool_input"] = json.loads(p["tool_input"])
        except ValueError:
            p["tool_input"] = {"command": p["tool_input"]}
    if not p.get("cwd") and p.get("workspace_roots"):
        p["cwd"] = p["workspace_roots"][0]
    name = p.get("hook_event_name") or event or ""
    p["hook_event_name"] = EVENT_ALIASES.get(name, name)
    if p.get("tool_name"):
        p["tool_name"] = TOOL_ALIASES.get(p["tool_name"], p["tool_name"])
    p["harness"] = harness
    return p


def output(out: dict | None, harness: str = "claude") -> dict | None:
    """Translate good-cop's Claude-shaped PreToolUse output for the harness."""
    if not out or harness == "claude":
        return out
    hso = out["hookSpecificOutput"]
    decision, reason = hso["permissionDecision"], hso.get("permissionDecisionReason", "")
    if decision == "ask" and not SUPPORTS_ASK[harness]:
        decision, reason = "deny", reason + " (ask not supported by this harness; denied)"
    if harness == "codex":
        return {"hookSpecificOutput": {**hso, "permissionDecision": decision, "permissionDecisionReason": reason}}
    if harness == "cursor":
        return {"permission": decision, "user_message": reason, "agent_message": reason}
    return {"permissionDecision": decision, "permissionDecisionReason": reason}  # copilot


# apply_patch (Codex): file operations named in the patch envelope
PATCH_OPS = ("*** Add File: ", "*** Update File: ", "*** Delete File: ", "*** Move to: ")


def patch_paths(patch: str) -> list[str]:
    return [line[len(op):].strip() for line in (patch or "").splitlines()
            for op in PATCH_OPS if line.startswith(op)]
