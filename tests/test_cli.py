import io
import json

from good_cop import cli


def test_hook_fails_open(monkeypatch, tmp_path):
    monkeypatch.setattr("good_cop.store.ROOT", tmp_path)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert cli.main(["hook"]) == 0
    assert (tmp_path / "errors.log").exists()


def test_hook_accepts_payload(monkeypatch, tmp_path):
    monkeypatch.setattr("good_cop.store.ROOT", tmp_path)
    payload = {"hook_event_name": "SessionStart", "session_id": "s1", "cwd": str(tmp_path)}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    assert cli.main(["hook"]) == 0
