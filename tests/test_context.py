from good_cop import context, ledger


def test_build_state_caps_size():
    led = ledger.empty()
    recent = [{"seq": i, "type": "post_tool", "tool": "Bash", "input": {"command": "x" * 2000},
               "result": "y" * 2000} for i in range(10)]
    event = {"seq": 11, "type": "pre_tool", "tool": "Bash", "input": {"command": "z" * 50000}}
    state = context.build_state(event, led, None, recent, max_tokens=2000)
    assert context.size(state) <= 2000 + 50
    assert state["summary"] is None and state["recent"] == []


def test_resolve_script():
    led = ledger.empty()
    led["files_written"]["/w/deploy.sh"] = {}
    r = context.resolve_script({"command": "./deploy.sh prod"}, "/w", led, lambda p: "#!/bin/sh\necho hi")
    assert r == {"path": "/w/deploy.sh", "written_this_session": True, "head": "#!/bin/sh\necho hi"}
    assert context.resolve_script({"command": "ls"}, "/w", led) is None


def test_writes():
    w = context.writes
    assert w({"tool": "Bash", "cwd": "/w", "input": {"command": "cd ~/x && cat README.md"}}) == []
    assert w({"tool": "Bash", "cwd": "/w", "input": {"command": "echo hi > /tmp/o.txt; echo > a.txt"}}) == [
        {"path": "/tmp/o.txt", "outside_cwd": True}, {"path": "/w/a.txt", "outside_cwd": False}]
    assert w({"tool": "Edit", "cwd": "/w", "input": {"file_path": "/w2/x.py"}}) == [{"path": "/w2/x.py", "outside_cwd": True}]
