import json
from pathlib import Path

import pytest

from good_cop import store

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def home(monkeypatch, tmp_path):
    """Point good-cop at an empty temp home."""
    monkeypatch.setattr(store, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def payloads():
    return [json.loads(l) for l in (FIXTURES / "hook_payloads.jsonl").read_text().splitlines() if l.strip()]


class FakeLLM:
    """Answers every question with a fixed probability, or by keyword in the question text."""

    name = "fake:1"

    def __init__(self, p=0.0, fail=False, by_keyword=None):
        self.p, self.fail, self.by_keyword, self.calls = p, fail, by_keyword or {}, 0

    def complete(self, system, user, *, timeout):
        self.calls += 1
        if self.fail:
            raise TimeoutError("boom")
        if '"goal"' in system:  # summariser prompt
            return json.dumps({"goal": "g", "current_task": "t", "next_intent": "n", "notable": ["x"]})
        ids = json.loads(user.rsplit("exactly this shape: ", 1)[1])
        call = user.split("QUESTIONS", 1)[0]
        return json.dumps({rid: next((p for k, p in self.by_keyword.items() if k in call), self.p) for rid in ids})


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr("good_cop.providers.make_llm", lambda cfg, redact="auto": llm)
    return llm


def write_rules(home, text):
    (home / "rules.yaml").write_text(text)
