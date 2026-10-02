from conftest import FakeLLM
from good_cop import rules

STATE = {"call": {"tool": "Bash", "input": {"command": "rm -rf / "}}, "ledger": {}, "recent": []}


def cfg(*rs, enforce=False):
    return {"enforce": enforce, "defaults": {"threshold": 0.6, "action": "ask"}, "rules": list(rs)}


def test_pattern_rule_no_model_call():
    llm = FakeLLM()
    d = rules.evaluate(cfg({"id": "rm", "pattern": r"rm\s+-rf\s+/", "action": "deny"}), STATE, llm)
    assert d["results"]["rm"] == {"p": 1.0, "source": "pattern", "tripped": True}
    assert d["action"] == "deny" and d["enforced"] == "allow" and llm.calls == 0


def test_strictest_action_and_threshold():
    llm = FakeLLM(p=0.7)
    c = cfg({"id": "a", "question": "q1"}, {"id": "b", "question": "q2", "threshold": 0.8, "action": "deny"},
            {"id": "c", "question": "q3", "action": "log"}, enforce=True)
    d = rules.evaluate(c, STATE, llm)
    assert llm.calls == 1  # batched
    assert d["results"]["a"]["tripped"] and not d["results"]["b"]["tripped"]
    assert d["action"] == d["enforced"] == "ask"


def test_when_tools_glob():
    r = {"id": "x", "when": {"tools": ["Bash", "mcp__*"]}}
    assert rules.applies(r, "mcp__github__create_pr") and rules.applies(r, "Bash") and not rules.applies(r, "Read")
    assert rules.applies({"id": "y"}, "Read")


def test_model_error_allows():
    d = rules.evaluate(cfg({"id": "a", "question": "q", "action": "deny"}, enforce=True), STATE, FakeLLM(fail=True))
    assert d["action"] == "allow" and d["enforced"] == "allow" and "TimeoutError" in d["error"]
    assert d["results"]["a"]["p"] is None


def test_enforced_pattern_deny_skips_model():
    llm = FakeLLM(p=0.9)
    c = cfg({"id": "rm", "pattern": r"rm\s+-rf", "action": "deny"}, {"id": "q", "question": "q"}, enforce=True)
    d = rules.evaluate(c, STATE, llm)
    assert d["enforced"] == "deny" and llm.calls == 0 and "q" not in d["results"]
    d = rules.evaluate({**c, "enforce": False}, STATE, llm)  # log mode still collects everything
    assert llm.calls == 1 and d["results"]["q"]["tripped"]


WRITE_STATE = {"call": {"tool": "Bash", "input": {"command": "echo x > /etc/hosts"}},
               "resolved": {"writes": [{"path": "/w/a", "outside_cwd": False}, {"path": "/etc/hosts", "outside_cwd": True}]},
               "ledger": {"env": {"kube_context": "prod-eu"}}, "recent": []}


def test_fact_rules():
    c = cfg({"id": "outside", "fact": "resolved.writes[].outside_cwd", "action": "deny"},
            {"id": "prod", "fact": "ledger.env.kube_context", "matches": "^prod"},
            {"id": "dev", "fact": "ledger.env.kube_context", "equals": "dev"},
            {"id": "tmp", "fact": "resolved.writes[].path", "in": ["/tmp/x"]}, enforce=True)
    llm = FakeLLM()
    d = rules.evaluate(c, WRITE_STATE, llm)
    assert d["results"]["outside"] == {"p": 1.0, "source": "fact", "tripped": True}
    assert d["results"]["prod"]["tripped"] and not d["results"]["dev"]["tripped"] and not d["results"]["tmp"]["tripped"]
    assert d["enforced"] == "deny" and llm.calls == 0
    assert rules.lookup(WRITE_STATE, "resolved.writes[].path") == ["/w/a", "/etc/hosts"]
    assert rules.lookup(WRITE_STATE, "resolved.script.path") == []


def test_judge_threshold_precedence():
    c = cfg({"id": "a", "question": "q"}, {"id": "b", "question": "q", "threshold": 0.95})
    d = rules.evaluate(c, STATE, FakeLLM(p=0.9), judge_threshold=0.85)
    assert d["results"]["a"]["tripped"] and not d["results"]["b"]["tripped"]
    d = rules.evaluate(c, STATE, FakeLLM(p=0.8), judge_threshold=0.85)
    assert not d["results"]["a"]["tripped"]


