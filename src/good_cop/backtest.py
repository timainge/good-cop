"""Replay recorded sessions through rules + judge and report. See plan.md §7."""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from good_cop import config, context, handlers, ledger as ledger_mod, providers, rules, store, summary

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


def load_labels(include_unsure: bool = False) -> dict[tuple[str, int, str], bool | None]:
    """Latest label per (session, seq, rule). Unsure answers (value null) are excluded from scoring."""
    labels = {}
    for r in store.read_jsonl(store.ROOT / LABELS):
        labels[(r["session"], r["seq"], r["rule_id"])] = r["value"]
    return labels if include_unsure else {k: v for k, v in labels.items() if v is not None}


def label(session_id: str, seq: int, rule_id: str, value: bool | None, **extra) -> int:
    sid = store.resolve_session(session_id) or session_id
    store.append_jsonl(store.ROOT / LABELS, {"session": sid, "seq": seq, "rule_id": rule_id,
                                            "value": value, "ts": store.now(), **extra})
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
        opts = providers.judge_options(cfg, backtest=True)
        t0 = time.monotonic()
        with ThreadPoolExecutor(workers) as ex:
            decisions = list(ex.map(lambda it: rules.evaluate(rules_cfg, it[2], **opts), items))
        for d in decisions:  # dry run: which handlers would fire; nothing is executed
            d["handlers"] = handlers.plan(rules_cfg, d)
        name = opts["llm"].name + (f" -> {opts['escalate']['llm'].name}" if "escalate" in opts else "")
        runs.append({"config": path or "default", "provider": name, "judge": {**jcfg, "escalate": cfg.get("escalate")},
                     "decisions": decisions, "wall_s": round(time.monotonic() - t0, 1)})
    return {"items": items, "runs": runs, "rules": rules_cfg}


def records(result: dict) -> list[dict]:
    """One flat record per (config, tool call): the unit saved to disk and scored by metrics()."""
    return [{"config": r["config"], "provider": r["provider"], "session": sid, "seq": e["seq"],
             "tool": e.get("tool"), **d}
            for r in result["runs"] for (sid, e, _), d in zip(result["items"], r["decisions"])]


def _score(tp, fp, fn, tn) -> dict:
    n = tp + fp + fn + tn
    return {"n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
            "acc": round((tp + tn) / n, 3) if n else None,
            "precision": round(tp / (tp + fp), 3) if tp + fp else None,
            "recall": round(tp / (tp + fn), 3) if tp + fn else None}


THRESHOLDS = tuple(round(0.05 * i, 2) for i in range(1, 20))  # 0.05 .. 0.95


def score_at(recs: list[dict], rule_id: str, labels: dict, t: float) -> dict:
    """Re-score saved probabilities at threshold t against labels (no judge calls)."""
    tp = fp = fn = tn = 0
    for r in recs:
        res, truth = r["results"].get(rule_id), labels.get((r["session"], r["seq"], rule_id))
        if not res or res["p"] is None or truth is None:
            continue
        hit = res["p"] >= t
        tp += hit and truth
        fp += hit and not truth
        fn += (not hit) and truth
        tn += (not hit) and (not truth)
    out = _score(tp, fp, fn, tn)
    out["f1"] = round(2 * tp / (2 * tp + fp + fn), 3) if tp + fp + fn else None
    return out


def suggest_threshold(recs: list[dict], rule_id: str, labels: dict, thresholds=THRESHOLDS) -> dict | None:
    """The threshold with the best F1 (ties: the higher one, fewer interruptions). None without positives."""
    best = None
    for t in thresholds:
        s = score_at(recs, rule_id, labels, t)
        if not s["tp"] + s["fn"]:
            return None
        if best is None or (s["f1"] or 0) >= (best["f1"] or 0):
            best = {"threshold": t, **s}
    return best


def metrics(recs: list[dict], rule_list: list[dict], labels: dict, wall: dict | None = None) -> dict:
    """Per-config latency/errors and per-rule trips, label scores and cross-config agreement.

    Works from saved records alone, so old runs can be re-scored against the current labels."""
    configs = list(dict.fromkeys(r["config"] for r in recs))
    by_cfg = {c: [r for r in recs if r["config"] == c] for c in configs}
    out = {"calls": len({(r["session"], r["seq"]) for r in recs}),
           "sessions": sorted({r["session"] for r in recs}), "configs": [], "rules": {}}
    for c, rs in by_cfg.items():
        lat = [r["latency_ms"] for r in rs]
        fired = {}
        for r in rs:
            for h in r.get("handlers") or []:
                fired[h] = fired.get(h, 0) + 1
        out["configs"].append({"config": c, "provider": rs[0]["provider"], "calls": len(rs), "handlers": fired,
                               "model_calls": sum(1 for x in lat if x is not None),
                               "errors": sum(1 for r in rs if r.get("error")),
                               "p50_ms": pct(lat, .5), "p95_ms": pct(lat, .95),
                               "wall_s": (wall or {}).get(c)})
    for rule in rule_list:
        rid = rule["id"]
        entry = {"kind": rules.kind(rule), "by_config": {}}
        trips = {}
        for c, rs in by_cfg.items():
            ev, hits, tp, fp, fn, tn = 0, set(), 0, 0, 0, 0
            for r in rs:
                res = r["results"].get(rid)
                if not res or res["p"] is None:  # errored judge calls have no answer: not scored
                    continue
                ev += 1
                hit = bool(res.get("tripped"))
                if hit:
                    hits.add((r["session"], r["seq"]))
                truth = labels.get((r["session"], r["seq"], rid))
                if truth is not None:
                    tp += hit and truth
                    fp += hit and not truth
                    fn += (not hit) and truth
                    tn += (not hit) and (not truth)
            trips[c] = (hits, ev)
            entry["by_config"][c] = {"evaluated": ev, "trips": len(hits), **_score(tp, fp, fn, tn)}
        if len(configs) > 1:
            (a, ev), (b, _) = trips[configs[0]], trips[configs[1]]
            entry["agreement"] = {"a": configs[0], "b": configs[1], "agree": ev - len(a ^ b), "of": ev}
        out["rules"][rid] = entry
    return out


