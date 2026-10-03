"""Adapter logic for evals/benchmarks (no datasets or model calls needed)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("bench", Path(__file__).parent.parent / "evals" / "benchmarks" / "bench.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def test_rjudge_actions_become_tool_calls():
    a = bench.rjudge_action
    assert a("bash\n\n```bash\nrm -rf /root\n```") == {"tool": "Bash", "input": {"command": "rm -rf /root"}}
    assert a('TerminalExecute: {"command": "cat event-info.txt"}') == {"tool": "Bash", "input": {"command": "cat event-info.txt"}}
    assert a("GmailReadEmail{'email_id': 'email001'}") == {"tool": "mcp__rjudge__GmailReadEmail", "input": {"email_id": "email001"}}
    assert a('BankManagerPayBill\nAction Input: {"payee_id": "P-1"}') == {"tool": "mcp__rjudge__BankManagerPayBill", "input": {"payee_id": "P-1"}}
    py = a('"command": {"name": "execute_python_code", "args": {"code": "import os; os.remove(\'x\')"}}')
    assert py["tool"] == "Bash" and "os.remove" in py["input"]["command"]
    assert a("Final Answer: done") is None and a("I'm sorry, I can't do that.") is None
    assert a("click <Goodnotes><download>")["tool"] == "mcp__rjudge__ui"


def test_session_events_are_replayable():
    from good_cop import backtest, config
    evs = bench.session([{"prompt": "delete /root"}, {"tool": "Bash", "input": {"command": "rm -rf /root"}, "result": "ok"}])
    pairs = backtest.replay(evs, config.load_config())
    assert len(pairs) == 1 and pairs[0][1]["call"]["input"]["command"] == "rm -rf /root"
    assert any(r.get("prompt") == "delete /root" for r in pairs[0][1]["recent"])
