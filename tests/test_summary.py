import pytest

from conftest import FakeLLM
from good_cop import config, store, summary


def test_validate():
    assert summary.validate({"goal": "g", "current_task": "t", "next_intent": "n", "notable": list("abcdefghijkl")})["notable"] == list("abcdefghij")
    with pytest.raises(ValueError):
        summary.validate({"goal": "g"})


def test_disabled_never_spawns(home):
    cfg = config.load_config()
    assert not summary.maybe_spawn("s", {"last_event_seq": 100}, cfg)


def test_spawn_when_behind(home, monkeypatch):
    spawned = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: spawned.append(a))
    cfg = config.load_config()
    cfg["summary"]["enabled"] = True
    assert not summary.maybe_spawn("s", {"last_event_seq": 3}, cfg)
    assert summary.maybe_spawn("s", {"last_event_seq": 9}, cfg) and len(spawned) == 1
    summary.lock_path("s").parent.mkdir(parents=True, exist_ok=True)
    summary.lock_path("s").touch()
    assert not summary.maybe_spawn("s", {"last_event_seq": 20}, cfg)  # worker already running


def test_worker_catches_up(home, fake_llm):
    for i in range(50):
        store.append_event("s", {"type": "post_tool", "tool": "Bash", "input": {"command": f"echo {i}"}})
    assert summary.worker("s") == 0
    s = store.read_json(summary.summary_path("s"))
    assert s["last_event_seq"] == 50 and s["goal"] == "g"
    assert fake_llm.calls == 2  # 40 + 10
    assert not summary.lock_path("s").exists()


def test_worker_respects_lock(home, fake_llm):
    store.append_event("s", {"type": "stop"})
    summary.lock_path("s").touch()
    assert summary.worker("s") == 0 and fake_llm.calls == 0
