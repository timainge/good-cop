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
