import io
import json
from types import SimpleNamespace

from conftest import write_rules
from good_cop import backtest, config, hook, review, store

RULES = """
rules:
  - {id: q, when: {tools: [Bash]}, question: 'Does this run a script?',
     criteria: {true: runs a local script, false: anything else}}
  - {id: echo, when: {tools: [Bash]}, pattern: 'echo'}
"""


def args(**kw):
    return SimpleNamespace(**{"sessions": [], "since": None, "rule": None, "from_backtest": None, "rules": None,
                              "negatives": 10, "seed": 0, "labeller": "tester", **kw})


def record_live(home, payloads, fake_llm):
    write_rules(home, RULES)
    fake_llm.by_keyword = {'"command": "chmod +x deploy.sh': 0.9, '"command": "ls -la"': 0.5}
    cfg = config.load_config()
    for p in payloads:
        hook.handle(p, cfg)
    return payloads[0]["session_id"]


def test_queue_order(home, payloads, fake_llm):
    sid = record_live(home, payloads, fake_llm)
    recs = review.live_records([sid])
    q = review.build_queue(recs, config.load_rules(), set())
    kinds = [it["kind"] for it in q]
    assert kinds == ["tripped", "tripped", "near"] + ["negative"] * 3
    assert {(it["rule"], it["kind"]) for it in q[:3]} == {("q", "tripped"), ("echo", "tripped"), ("q", "near")}
    assert len(review.build_queue(recs, config.load_rules(), set(), negatives=1)) == 4
    assert all(it["rule"] == "q" for it in review.build_queue(recs, config.load_rules(), set(), rule_filter="q"))


def test_loop_with_scripted_stdin(home, payloads, fake_llm, monkeypatch, capsys):
    sid = record_live(home, payloads, fake_llm)
    # y, then a bad key and n, then o (open) and u, then skip, then quit
    monkeypatch.setattr("sys.stdin", io.StringIO("y\nx\nn\no\nu\ns\nq\n"))
    assert review.main(args(sessions=[sid[:8]])) == 0
    out = capsys.readouterr().out
    assert "6 to review: 2 tripped, 1 near, 3 negative" in out
    assert "chmod +x deploy.sh" in out and "script /tmp/gc-work/deploy.sh (written this session)" in out
    assert "yes: runs a local script" in out and '"state"' in out
    assert "labelled 3 (1 yes, 1 no, 1 unsure)" in out and "agreement with fake:1" in out
    labels = store.read_jsonl(home / "labels.jsonl")
    assert [l["value"] for l in labels] == [True, False, None]
    assert all(l["source"] == "review" and l["labeller"] == "tester" for l in labels)
    assert len(backtest.load_labels()) == 2  # unsure is stored, not scored

    # never re-asked: the three labelled items are gone from the queue; EOF quits cleanly
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert review.main(args(sessions=[sid])) == 0
    assert "3 to review" in capsys.readouterr().out


def test_from_backtest_disagreements_first(home, payloads, fake_llm, capsys, monkeypatch):
    sid = record_live(home, payloads, fake_llm)
    recs = review.live_records([sid])
    other = [{**r, "config": "b.yaml", "provider": "fake:2",
              "results": {k: {**v, "tripped": not v["tripped"]} if k == "q" else v for k, v in r["results"].items()}}
             for r in recs]
    path = home / "backtests" / "20260101-000000.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(r) + "\n" for r in recs + other))
    q = review.build_queue(store.read_jsonl(path), config.load_rules(), set())
    assert [it["kind"] for it in q[:3]] == ["disagree"] * 3 and q[3]["kind"] == "tripped"
    assert set(q[0]["answers"]) == {"fake:1", "fake:2"}
    monkeypatch.setattr("sys.stdin", io.StringIO("y\nn\ny\n"))
    assert review.main(args(from_backtest="latest")) == 0
    out = capsys.readouterr().out
    assert "3 disagree" in out and "suggested thresholds" in out


def test_suggest_threshold():
    recs = [{"session": "s", "seq": i, "results": {"r": {"p": p}}} for i, p in enumerate([0.1, 0.4, 0.7, 0.95])]
    labels = {("s", 2, "r"): True, ("s", 3, "r"): True, ("s", 1, "r"): False, ("s", 0, "r"): False}
    best = backtest.suggest_threshold(recs, "r", labels)
    assert best["f1"] == 1.0 and 0.4 < best["threshold"] <= 0.7
    assert backtest.suggest_threshold(recs, "r", {("s", 0, "r"): False}) is None
