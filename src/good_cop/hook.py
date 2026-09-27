"""Live hook entry: dispatch on hook_event_name, time-boxed, fail open. See plan.md §1."""

import json
import signal
import sys
import time
import traceback

from good_cop import config, context, ledger as ledger_mod, probes, rules, store, summary

EVENT_TYPES = {
    "SessionStart": "session_start",
    "UserPromptSubmit": "prompt",
    "PreToolUse": "pre_tool",
    "PostToolUse": "post_tool",
    "Stop": "stop",
    "SubagentStop": "stop",
}
FIELDS = [("tool_name", "tool"), ("tool_input", "input"), ("tool_response", "result"),
          ("tool_use_id", "tool_use_id"), ("prompt", "prompt"), ("source", "source"),
          ("agent_id", "agent_id"), ("agent_type", "agent_type")]


class Budget(Exception):
    pass


def main() -> int:
    t0 = time.monotonic()
    try:
        payload = json.load(sys.stdin)
        cfg = config.load_config()
        signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(Budget("hook budget exceeded")))
        signal.setitimer(signal.ITIMER_REAL, cfg.get("hook_budget", 5.0))
        out = handle(payload, cfg, t0)
        signal.setitimer(signal.ITIMER_REAL, 0)
        if out:
            print(json.dumps(out))
    except BaseException:
        signal.setitimer(signal.ITIMER_REAL, 0)
        store.log_error(traceback.format_exc())
    return 0  # never break Claude Code


def normalise(payload: dict) -> dict:
    name = payload.get("hook_event_name", "")
    event = {"type": EVENT_TYPES.get(name, name.lower()), "cwd": payload.get("cwd")}
    for src, dst in FIELDS:
        if src in payload:
            event[dst] = payload[src]
    return store.truncate(event)


def sync_ledger(session_id: str) -> tuple[dict, list[dict]]:
    """Fold any events not yet in ledger.json, under the session lock."""
    with store.locked(session_id) as d:
        ledger = store.read_json(d / "ledger.json") or ledger_mod.empty()
        events = store.read_events(session_id)
        for e in events:
            if e["seq"] > ledger["last_event_seq"]:
                ledger = ledger_mod.fold(ledger, e)
        store.write_json_atomic(d / "ledger.json", ledger)
    return ledger, events


def handle(payload: dict, cfg: dict, t0: float | None = None) -> dict | None:
    t0 = t0 or time.monotonic()
    sid = payload["session_id"]
    event = normalise(payload)
    probe_list = cfg.get("probes") or probes.DEFAULT_PROBES

    if event["type"] == "pre_tool" and event.get("tool") == "Bash":
        ledger, _ = sync_ledger(sid)
        script = context.resolve_script(event.get("input"), event.get("cwd"), ledger, context.read_disk)
        if script:
            event["resolved"] = {"script": script}

    event = store.append_event(sid, event)

    if event["type"] == "session_start":
        store.append_event(sid, {"type": "probe", "facts": probes.run(probe_list, event.get("cwd"))})
    elif event["type"] == "post_tool" and event.get("tool") == "Bash":
        hit = probes.triggered(probe_list, (event.get("input") or {}).get("command", ""))
        if hit:
            store.append_event(sid, {"type": "probe", "facts": probes.run(hit, event.get("cwd"))})

    ledger, events = sync_ledger(sid)

    if event["type"] == "pre_tool":
        return decide(sid, event, ledger, events, cfg, t0)
    if event["type"] in ("post_tool", "stop"):
        summary.maybe_spawn(sid, ledger, cfg)
    return None


def decide(sid: str, event: dict, ledger: dict, events: list[dict], cfg: dict, t0: float) -> dict | None:
    rules_cfg = config.load_rules()
    if not rules_cfg["rules"]:
        return None
    summ = store.read_json(summary.summary_path(sid)) if cfg["summary"].get("enabled") else None
    recent = [e for e in events if e["seq"] < event["seq"]][-context.RECENT:]
    state = context.build_state(event, ledger, summ, recent, cfg.get("max_state_tokens", 8000))

    needs_model = any(r.get("question") and rules.applies(r, event.get("tool")) for r in rules_cfg["rules"])
    opts = {}
    if needs_model:
        from good_cop import providers
        opts = providers.judge_options(cfg)
    decision = rules.evaluate(rules_cfg, state, **opts)
    decision = {"seq": event["seq"], "ts": store.now(), "tool": event.get("tool"), **decision,
                "hook_ms": round((time.monotonic() - t0) * 1000)}
    store.append_jsonl(store.session_dir(sid) / "decisions.jsonl", decision)

    if decision["enforced"] in ("ask", "deny"):
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": decision["enforced"],
                                       "permissionDecisionReason": rules.reason(decision)}}
    return None
