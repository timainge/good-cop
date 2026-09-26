"""Print ledger, summary and recent decisions for a session. See plan.md §7."""

import json

from good_cop import store


def pct(values: list[float], q: float):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))]


def fmt_decision(d: dict) -> str:
    ps = " ".join(f"{rid}={r['p']:.2f}{'!' if r.get('tripped') else ''}"
                  for rid, r in d["results"].items() if r.get("p") is not None)
    err = f"  ERROR {d['error'][:80]}" if d.get("error") else ""
    return f"  #{d['seq']:<5} {d.get('tool') or '':<14} {d['action']:<5} {d.get('hook_ms', '-')}ms  {ps}{err}"


def main(session: str | None, n: int) -> int:
    sid = store.resolve_session(session)
    if not sid:
        print("no sessions recorded" if not session else f"no session matching {session!r}")
        return 1
    d = store.session_dir(sid)
    events = store.read_events(sid)
    decisions = store.read_jsonl(d / "decisions.jsonl")
    print(f"session {sid}  ({len(events)} events, {len(decisions)} decisions)")
    print("\nLEDGER")
    print(json.dumps(store.read_json(d / "ledger.json"), indent=2))
    summary = store.read_json(d / "summary.json")
    if summary:
        print("\nSUMMARY")
        print(json.dumps(summary, indent=2))
    if decisions:
        hook = [x["hook_ms"] for x in decisions if x.get("hook_ms") is not None]
        judge = [x["latency_ms"] for x in decisions if x.get("latency_ms") is not None]
        errors = sum(1 for x in decisions if x.get("error"))
        print(f"\nDECISIONS (last {n}; hook p50={pct(hook, .5)}ms p95={pct(hook, .95)}ms, "
              f"judge p50={pct(judge, .5)}ms p95={pct(judge, .95)}ms, errors={errors})")
        for x in decisions[-n:]:
            print(fmt_decision(x))
    return 0
