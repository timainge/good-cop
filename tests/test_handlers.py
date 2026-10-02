import json
import subprocess
import time

from conftest import write_rules
from good_cop import backtest, config, handlers, hook, store, transcripts
from conftest import FIXTURES

RULES = """
handlers:
  file:   {type: command, command: "cat >> {out}"}
  notice: {type: command, command: "echo $GOOD_COP_ACTION:$GOOD_COP_RULES >> {out}.env", only: [deny]}
defaults: {threshold: 0.6, action: ask, on_trip: [file]}
rules:
  - {id: ls_cmd, when: {tools: [Bash]}, pattern: '^ls\\b', action: deny, on_trip: [file, notice]}
  - {id: echo_cmd, when: {tools: [Bash]}, pattern: '^echo', action: log}
"""


def decision(*tripped):
    return {"results": {rid: {"p": 1.0, "source": "pattern", "tripped": True} for rid in tripped},
            "action": "deny", "enforced": "allow"}


def test_plan(home, tmp_path):
    write_rules(home, RULES.replace("{out}", str(tmp_path / "o")) + "  - {id: bad, pattern: x, on_trip: [nope]}\n")
    rc = config.load_rules()
    assert handlers.plan(rc, decision("ls_cmd")) == ["file", "notice"]
    assert handlers.plan(rc, decision("echo_cmd")) == ["file"]              # default on_trip
    assert handlers.plan(rc, decision("bad")) == []                        # unknown handler skipped
    assert "unknown handler 'nope'" in (home / "errors.log").read_text()
    assert handlers.plan(rc, {"results": {"ls_cmd": {"p": 0.0, "tripped": False}}}) == []


def test_run_passes_stdin_env_and_logs_failures(home, tmp_path):
    out = tmp_path / "o"
    write_rules(home, RULES.replace("{out}", str(out)))
    rc = config.load_rules()
    rc["handlers"]["slow"] = {"type": "command", "command": "sleep 5", "timeout": 0.2}
    rc["handlers"]["fail"] = {"type": "command", "command": "echo boom >&2; exit 3"}
    assert handlers.run("file", handlers.SAMPLE, rc) == 0
    assert json.loads(out.read_text())["tripped"][0]["id"] == "prod_target"
    assert handlers.run("notice", handlers.SAMPLE, rc) == 0
    assert (tmp_path / "o.env").read_text().strip() == "ask:prod_target"
    assert handlers.run("slow", handlers.SAMPLE, rc) == 1 and handlers.run("fail", handlers.SAMPLE, rc) == 3
    log = (home / "errors.log").read_text()
    assert "timed out" in log and "exited 3: boom" in log


def test_once_per_session(home, monkeypatch):
    started = []

    class P:
        def __init__(self, cmd, **kw):
            started.append(cmd[-1])
            self.stdin = open("/dev/null", "wb")
    monkeypatch.setattr(subprocess, "Popen", P)
    rc = {"handlers": {"a": {"type": "command", "command": "true", "once_per_session": True},
                       "b": {"type": "command", "command": "true"}}}
    payload = {"seq": 1, "tripped": [{"id": "r1"}]}
    for _ in range(3):
        handlers.dispatch("s", ["a", "b"], payload, rc)
    assert started == ["a", "b", "b", "b"]
    handlers.dispatch("s", ["a"], {"seq": 2, "tripped": [{"id": "r2"}]}, rc)  # new rule: fires again
    assert started[-1] == "a" and len(store.read_jsonl(store.session_dir("s") / "handlers.jsonl")) == 5


def test_hook_dispatches_detached_with_redacted_payload(home, payloads, tmp_path, monkeypatch):
    monkeypatch.setenv("GOOD_COP_HOME", str(home))  # the detached child reads config from here
    monkeypatch.setenv("SUPER_SECRET_TOKEN", "echo-canary-12345")
    out = tmp_path / "o"
    write_rules(home, RULES.replace("{out}", str(out)))
    cfg = config.load_config()
    ps = [p if "ls -la" not in json.dumps(p) else
          {**p, "tool_input": {"command": "ls -la # echo-canary-12345"}} for p in payloads]
    for p in ps:
        hook.handle(p, cfg)
    for _ in range(50):  # handlers run detached; wait for both to land
        if out.exists() and "ls_cmd" in out.read_text() and (tmp_path / "o.env").exists():
            break
        time.sleep(0.1)
    text = out.read_text()
    assert "ls_cmd" in text and "echo-canary-12345" not in text and "[REDACTED]" in text
    assert (tmp_path / "o.env").read_text().strip() == "deny:ls_cmd"
    sid = payloads[0]["session_id"]
    d = store.read_jsonl(store.session_dir(sid) / "decisions.jsonl")
    assert any(x["handlers"] == ["file", "notice"] for x in d)


