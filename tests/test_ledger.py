from good_cop import ledger


def test_executed_scripts():
    f = ledger.executed_scripts
    assert f("./deploy.sh", "/w") == ["/w/deploy.sh"]
    assert f("chmod +x x.sh && ./x.sh --prod", "/w") == ["/w/x.sh"]
    assert f("bash scripts/run.sh", "/w") == ["/w/scripts/run.sh"]
    assert f("FOO=1 python3 tools/gen.py -v", "/w") == ["/w/tools/gen.py"]
    assert f("uv run python main.py", "/w") == ["/w/main.py"]
    assert f("ls -la; git status /usr/bin/x", "/w") == []
    assert f("python -c 'print(1)'", "/w") == []


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


def test_executed_scripts_shell_forms():
    f = ledger.executed_scripts
    assert f("cd sub && ./run.sh", "/w") == ["/w/sub/run.sh"]
    assert f("S=/tmp/s; bash $S/run.sh x", "/w") == ["/tmp/s/run.sh"]
    assert f("echo '{}' | .claude/hooks/guard.sh", "/w") == ["/w/.claude/hooks/guard.sh"]
    assert f("npx tsx server/index.ts", "/w") == ["/w/server/index.ts"]
    assert f("cat > x.sh <<'EOF'\n./not-run.sh\nEOF\nls", "/w") == []


def test_shell_writes():
    f = ledger.shell_writes
    assert f("cat > run.sh <<'EOF'\necho hi > nope.txt\nEOF", "/w") == ["/w/run.sh"]
    assert f("echo x >> log.txt 2>&1 >/dev/null", "/w") == ["/w/log.txt"]
    assert f("printf x | tee -a a.txt b.txt", "/w") == ["/w/a.txt", "/w/b.txt"]
    assert f("cd d && cp /tmp/shot.mjs out/shot.mjs", "/w") == ["/w/d/out/shot.mjs"]


def test_bash_written_script_flag():
    led = ledger.empty()
    led = ledger.fold(led, {"seq": 1, "type": "post_tool", "tool": "Bash", "cwd": "/w",
                            "input": {"command": "cat > go.sh <<'EOF'\necho hi\nEOF\nchmod +x go.sh"}})
    assert led["files_written"]["/w/go.sh"]["tool"] == "Bash"
    led = ledger.fold(led, {"seq": 2, "type": "post_tool", "tool": "Bash", "cwd": "/w", "input": {"command": "./go.sh"}})
    assert led["flags"]["ran_script_written_this_session"]


def test_unwrap_launchers():
    f = ledger.executed_scripts
    assert f("timeout 60 ./slow.sh", "/w") == ["/w/slow.sh"]
    assert f("uv run --quiet python tools/x.py", "/w") == ["/w/tools/x.py"]
    assert f("uv run --with rich python y.py", "/w") == ["/w/y.py"]
    assert ledger._unwrap(["npx", "-y", "playwright", "test"]) == ["playwright", "test"]


def test_quoted_operators_are_not_separators():
    f = ledger.executed_scripts
    assert f("sed -n '/app.put(.\\/api\\/x/,/^});/p' server/index.ts", "/w") == []
    assert f("grep -E 'a|./b.sh' f.txt && ./real.sh", "/w") == ["/w/real.sh"]
    assert ledger.shell_writes("cp a b 2>/dev/null; echo 'x > y' > out.txt", "/w") == ["/w/b", "/w/out.txt"]
    assert ledger.shell_writes("echo hi 2>&1 >> log.txt", "/w") == ["/w/log.txt"]
    assert f("cd sub\n./run.sh", "/w") == ["/w/sub/run.sh"]
