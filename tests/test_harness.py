import json

from conftest import FIXTURES, write_rules
from good_cop import cli, config, harness, hook, install, ledger, store

CODEX = [json.loads(l) for l in (FIXTURES / "codex" / "hook_payloads.jsonl").read_text().splitlines() if l.strip()]


def test_codex_session_end_to_end(home):
    write_rules(home, "rules:\n  - {id: md, when: {tools: [Edit, Write]}, pattern: 'deploy'}\n")
    cfg = config.load_config()
    for p in CODEX:
        hook.handle(harness.to_claude(p, "codex"), cfg)
    sid = CODEX[0]["session_id"]
    events = store.read_events(sid)
    assert [e["type"] for e in events][:3] == ["session_start", "probe", "prompt"]
    assert all(e.get("harness") == "codex" for e in events if e["type"] != "probe")
    led = store.read_json(store.session_dir(sid) / "ledger.json")
    assert led == ledger.rebuild(events)
    info = led["files_written"]["/tmp/gc-codex/deploy.sh"]
    assert info["tool"] == "apply_patch" and info["executable_hint"]
    assert led["flags"]["ran_script_written_this_session"]
    d = store.read_jsonl(store.session_dir(sid) / "decisions.jsonl")
    assert [x["tool"] for x in d] == ["apply_patch", "Bash", "apply_patch", "Bash"]
    assert d[0]["results"]["md"]["tripped"]  # Edit/Write rule applies to apply_patch
    assert "md" not in d[1]["results"]


def test_ask_degrades_to_deny_where_unsupported():
    out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "ask",
                                  "permissionDecisionReason": "good-cop: x"}}
    assert harness.output(out, "claude") == out
    assert harness.output(out, "codex")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert harness.output(out, "cursor")["permission"] == "deny"
    assert harness.output(out, "copilot")["permissionDecision"] == "ask"
    assert harness.output(None, "codex") is None


def test_camelcase_and_cursor_payloads():
    p = harness.to_claude({"sessionId": "s", "cwd": "/w", "toolName": "bash", "toolArgs": '{"command": "ls"}'},
                          "copilot", "preToolUse")
    assert p["hook_event_name"] == "PreToolUse" and p["tool_name"] == "Bash" and p["tool_input"] == {"command": "ls"}
    p = harness.to_claude({"conversation_id": "c", "workspace_roots": ["/w"], "hook_event_name": "postToolUse",
                           "tool_name": "Shell", "tool_input": {"command": "ls"}, "tool_output": "x"}, "cursor")
    assert (p["session_id"], p["cwd"], p["hook_event_name"], p["tool_name"], p["tool_response"]) == \
           ("c", "/w", "PostToolUse", "Bash", "x")


def test_patch_paths():
    patch = "*** Begin Patch\n*** Add File: a.sh\n+x\n*** Update File: b.py\n*** Move to: c.py\n*** Delete File: d\n*** End Patch"
    assert harness.patch_paths(patch) == ["a.sh", "b.py", "c.py", "d"]


def test_install_each_harness(home, tmp_path):
    for h in ("codex", "cursor", "copilot"):
        path = tmp_path / f"{h}.json"
        path.write_text(json.dumps({"hooks": {install.TARGETS[h][1][0]: [{"command": "other"}] if h != "codex"
                                              else [{"hooks": [{"type": "command", "command": "other"}]}]}}))
        cli.main(["install", "--harness", h, "--settings", str(path)])
        cli.main(["install", "--harness", h, "--settings", str(path)])  # idempotent
        s = json.loads(path.read_text())
        pre = install.TARGETS[h][1][2]
        text = json.dumps(s["hooks"][pre])
        assert text.count(f"hook --harness {h}") == 1
        if h != "codex":
            assert f"--event {pre}" in text and s["version"] == 1
        cli.main(["uninstall", "--harness", h, "--settings", str(path)])
        assert "good-cop" not in path.read_text() and "other" in path.read_text()
