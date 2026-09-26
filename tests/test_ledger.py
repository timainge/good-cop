from good_cop import ledger


def test_executed_scripts():
    f = ledger.executed_scripts
    assert f("./deploy.sh") == ["./deploy.sh"]
    assert f("chmod +x x.sh && ./x.sh --prod") == ["./x.sh"]
    assert f("bash scripts/run.sh") == ["scripts/run.sh"]
    assert f("FOO=1 python3 tools/gen.py -v") == ["tools/gen.py"]
    assert f("uv run python main.py") == ["main.py"]
    assert f("ls -la; git status") == []
    assert f("python -c 'print(1)'") == []


def test_fold_is_pure_and_tracks_hosts():
    l0 = ledger.empty()
    e = {"seq": 1, "type": "post_tool", "tool": "Bash", "cwd": "/w",
         "input": {"command": "curl -s https://API.example.com/x"}}
    l1 = ledger.fold(l0, e)
    assert l0 == ledger.empty()
    assert l1["hosts_contacted"] == ["api.example.com"] and l1["last_event_seq"] == 1
    l2 = ledger.fold(l1, {"seq": 2, "type": "post_tool", "tool": "WebFetch", "input": {"url": "https://docs.x.io/a"}})
    assert l2["hosts_contacted"] == ["api.example.com", "docs.x.io"]


def test_unknown_tool_ignored():
    l1 = ledger.fold(ledger.empty(), {"seq": 3, "type": "post_tool", "tool": "Mystery", "input": {}})
    assert {**l1, "last_event_seq": 0} == ledger.empty()