def test_escalation_reasks_only_uncertain():
    first = FakeLLM(by_keyword={}, p=0.5)
    second = FakeLLM(p=0.95)
    second.name = "fake:big"
    c = cfg({"id": "a", "question": "q"}, {"id": "b", "question": "q2"})
    d = rules.evaluate(c, STATE, first, escalate={"llm": second, "band": [0.3, 0.85]})
    assert first.calls == 1 and second.calls == 1
    assert d["escalated"] == ["a", "b"] and d["results"]["a"] == {"p": 0.95, "source": "escalated", "p0": 0.5, "tripped": True}
    sure = FakeLLM(p=0.99)
    d = rules.evaluate(c, STATE, sure, escalate={"llm": second, "band": [0.3, 0.85]})
    assert "escalated" not in d and second.calls == 1  # confident answers are not re-asked


def named(p, name, threshold=None, fail=False):
    llm = FakeLLM(p=p, fail=fail)
    llm.name = name
    return {"llm": llm, "timeout": 1.0, "threshold": threshold}


def test_per_rule_cascade_batches_per_judge():
    fast, strong = named(0.5, "fake:fast", threshold=0.9), named(0.95, "fake:strong")
    default = FakeLLM(p=0.1)
    c = cfg({"id": "a", "question": "qa", "cascade": ["fast", "strong"]},
            {"id": "b", "question": "qb", "cascade": ["fast", "strong"], "band": [0.6, 0.9]},  # 0.5 is below b's band
            {"id": "c", "question": "qc", "cascade": ["strong"]},
            {"id": "d", "question": "qd"})                                                      # global judge
    d = rules.evaluate(c, STATE, default, judges={"fast": fast, "strong": strong})
    assert fast["llm"].calls == 1 and strong["llm"].calls == 1 and default.calls == 1  # one request per judge
    assert d["results"]["a"] == {"p": 0.95, "source": "escalated", "p0": 0.5, "judge": "strong", "tripped": True}
    assert d["results"]["b"] == {"p": 0.5, "source": "model", "judge": "fast", "tripped": False}  # fast's t=0.9
    assert d["results"]["c"]["judge"] == "strong" and d["results"]["d"] == {"p": 0.1, "source": "model", "tripped": False}
    assert set(d["judges"]) == {"default", "fast", "strong"} and sorted(d["judges"]["strong"]["rules"]) == ["a", "c"]
    assert d["escalation_ms"] is not None


def test_cascade_failure_keeps_earlier_answer_and_ask_when_unsure():
    fast, broken = named(0.6, "fake:fast"), named(0.0, "fake:broken", fail=True)
    c = cfg({"id": "a", "question": "qa", "cascade": ["fast", "broken"], "ask_when_unsure": True, "action": "deny",
             "threshold": 0.9}, enforce=True)
    d = rules.evaluate(c, STATE, None, judges={"fast": fast, "broken": broken})
    assert d["results"]["a"]["p"] == 0.6 and d["results"]["a"]["unsure"] and not d["results"]["a"]["tripped"]
    assert d["action"] == d["enforced"] == "ask"  # unsure asks, never denies
    assert "TimeoutError" in d["judges"]["broken"]["error"]


def test_unknown_cascade_judge_falls_back_to_default():
    default = FakeLLM(p=0.9)
    d = rules.evaluate(cfg({"id": "a", "question": "q", "cascade": ["nope"]}), STATE, default, judges={})
    assert default.calls == 1 and d["results"]["a"]["tripped"]


def test_judge_options_builds_named_judges(monkeypatch):
    from good_cop import providers
    monkeypatch.setattr(providers, "make_llm", lambda c, r="auto": FakeLLM())
    opts = providers.judge_options({"judge": {"provider": "x"}, "judges": {"fast": {"provider": "jev", "threshold": 0.9}}},
                                   backtest=True)
    assert opts["judges"]["fast"]["threshold"] == 0.9 and opts["judges"]["fast"]["timeout"] == 60
