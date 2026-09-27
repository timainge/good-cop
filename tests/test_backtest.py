from types import SimpleNamespace

from conftest import FIXTURES, write_rules
from good_cop import backtest, store, transcripts

T = next((FIXTURES / "transcript").glob("*.jsonl"))
RULES = """
rules:
  - {id: runs_script, when: {tools: [Bash]}, question: 'Does this run a script?'}
  - {id: echo, when: {tools: [Bash]}, pattern: 'echo'}
"""


def test_backtest_with_labels(home, fake_llm, capsys):
    sid, _ = transcripts.import_transcript(T)
    write_rules(home, RULES)
    fake_llm.by_keyword = {'"command": "chmod +x deploy.sh': 0.9}  # the call itself, not an escaped `recent` copy
    pres = [e for e in store.read_events(sid) if e["type"] == "pre_tool" and e["tool"] == "Bash"]
    for e in pres:
        backtest.label(sid, e["seq"], "runs_script", "./deploy.sh" in e["input"]["command"])
    args = SimpleNamespace(all=False, sessions=[sid[:8]], config=None, rules=None, note="t",
                           with_summary=False, limit=None, workers=2)
    assert backtest.main(args) == 0
    out = capsys.readouterr().out
    assert "3 tool calls" in out
    assert "runs_script" in out and "echo  [pattern]" in out
    assert list((home / "backtests").glob("*.jsonl"))
    doc = store.read_json(next((home / "backtests").glob("*.summary.json")))
    assert doc["meta"]["note"] == "t" and doc["meta"]["rules"][0]["id"] == "runs_script"
    rs = doc["metrics"]["rules"]["runs_script"]["by_config"]["default"]
    assert rs["evaluated"] == 3 and rs["n"] == 3 and rs["recall"] == 1.0
    assert backtest.evals() == 0 and "runs_script=" in capsys.readouterr().out


def test_replay_matches_live_state(home, payloads, fake_llm):
    """Backtest must build the same state live mode did (same hash)."""
    from good_cop import config, hook
    write_rules(home, "rules:\n  - {id: q, question: 'anything?'}\n")
    cfg = config.load_config()
    for p in payloads:
        hook.handle(p, cfg)
    sid = payloads[0]["session_id"]
    live = {d["seq"]: d["state_hash"] for d in store.read_jsonl(store.session_dir(sid) / "decisions.jsonl")}
    result = backtest.run([sid], [None])
    replayed = {e["seq"]: d["state_hash"] for (_, e, _), d in zip(result["items"], result["runs"][0]["decisions"])}
    assert replayed == live


def test_with_summary(home, fake_llm):
    sid, _ = transcripts.import_transcript(T)
    events = store.read_events(sid)
    pairs = backtest.replay(events, {"summary": {"every": 4}, "max_state_tokens": 8000}, fake_llm)
    assert pairs[0][1]["summary"] is None or pairs[0][1]["summary"]["goal"] == "g"
    assert pairs[-1][1]["summary"]["goal"] == "g"
