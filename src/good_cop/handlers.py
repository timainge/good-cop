"""Named handlers: side effects when rules trip (post to Slack, write to syslog, page someone).

Handlers are registered once under `handlers:` in rules.yaml and referenced by name from a rule's
`on_trip` list (or `defaults.on_trip`). The only type today is `command`: a shell command that gets
a redacted JSON event on stdin. Integration logic (Slack formatting, webhook URLs, retries) lives
in those scripts, not here; see examples/handlers/.

    handlers:
      slack:  {type: command, command: "~/.good-cop/handlers/slack.sh", only: [ask, deny], once_per_session: true}
      syslog: {type: command, command: "logger -t good-cop", timeout: 5}
    defaults: {on_trip: [syslog]}
    rules:
      - {id: prod_target, question: ..., on_trip: [slack, syslog]}   # replaces the default list

Handlers run detached (no latency added to the tool call), time-boxed, and fail open.
"""

import json
import os
import subprocess
import sys
import traceback

from good_cop import redact, store

TYPES = {"command"}
DEFAULT_TIMEOUT = 10.0


def plan(rules_cfg: dict, decision: dict) -> list[str]:
    """Handler names a decision triggers: tripped rules' `on_trip` (or the default), filtered by `only`."""
    registry = rules_cfg.get("handlers") or {}
    defaults = rules_cfg["defaults"]
    names = []
    for rule in rules_cfg["rules"]:
        res = decision["results"].get(rule["id"])
        if not res or not res.get("tripped"):
            continue
        action = rule.get("action", defaults["action"])
        for name in rule.get("on_trip", defaults.get("on_trip") or []):
            h = registry.get(name)
            if not h or h.get("type", "command") not in TYPES:
                store.log_error(f"on_trip: unknown handler {name!r} in rule {rule['id']!r}")
                continue
            if h.get("only") and action not in h["only"]:
                continue
            names.append(name)
    return list(dict.fromkeys(names))


def event_payload(event: dict, decision: dict, rules_cfg: dict) -> dict:
    """What a handler receives: compact and redacted, never the full decision state."""
    defaults = rules_cfg["defaults"]
    actions = {r["id"]: r.get("action", defaults["action"]) for r in rules_cfg["rules"]}
    tripped = [{"id": rid, "p": r["p"], "source": r["source"], "action": actions.get(rid)}
               for rid, r in decision["results"].items() if r.get("tripped")]
    payload, _ = redact.redact_obj({
        "ts": store.now(), "session_id": event.get("session_id"), "seq": event.get("seq"),
        "harness": event.get("harness", "claude"), "cwd": event.get("cwd"), "tool": event.get("tool"),
        "input": store.truncate(event.get("input"), 2000), "agent_id": event.get("agent_id"),
        "action": decision["action"], "enforced": decision["enforced"], "enforce": bool(rules_cfg.get("enforce")),
        "tripped": tripped, "provider": decision.get("provider"),
    })
    return payload


def _fired(session_id: str) -> list[dict]:
    return store.read_jsonl(store.session_dir(session_id) / "handlers.jsonl")


def dispatch(session_id: str, names: list[str], payload: dict, rules_cfg: dict) -> list[str]:
    """Start each handler detached; skip once_per_session repeats. Returns the names started."""
    registry = rules_cfg.get("handlers") or {}
    rule_ids = sorted(t["id"] for t in payload["tripped"])
    started = []
    for name in names:
        if registry[name].get("once_per_session"):
            seen = {rid for f in _fired(session_id) if f["handler"] == name for rid in f["rules"]}
            if set(rule_ids) <= seen:
                continue
        proc = subprocess.Popen([sys.executable, "-m", "good_cop.cli", "handler", name],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True)
        proc.stdin.write(json.dumps(payload, default=str).encode())
        proc.stdin.close()
        store.append_jsonl(store.session_dir(session_id) / "handlers.jsonl",
                           {"ts": store.now(), "seq": payload.get("seq"), "handler": name, "rules": rule_ids})
        started.append(name)
    return started


def run(name: str, payload: dict, rules_cfg: dict) -> int:
    """Execute one handler now (the detached child, or `good-cop handler NAME --test`)."""
    h = (rules_cfg.get("handlers") or {}).get(name)
    if not h:
        store.log_error(f"handler {name!r} is not registered")
        return 1
    env = {**os.environ,
           "GOOD_COP_HANDLER": name,
           "GOOD_COP_ACTION": str(payload.get("action", "")),
           "GOOD_COP_RULES": ",".join(t["id"] for t in payload.get("tripped", [])),
           "GOOD_COP_TOOL": str(payload.get("tool") or ""),
           "GOOD_COP_SESSION": str(payload.get("session_id") or "")}
    try:
        r = subprocess.run(os.path.expanduser(h["command"]), shell=True, env=env, capture_output=True, text=True,
                           input=json.dumps(payload, default=str), timeout=h.get("timeout", DEFAULT_TIMEOUT))
    except subprocess.TimeoutExpired:
        store.log_error(f"handler {name!r} timed out after {h.get('timeout', DEFAULT_TIMEOUT)}s")
        return 1
    except Exception:
        store.log_error(f"handler {name!r}:\n{traceback.format_exc()}")
        return 1
    if r.returncode:
        store.log_error(f"handler {name!r} exited {r.returncode}: {r.stderr.strip()[:500]}")
    return r.returncode


SAMPLE = {
    "ts": "2026-09-28T00:00:00.000+00:00", "session_id": "test-session", "seq": 42, "harness": "claude",
    "cwd": "/home/me/project", "tool": "Bash", "input": {"command": "kubectl --context prod apply -f deploy.yaml"},
    "agent_id": None, "action": "ask", "enforced": "ask", "enforce": True,
    "tripped": [{"id": "prod_target", "p": 0.97, "source": "model", "action": "ask"}], "provider": "jev:jev-latest",
}
