import io
import json

from conftest import write_rules
from good_cop import cli, config, hook, ledger, store


def run_all(payloads):
    cfg = config.load_config()
    return [hook.handle(p, cfg) for p in payloads]


def test_hook_fails_open(home, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert cli.main(["hook"]) == 0
    assert "JSONDecodeError" in (home / "errors.log").read_text()


def test_capture_session(home, payloads, fake_llm):
    run_all(payloads)
    sid = payloads[0]["session_id"]
    events = store.read_events(sid)
    types = [e["type"] for e in events]
    assert types[:3] == ["session_start", "probe", "prompt"]
    assert types.count("pre_tool") == types.count("post_tool") == 7
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    sub = [e for e in events if e.get("agent_id")]
    assert sub and all(e["tool"] == "Bash" for e in sub)

    led = store.read_json(store.session_dir(sid) / "ledger.json")
    assert led == ledger.rebuild(events)
    assert "/tmp/gc-work/deploy.sh" in led["files_written"]
    assert led["files_written"]["/tmp/gc-work/deploy.sh"]["executable_hint"]
    assert led["flags"]["ran_script_written_this_session"]
    assert led["commands"]["count"] == 3

    # every PreToolUse produced a decision with the default rules
    decisions = store.read_jsonl(store.session_dir(sid) / "decisions.jsonl")
    assert len(decisions) == 7 and all(d["enforced"] == "allow" for d in decisions)
    assert [d["action"] for d in decisions if d["action"] != "allow"] == ["log"]  # ./deploy.sh: runs_session_script
    assert all("hook_ms" in d for d in decisions)


def test_resolved_script_recorded(home, payloads, fake_llm, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "deploy.sh").write_text("#!/bin/sh\necho deploying to staging\n")
    ps = [json.loads(json.dumps(p).replace("/tmp/gc-work", str(work))) for p in payloads]
    run_all(ps)
    pre = [e for e in store.read_events(ps[0]["session_id"])
           if e["type"] == "pre_tool" and "./deploy.sh" in e["input"].get("command", "")][0]
    script = pre["resolved"]["script"]
    assert script["written_this_session"] and "staging" in script["head"]


def test_judge_failure_fails_open(home, payloads, fake_llm):
    fake_llm.fail = True
    write_rules(home, "enforce: true\nrules:\n  - {id: any, question: 'anything?', action: deny}\n")
    outs = run_all(payloads)
    assert all(o is None for o in outs)
    d = store.read_jsonl(store.session_dir(payloads[0]["session_id"]) / "decisions.jsonl")
    assert d and all(x["error"] and x["action"] == "allow" for x in d)


def test_enforce_deny_pattern(home, payloads):
    write_rules(home, "enforce: true\nrules:\n  - {id: no_ls, when: {tools: [Bash]}, pattern: '^ls\\b', action: deny}\n")
    outs = run_all(payloads)
    denied = [o for o in outs if o]
    assert len(denied) == 1
    out = denied[0]["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "no_ls" in out["permissionDecisionReason"]


def test_log_mode_never_outputs(home, payloads):
    write_rules(home, "enforce: false\nrules:\n  - {id: no_ls, pattern: '^ls\\b', action: deny}\n")
    assert all(o is None for o in run_all(payloads))
    d = store.read_jsonl(store.session_dir(payloads[0]["session_id"]) / "decisions.jsonl")
    assert [x["action"] for x in d].count("deny") == 1


def test_context_change_probe(home, payloads, monkeypatch):
    values = iter(["dev", "prod"])
    monkeypatch.setattr("good_cop.probes.run_one", lambda p, cwd: next(values) if p["name"] == "kube_context" else None)
    write_rules(home, "rules: []\n")
    cfg = config.load_config()
    sid = payloads[0]["session_id"]
    hook.handle(payloads[0], cfg)
    post = {**payloads[5], "tool_input": {"command": "kubectl config use-context prod"}}
    hook.handle(post, cfg)
    led = store.read_json(store.session_dir(sid) / "ledger.json")
    assert led["env"]["kube_context"] == "prod"
    assert led["context_changes"][0]["from"] == "dev" and led["context_changes"][0]["to"] == "prod"


def test_install_uninstall(home, tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}))
    cli.main(["install", "--settings", str(settings)])
    cli.main(["install", "--settings", str(settings)])  # idempotent
    s = json.loads(settings.read_text())
    assert len(s["hooks"]["PreToolUse"]) == 1 and len(s["hooks"]["Stop"]) == 2
    assert (home / "rules.yaml").exists() and (home / "config.yaml").exists()
    cli.main(["uninstall", "--settings", str(settings)])
    assert json.loads(settings.read_text()) == {"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "other"}]}]}}
