"""Replay recorded sessions through rules + judge and report. See plan.md §7."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from good_cop import config, context, ledger as ledger_mod, providers, rules, store, summary

LABELS = "labels.jsonl"


def replay(events: list[dict], cfg: dict, summariser=None) -> list[tuple[dict, dict]]:
    """Rebuild the ledger event by event; return (pre_tool event, state) pairs.

    Uses only what was known before each call. With a summariser, the summary is regenerated
    incrementally every `summary.every` events; otherwise summary is null.
    """
    ledger, summ, out = ledger_mod.empty(), None, []
    every = cfg["summary"].get("every", 8)
    for i, e in enumerate(events):
        if e["type"] == "pre_tool":
            recent = events[max(0, i - context.RECENT):i]
            out.append((e, context.build_state(e, ledger, summ, recent, cfg.get("max_state_tokens", 8000))))
        ledger = ledger_mod.fold(ledger, e)
        done = (summ or {}).get("last_event_seq", 0)
        if summariser and e["seq"] - done >= every:
            new = [x for x in events[: i + 1] if x["seq"] > done][-summary.CHUNK:]
            try:
                summ = summary.update(summariser, summ, new, ledger, cfg["summary"].get("timeout", 120))
            except Exception as ex:
                store.log_error(f"backtest summary: {ex}")
    return out


def load_labels() -> dict[tuple[str, int, str], bool]:
    labels = {}
    for r in store.read_jsonl(store.ROOT / LABELS):
        labels[(r["session"], r["seq"], r["rule_id"])] = r["value"]
    return labels


def label(session_id: str, seq: int, rule_id: str, value: bool) -> int:
    sid = store.resolve_session(session_id) or session_id
    store.append_jsonl(store.ROOT / LABELS, {"session": sid, "seq": seq, "rule_id": rule_id,
                                            "value": value, "ts": store.now()})
    return 0


def pct(values, q):
    values = sorted(v for v in values if v is not None)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def run(sessions: list[str], config_paths: list[str | None], rules_path: str | None = None,
        with_summary: bool = False, limit: int | None = None, workers: int = 4) -> dict:
    """Evaluate every recorded PreToolUse under each config. Returns {"items", "runs", "rules"}."""
    rules_cfg = config.load_rules(rules_path)
    cfgs = [config.load_config(p) for p in config_paths]
    summariser = providers.make_llm(cfgs[0]["summary"], cfgs[0].get("redact")) if with_summary else None

    items = []  # (session, event, state)
    for sid in sessions:
        pairs = replay(store.read_events(sid), cfgs[0], summariser)
        pairs = [(e, s) for e, s in pairs if any(rules.applies(r, e.get("tool")) for r in rules_cfg["rules"])]
        items += [(sid, e, s) for e, s in pairs[:limit]]

    runs = []
    for path, cfg in zip(config_paths, cfgs):
        jcfg = cfg["judge"]
        llm = providers.make_llm({**jcfg, "retries": jcfg.get("backtest_retries", 3)}, cfg.get("redact", "auto"))
        timeout = jcfg.get("backtest_timeout", 60)
        t0 = time.monotonic()
        with ThreadPoolExecutor(workers) as ex:
            decisions = list(ex.map(lambda it: rules.evaluate(rules_cfg, it[2], llm, timeout), items))
        runs.append({"config": path or "default", "provider": llm.name, "decisions": decisions,
                     "wall_s": round(time.monotonic() - t0, 1)})
    return {"items": items, "runs": runs, "rules": rules_cfg}


def report(result: dict) -> str:
    items, runs = result["items"], result["runs"]
    labels = load_labels()
    recorded = {}
    for sid in {it[0] for it in items}:
        for d in store.read_jsonl(store.session_dir(sid) / "decisions.jsonl"):
            recorded[(sid, d["seq"])] = d

    lines = [f"{len(items)} tool calls from {len({it[0] for it in items})} session(s)", ""]
    lines.append(f"{'config':<28}{'provider':<42}{'calls':>6}{'errors':>8}{'p50 ms':>9}{'p95 ms':>9}{'wall s':>8}")
    for r in runs:
        lat = [d["latency_ms"] for d in r["decisions"]]
        errs = sum(1 for d in r["decisions"] if d["error"])
        lines.append(f"{Path(r['config']).name:<28}{r['provider']:<42}{sum(1 for x in lat if x is not None):>6}"
                     f"{errs:>8}{str(pct(lat, .5)):>9}{str(pct(lat, .95)):>9}{r['wall_s']:>8}")

    lines += ["", "per rule: trips / evaluated; label accuracy (precision, recall) over labelled calls"]
    for rule in result["rules"]["rules"]:
        rid = rule["id"]
        lines.append(f"\n  {rid}  [{'pattern' if rule.get('pattern') else 'model'}]")
        tripsets = []
        for r in runs:
            ev, trips, tp, fp, fn, tn = 0, set(), 0, 0, 0, 0
            for (sid, e, _), d in zip(items, r["decisions"]):
                res = d["results"].get(rid)
                if not res:
                    continue
                ev += 1
                hit = bool(res.get("tripped"))
                if hit:
                    trips.add((sid, e["seq"]))
                truth = labels.get((sid, e["seq"], rid))
                if truth is not None:
                    tp += hit and truth
                    fp += hit and not truth
                    fn += (not hit) and truth
                    tn += (not hit) and (not truth)
            tripsets.append((trips, ev))
            n = tp + fp + fn + tn
            lab = (f"acc {(tp + tn) / n:.2f} (P {tp / (tp + fp) if tp + fp else 0:.2f}, "
                   f"R {tp / (tp + fn) if tp + fn else 0:.2f}) n={n}") if n else "no labels"
            lines.append(f"    {Path(r['config']).name:<26}{len(trips):>5} / {ev:<6}{lab}")
        if len(runs) > 1:
            a, b = tripsets[0][0], tripsets[1][0]
            ev = tripsets[0][1]
            agree = ev - len(a ^ b)
            lines.append(f"    agreement {runs[0]['provider']} vs {runs[1]['provider']}: {agree}/{ev}")
        rec = [(k, v) for k, v in recorded.items() if rid in v["results"]]
        if rec and len(runs) == 1:
            trips = tripsets[0][0]
            keys = {(it[0], it[1]["seq"]) for it in items}
            both = [(k, v) for k, v in rec if k in keys]
            agree = sum(1 for k, v in both if bool(v["results"][rid].get("tripped")) == (k in trips))
            lines.append(f"    agreement with recorded live decisions: {agree}/{len(both)}")
    return "\n".join(lines)


def save(result: dict) -> Path:
    out = store.ROOT / "backtests" / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for r in result["runs"]:
            for (sid, e, _), d in zip(result["items"], r["decisions"]):
                f.write(json.dumps({"config": r["config"], "provider": r["provider"], "session": sid,
                                    "seq": e["seq"], "tool": e.get("tool"), **d}, default=str) + "\n")
    return out


def main(args) -> int:
    if args.all:
        sessions = store.list_sessions()
    else:
        sessions = [store.resolve_session(s) for s in (args.sessions or [None])]
        missing = [s for s, r in zip(args.sessions or ["latest"], sessions) if not r]
        if missing:
            print(f"no session matching {missing}")
            return 1
    if not sessions:
        print("no sessions to backtest")
        return 1
    result = run(sessions, args.config or [None], args.rules, args.with_summary, args.limit, args.workers)
    print(report(result))
    print(f"\nresults: {save(result)}")
    return 0