def test_backtest_is_a_dry_run(home, tmp_path, fake_llm):
    out = tmp_path / "o"
    write_rules(home, RULES.replace("{out}", str(out)))
    sid, _ = transcripts.import_transcript(next((FIXTURES / "transcript").glob("*.jsonl")))
    result = backtest.run([sid], [None])
    planned = [d["handlers"] for d in result["runs"][0]["decisions"]]
    assert ["file", "notice"] in planned and not out.exists()
    m = backtest.metrics(backtest.records(result), result["rules"]["rules"], {})
    assert m["configs"][0]["handlers"]["file"] >= 1


import http.server
import threading

import pytest


@pytest.fixture
def server():
    """A local HTTP server that records requests; `codes` is the queue of statuses to return."""
    got, codes = [], []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("content-length") or 0)
            got.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(n).decode()})
            self.send_response(codes.pop(0) if codes else 200)
            self.end_headers()
            self.wfile.write(b"ok")
        do_PUT = do_POST

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", got, codes
    srv.shutdown()


def test_webhook_template_env_and_retry(home, server, monkeypatch):
    url, got, codes = server
    monkeypatch.setenv("HOOK_URL", url + "/services/T0/B0/secretpart")
    monkeypatch.setenv("HOOK_TOKEN", "tok123")
    rc = {"handlers": {
        "slack": {"type": "webhook", "url": "${HOOK_URL}", "headers": {"Authorization": "Bearer ${HOOK_TOKEN}"},
                  "body": {"text": "good-cop {action}: {rules} on {tool} `{command}` p={p} {nope}"}, "backoff": 0.01},
        "raw": {"type": "webhook", "url": url + "/raw", "method": "PUT", "retries": 0},
        "text": {"type": "webhook", "url": url + "/t", "body": "{session} {rules}"},
        "unset": {"type": "webhook", "url": "${NOT_SET_ANYWHERE}/x"},
    }}
    codes += [503, 200]  # first attempt fails, the retry succeeds
    assert handlers.run("slack", handlers.SAMPLE, rc) == 0
    assert len(got) == 2 and got[1]["path"] == "/services/T0/B0/secretpart"
    assert got[1]["headers"]["Authorization"] == "Bearer tok123"
    assert json.loads(got[1]["body"]) == {"text": "good-cop ask: prod_target on Bash "
                                                  "`kubectl --context prod apply -f deploy.yaml` p=0.97 {nope}"}
    assert handlers.run("raw", handlers.SAMPLE, rc) == 0 and json.loads(got[2]["body"])["seq"] == 42
    assert handlers.run("text", handlers.SAMPLE, rc) == 0 and got[3]["body"] == "test-ses prod_target"
    assert handlers.run("unset", handlers.SAMPLE, rc) == 1 and len(got) == 4  # skipped, not retried
    codes += [400]
    assert handlers.run("slack", handlers.SAMPLE, rc) == 1 and len(got) == 5  # 4xx: not retried
    log = (home / "errors.log").read_text()
    assert "NOT_SET_ANYWHERE not set" in log and "HTTP 503" in log and "secretpart" not in log


def test_file_handler_and_plan_types(home, tmp_path):
    out = tmp_path / "audit" / "a.jsonl"
    rc = {"handlers": {"audit": {"type": "file", "path": str(out)}, "bad": {"type": "carrier-pigeon"}},
          "defaults": {"action": "ask"}, "rules": [{"id": "ls_cmd", "on_trip": ["audit", "bad"]}]}
    assert handlers.plan(rc, decision("ls_cmd")) == ["audit"]
    assert handlers.run("audit", handlers.SAMPLE, rc) == 0 and handlers.run("audit", handlers.SAMPLE, rc) == 0
    assert [json.loads(l)["seq"] for l in out.read_text().splitlines()] == [42, 42]
    assert handlers.run("bad", handlers.SAMPLE, rc) == 1


def test_max_per_minute(home, monkeypatch):
    started = []

    class P:
        def __init__(self, cmd, **kw):
            started.append(cmd[-1])
            self.stdin = open("/dev/null", "wb")
    monkeypatch.setattr(subprocess, "Popen", P)
    rc = {"handlers": {"a": {"type": "webhook", "url": "http://x", "max_per_minute": 2}}}
    for i in range(4):
        handlers.dispatch(f"s{i % 2}", ["a"], {"seq": i, "tripped": [{"id": "r"}]}, rc)  # limit spans sessions
    assert started == ["a", "a"]
    skipped = [f for s in ("s0", "s1") for f in store.read_jsonl(store.session_dir(s) / "handlers.jsonl") if f.get("skipped")]
    assert len(skipped) == 2
