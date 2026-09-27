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
