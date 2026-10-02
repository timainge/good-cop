"""Named handlers: side effects when rules trip (post to Slack, write to syslog, page someone).

Handlers are registered once under `handlers:` in rules.yaml and referenced by name from a rule's
`on_trip` list (or `defaults.on_trip`). Types:

- `command`: a shell command that gets a redacted JSON event on stdin (integration logic lives in
  the script; see examples/handlers/).
- `webhook`: an HTTP request. `url` and `headers` expand `${ENV}`; `body` is a template (a string,
  or a dict/list whose strings are templates) filled with `{action}`, `{rules}`, `{tool}`,
  `{command}`, `{cwd}`, `{session}`, `{p}` and any payload key; without `body` the event JSON is sent.
- `file`: append the event as one JSON line to `path`.

    handlers:
      slack:  {type: webhook, url: "${SLACK_WEBHOOK_URL}", body: {text: "good-cop {action}: {rules} `{command}`"},
               only: [ask, deny], once_per_session: true}
      syslog: {type: command, command: "logger -t good-cop", timeout: 5}
      audit:  {type: file, path: "~/.good-cop/audit.jsonl"}
    defaults: {on_trip: [syslog]}
    rules:
      - {id: prod_target, question: ..., on_trip: [slack, syslog]}   # replaces the default list

Every type: `timeout`, `retries` (with backoff; default 2 for webhooks, else 0), `max_per_minute`
(across sessions), `only`, `once_per_session`.

Handlers run detached (no latency added to the tool call), time-boxed, and fail open.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import time
import traceback

from good_cop import redact, store

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
            if not h or h.get("type", "command") not in RUNNERS:
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
    return [f for f in store.read_jsonl(store.session_dir(session_id) / "handlers.jsonl") if not f.get("skipped")]


def _rate_ok(name: str, limit: int | None) -> bool:
    """At most `limit` starts per handler per rolling minute, across all sessions."""
    if not limit:
        return True
    path = store.ROOT / "handlers" / f"{name}.rate"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        now = time.time()
        times = []
        for x in f.read().split():
            try:
                t = float(x)
            except ValueError:  # a corrupt line must not stop other handlers
                continue
            if now - t < 60:
                times.append(t)
        ok = len(times) < limit
        if ok:
            times.append(now)
        f.seek(0)
        f.truncate()
        f.write("\n".join(str(t) for t in times))
    return ok


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
        if not _rate_ok(name, registry[name].get("max_per_minute")):
            store.append_jsonl(store.session_dir(session_id) / "handlers.jsonl",
                               {"ts": store.now(), "seq": payload.get("seq"), "handler": name, "rules": rule_ids,
                                "skipped": "max_per_minute"})
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
    """Execute one handler now (the detached child, or `good-cop handler NAME --test`), retrying
    failures with backoff. Returns 0 on success."""
    h = (rules_cfg.get("handlers") or {}).get(name)
    if not h:
        store.log_error(f"handler {name!r} is not registered")
        return 1
    kind = h.get("type", "command")
    fn = RUNNERS.get(kind)
    if not fn:
        store.log_error(f"handler {name!r}: unknown type {kind!r}")
        return 1
    retries = h.get("retries", 2 if kind == "webhook" else 0)
    for attempt in range(retries + 1):
        try:
            code = fn(name, payload, h)
        except Exception:
            store.log_error(f"handler {name!r}:\n{traceback.format_exc()}")
            code = 1
        if code in (0, NO_RETRY) or attempt == retries:
            return 1 if code == NO_RETRY else code
        time.sleep(min(h.get("backoff", 1.0) * 2 ** attempt, 30.0))
    return code


NO_RETRY = -1  # a runner's way to say "misconfigured, don't retry"


def _run_command(name: str, payload: dict, h: dict) -> int:
    env = {**os.environ,
           "GOOD_COP_HANDLER": name,
           "GOOD_COP_ACTION": str(payload.get("action", "")),
           "GOOD_COP_RULES": ",".join(t["id"] for t in payload.get("tripped", [])),
           "GOOD_COP_TOOL": str(payload.get("tool") or ""),
           "GOOD_COP_SESSION": str(payload.get("session_id") or "")}
    timeout = h.get("timeout", DEFAULT_TIMEOUT)
    try:
        r = subprocess.run(os.path.expanduser(h["command"]), shell=True, env=env, capture_output=True, text=True,
                           input=json.dumps(payload, default=str), timeout=timeout)
    except subprocess.TimeoutExpired:
        store.log_error(f"handler {name!r} timed out after {timeout}s")
        return 1
    if r.returncode:
        store.log_error(f"handler {name!r} exited {r.returncode}: {r.stderr.strip()[:500]}")
    return r.returncode


ENV_RE = re.compile(r"\$\{(\w+)\}")


def _expand(text: str) -> tuple[str, list[str]]:
    """`${VAR}` from the environment; returns the text and the names that were unset."""
    missing = []

    def sub(m):
        if m.group(1) not in os.environ:
            missing.append(m.group(1))
            return ""
        return os.environ[m.group(1)]
    return ENV_RE.sub(sub, text), missing


class _Fields(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def fields(payload: dict) -> dict:
    """Template fields: every payload key plus a few flattened conveniences."""
    inp = payload.get("input") or {}
    command = inp.get("command") if isinstance(inp, dict) and isinstance(inp.get("command"), str) else json.dumps(inp)
    tripped = payload.get("tripped") or []
    return _Fields({**payload, "rules": ", ".join(t["id"] for t in tripped), "command": command[:500],
                    "p": max((t.get("p") or 0 for t in tripped), default=0),
                    "session": str(payload.get("session_id") or "")[:8], "json": json.dumps(payload, default=str)})


def fill(template, values: dict):
    if isinstance(template, str):
        return template.format_map(values)
    if isinstance(template, dict):
        return {k: fill(v, values) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, values) for v in template]
    return template


def _run_webhook(name: str, payload: dict, h: dict) -> int:
    import httpx
    url, missing = _expand(h["url"])
    headers = {}
    for k, v in (h.get("headers") or {}).items():
        headers[k], m = _expand(str(v))
        missing += m
    if missing:  # the URL is often a secret: name the variable, never print the value
        store.log_error(f"handler {name!r}: {', '.join(missing)} not set; skipped")
        return NO_RETRY
    try:
        body = fill(h["body"], fields(payload)) if "body" in h else payload
    except (ValueError, KeyError, IndexError, AttributeError) as e:  # a template bug: retrying won't help
        store.log_error(f"handler {name!r}: body template error ({type(e).__name__}: {e})")
        return NO_RETRY
    if isinstance(body, str) and "content-type" not in {k.lower() for k in headers}:
        headers["content-type"] = "text/plain"
    kw = {"content": body, "headers": headers} if isinstance(body, str) else {"json": body, "headers": headers}
    try:
        r = httpx.request(h.get("method", "POST"), url, timeout=h.get("timeout", DEFAULT_TIMEOUT), **kw)
    except httpx.HTTPError as e:
        store.log_error(f"handler {name!r}: {type(e).__name__}")
        return 1
    if r.status_code >= 400:
        store.log_error(f"handler {name!r}: HTTP {r.status_code}")
        return 1 if r.status_code == 429 or r.status_code >= 500 else NO_RETRY
    return 0


def _run_file(name: str, payload: dict, h: dict) -> int:
    path, missing = _expand(os.path.expanduser(h["path"]))
    if missing:
        store.log_error(f"handler {name!r}: {', '.join(missing)} not set; skipped")
        return NO_RETRY
    from pathlib import Path
    store.append_jsonl(Path(path), payload)
    return 0


RUNNERS = {"command": _run_command, "webhook": _run_webhook, "file": _run_file}


SAMPLE = {
    "ts": "2026-09-28T00:00:00.000+00:00", "session_id": "test-session", "seq": 42, "harness": "claude",
    "cwd": "/home/me/project", "tool": "Bash", "input": {"command": "kubectl --context prod apply -f deploy.yaml"},
    "agent_id": None, "action": "ask", "enforced": "ask", "enforce": True,
    "tripped": [{"id": "prod_target", "p": 0.97, "source": "model", "action": "ask"}], "provider": "jev:jev-latest",
}