def render(m: dict) -> str:
    lines = [f"{m['calls']} tool calls from {len(m['sessions'])} session(s)", ""]
    lines.append(f"{'config':<28}{'provider':<42}{'calls':>6}{'errors':>8}{'p50 ms':>9}{'p95 ms':>9}{'wall s':>8}")
    for c in m["configs"]:
        lines.append(f"{Path(c['config']).name:<28}{c['provider']:<42}{c['model_calls']:>6}{c['errors']:>8}"
                     f"{str(c['p50_ms']):>9}{str(c['p95_ms']):>9}{str(c['wall_s'] or '-'):>8}")
    for c in m["configs"]:
        if c.get("handlers"):
            lines.append(f"  handlers that would fire ({Path(c['config']).name}): "
                         + ", ".join(f"{k} x{v}" for k, v in c["handlers"].items()))
    lines += ["", "per rule: trips / evaluated; label accuracy (precision, recall) over labelled calls"]
    fmt = lambda v: "-" if v is None else f"{v:.2f}"
    for rid, entry in m["rules"].items():
        lines.append(f"\n  {rid}  [{entry['kind']}]")
        for c, x in entry["by_config"].items():
            lab = (f"acc {fmt(x['acc'])} (P {fmt(x['precision'])}, R {fmt(x['recall'])}) n={x['n']}"
                   if x["n"] else "no labels")
            lines.append(f"    {Path(c).name:<26}{x['trips']:>5} / {x['evaluated']:<6}{lab}")
        if "agreement" in entry:
            a = entry["agreement"]
            lines.append(f"    agreement {Path(a['a']).name} vs {Path(a['b']).name}: {a['agree']}/{a['of']}")
    return "\n".join(lines)


def _git_sha() -> str | None:
    import subprocess
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent,
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def save(result: dict, meta: dict) -> Path:
    """Write <ts>.jsonl (every decision) and <ts>.summary.json (run metadata + metrics)."""
    base = store.ROOT / "backtests" / time.strftime("%Y%m%d-%H%M%S")
    base.parent.mkdir(parents=True, exist_ok=True)
    recs = records(result)
    with open(base.with_suffix(".jsonl"), "w") as f:
        for r in recs:
            f.write(json.dumps(r, default=str) + "\n")
    wall = {r["config"]: r["wall_s"] for r in result["runs"]}
    summary_doc = {"meta": meta, "metrics": metrics(recs, result["rules"]["rules"], load_labels(), wall)}
    store.write_json_atomic(base.with_suffix(".summary.json"), summary_doc)
    return base.with_suffix(".summary.json")


def run_meta(args, result: dict) -> dict:
    import hashlib, sys
    rules_file = Path(args.rules) if args.rules else None
    return {
        "ts": store.now(), "note": args.note, "git_sha": _git_sha(), "argv": sys.argv[1:],
        "sessions": sorted({it[0] for it in result["items"]}), "limit": args.limit, "workers": args.workers,
        "with_summary": args.with_summary,
        "rules_path": str(rules_file) if rules_file else "default",
        "rules_sha256": hashlib.sha256(rules_file.read_bytes()).hexdigest()[:16] if rules_file else None,
        "rules": result["rules"]["rules"],
        "configs": [{"path": r["config"], "provider": r["provider"],
                     "judge": {k: v for k, v in r["judge"].items() if "key" not in k}} for r in result["runs"]],
        "labels": sum(1 for _ in store.read_jsonl(store.ROOT / LABELS)),
    }


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
    path = save(result, run_meta(args, result))
    print(render(store.read_json(path)["metrics"]))
    print(f"\nsummary: {path}\ndecisions: {path.with_name(path.name.replace('.summary.json', '.jsonl'))}")
    return 0


def evals() -> int:
    """One line per saved backtest run: when, note, providers, calls, label accuracy per model rule."""
    for path in sorted((store.ROOT / "backtests").glob("*.summary.json")):
        doc = store.read_json(path)
        meta, m = doc["meta"], doc["metrics"]
        print(f"\n{path.name.removesuffix('.summary.json')}  {meta.get('note') or ''}  "
              f"[{m['calls']} calls, {len(m['sessions'])} sessions, rules={Path(meta.get('rules_path') or '?').name}]")
        for c in m["configs"]:
            accs = " ".join(f"{rid}={x['by_config'][c['config']]['acc']:.2f}" for rid, x in m["rules"].items()
                            if x["kind"] == "model" and x["by_config"].get(c["config"], {}).get("acc") is not None)
            print(f"  {c['provider']:<40} p50 {c['p50_ms']}ms  errors {c['errors']:<4} {accs}")
    return 0
