from conftest import FIXTURES
from good_cop import ledger, store, transcripts

T = next((FIXTURES / "transcript").glob("*.jsonl"))


def test_convert_fixture():
    sid, events = transcripts.convert(T)
    types = [e["type"] for e in events]
    assert types[0] == "session_start" and types.count("pre_tool") == types.count("post_tool") == 7
    tools = [e["tool"] for e in events if e["type"] == "pre_tool"]
    assert tools == ["Write", "Bash", "Edit", "Read", "Bash", "Agent", "Bash"]
    sub = [e for e in events if e.get("agent_id")]
    assert sub and sub[0]["input"]["command"] == "echo from-subagent"
    run = next(e for e in events if e["type"] == "pre_tool" and "./deploy.sh" in e["input"].get("command", ""))
    assert run["resolved"]["script"]["written_this_session"]
    assert "staging" in run["resolved"]["script"]["head"]  # replayed Write content, not disk


def test_import(home):
    sid, n = transcripts.import_transcript(T)
    events = store.read_events(sid)
    assert len(events) == n
    assert store.read_json(store.session_dir(sid) / "ledger.json") == ledger.rebuild(events)
    assert transcripts.import_transcript(T) is None  # already imported
