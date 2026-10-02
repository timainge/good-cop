"""`good-cop review`: label tool calls in value order with a plain terminal prompt. See plan.md R1.

Queue, per (session, seq, rule) not yet labelled:
  1. calls where judges disagreed (with --from-backtest and two or more configs);
  2. tripped calls;
  3. near-misses: p within ±NEAR of the rule's threshold, most borderline first;
  4. a small random sample of clear negatives, so recall can be estimated.

Probabilities come from a session's live decisions.jsonl, or from a saved backtest run.
"""

import getpass
import json
import random
import time
from pathlib import Path

from good_cop import backtest, config, context, rules as rules_mod, store

NEAR = 0.2
KEYS = "[y]es [n]o [u]nsure [s]kip [o]pen [q]uit"


def _since_seconds(text: str) -> float:
    n, unit = float(text[:-1]), text[-1]
    return n * {"m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]


def select_sessions(sessions: list[str] | None, since: str | None) -> list[str]:
    if sessions:
        return [s for s in (store.resolve_session(x) for x in sessions) if s]
    all_ = store.list_sessions()
    if not since:
        return all_
    cutoff = time.time() - _since_seconds(since)
    return [s for s in all_ if (store.session_dir(s) / "events.jsonl").stat().st_mtime >= cutoff]


def backtest_path(run: str) -> Path:
    """A run id (20260928-082225), 'latest', or a path to its .jsonl / .summary.json."""
    p = Path(run)
    if p.exists():
        return p.with_name(p.name.replace(".summary.json", ".jsonl"))
    base = store.ROOT / "backtests"
    if run == "latest":
        return sorted(base.glob("*.jsonl"))[-1]
    return base / f"{run}.jsonl"


def live_records(sessions: list[str]) -> list[dict]:
    """Recorded live decisions as backtest-style records (config 'live')."""
    out = []
    for sid in sessions:
        for d in store.read_jsonl(store.session_dir(sid) / "decisions.jsonl"):
            out.append({**d, "config": "live", "provider": d.get("provider") or "live", "session": sid})
    return out


def judge_name(rec: dict, res: dict) -> str:
    return rec["provider"] if res.get("source") in ("model", "escalated") else res.get("source", "?")


def threshold_for(rule: dict, source: str, rules_cfg: dict, judge_threshold) -> float:
    return rules_mod.threshold(rule, source, rules_cfg["defaults"], judge_threshold if source == "model" else None)


def build_queue(recs: list[dict], rules_cfg: dict, done: set, rule_filter: str | None = None,
                negatives: int = 10, judge_threshold=None, seed: int = 0) -> list[dict]:
    """Ordered review items: {"session", "seq", "rule", "kind", "answers": {judge: (p, tripped)}}."""
    by_rule = {r["id"]: r for r in rules_cfg["rules"]}
    items: dict[tuple, dict] = {}
    for rec in recs:
        for rid, res in (rec.get("results") or {}).items():
            if rid not in by_rule or (rule_filter and rid != rule_filter) or res.get("p") is None:
                continue
            key = (rec["session"], rec["seq"], rid)
            if key in done:
                continue
            it = items.setdefault(key, {"session": key[0], "seq": key[1], "rule": rid, "answers": {}, "margin": 1.0})
            it["answers"][judge_name(rec, res)] = (res["p"], bool(res.get("tripped")))
            t = threshold_for(by_rule[rid], res.get("source", "model"), rules_cfg, judge_threshold)
            it["margin"] = min(it["margin"], abs(res["p"] - t))
    groups = {"disagree": [], "tripped": [], "near": [], "negative": []}
    for it in items.values():
        trips = {tripped for _, tripped in it["answers"].values()}
        if len(trips) > 1:
            it["kind"] = "disagree"
        elif True in trips:
            it["kind"] = "tripped"
        elif it["margin"] <= NEAR:
            it["kind"] = "near"
        else:
            it["kind"] = "negative"
        groups[it["kind"]].append(it)
    order = lambda it: (it["session"], it["seq"], it["rule"])
    groups["near"].sort(key=lambda it: (it["margin"], *order(it)))
    neg = sorted(groups["negative"], key=order)
    groups["negative"] = random.Random(seed).sample(neg, min(negatives, len(neg)))
    return [it for k in ("disagree", "tripped") for it in sorted(groups[k], key=order)] + groups["near"] + groups["negative"]


def _event(session: str, seq: int, cache: dict) -> dict:
    if session not in cache:
        cache[session] = {e["seq"]: e for e in store.read_events(session)}
    return cache[session].get(seq) or {}


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def card(it: dict, event: dict, rule: dict, pos: str) -> str:
    inp = event.get("input") or {}
    cmd = inp.get("command") if isinstance(inp.get("command"), str) else json.dumps(inp, default=str)
    lines = [f"\n{pos} {it['kind']}  {it['session'][:8]} #{it['seq']}  rule {it['rule']}",
             f"  {event.get('tool') or '?':<6} {_clip(cmd, 400)}",
             f"  cwd    {event.get('cwd')}" + ("   (subagent)" if event.get("agent_id") else "")]
    script = (event.get("resolved") or {}).get("script")
    if script:
        seen = " (written this session)" if script.get("written_this_session") else ""
        lines.append(f"  script {script['path']}{seen}")
        lines += [f"    | {l}" for l in (script.get("head") or "").splitlines()[:6]]
    for w in context.writes(event) if event else []:
        lines.append(f"  writes {w['path']}" + ("  (outside cwd)" if w["outside_cwd"] else ""))
    q = rule.get("question") or (f"pattern {rule['pattern']!r}" if rule.get("pattern") else f"fact {rule.get('fact')}")
    lines.append(f"  Q      {_clip(q, 300)}")
    for k, label in (("true", "yes"), ("false", "no")):
        if k in (rule.get("criteria") or {}):
            lines.append(f"    {label}: {_clip(rule['criteria'][k], 200)}")
    lines.append("  p      " + "   ".join(f"{j} {p:.2f}{'!' if t else ''}" for j, (p, t) in it["answers"].items()))
    return "\n".join(lines)


def full_state(session: str, seq: int) -> dict | None:
    """The decision state this call was judged on (replayed from events, summary off)."""
    cfg = config.load_config()
    for e, state in backtest.replay(store.read_events(session), cfg):
        if e["seq"] == seq:
            return state
    return None


def loop(queue: list[dict], rules_cfg: dict, labeller: str, ask=input, out=print) -> list[dict]:
    """Prompt for each item; append labels as they're given. Returns the labels written."""
    by_rule = {r["id"]: r for r in rules_cfg["rules"]}
    cache, written = {}, []
    for i, it in enumerate(queue, 1):
        event = _event(it["session"], it["seq"], cache)
        out(card(it, event, by_rule[it["rule"]], f"[{i}/{len(queue)}]"))
        while True:
            try:
                key = ask(f"  {KEYS} > ").strip().lower()[:1]
            except EOFError:
                key = "q"
            if key == "o":
                out(json.dumps({"event": event, "state": full_state(it["session"], it["seq"])}, indent=1, default=str))
                continue
            if key in ("y", "n", "u", "s", "q"):
                break
            out(f"  ? {KEYS}")
        if key == "q":
            break
        if key == "s":
            continue
        value = {"y": True, "n": False, "u": None}[key]
        backtest.label(it["session"], it["seq"], it["rule"], value, source="review", labeller=labeller)
        written.append({**it, "value": value})
    return written


def summarise(written: list[dict], recs: list[dict], rules_cfg: dict) -> str:
    """Counts, agreement with each judge on this review's y/n answers, suggested thresholds."""
    decided = [w for w in written if w["value"] is not None]
    lines = [f"\nlabelled {len(written)} ({sum(1 for w in decided if w['value'])} yes, "
             f"{sum(1 for w in decided if not w['value'])} no, {len(written) - len(decided)} unsure)"]
    agree: dict[str, list[int]] = {}
    for w in decided:
        for j, (_, tripped) in w["answers"].items():
            a = agree.setdefault(j, [0, 0])
            a[0] += tripped == w["value"]
            a[1] += 1
    for j, (ok, n) in agree.items():
        lines.append(f"  agreement with {j}: {ok}/{n}")
    labels = backtest.load_labels()
    model_rules = [r["id"] for r in rules_cfg["rules"] if rules_mod.kind(r) == "model"]
    shown = False
    for cfg_name in dict.fromkeys(r["config"] for r in recs):
        rs = [r for r in recs if r["config"] == cfg_name]
        for rid in model_rules:
            best = backtest.suggest_threshold(rs, rid, labels)
            if best and best["f1"] is not None:
                if not shown:
                    lines.append("  suggested thresholds (best F1 over all labels):")
                    shown = True
                lines.append(f"    {rid:<24} {rs[0]['provider']:<36} t={best['threshold']:.2f}  F1 {best['f1']:.2f}  "
                             f"(P {best['precision']}, R {best['recall']}, n={best['n']}, {best['tp'] + best['fn']}+)")
    return "\n".join(lines)


def main(args) -> int:
    if args.from_backtest:
        path = backtest_path(args.from_backtest)
        if not path.exists():
            print(f"no backtest run {args.from_backtest!r} ({path})")
            return 1
        recs = store.read_jsonl(path)
        meta = (store.read_json(path.with_name(path.name.replace(".jsonl", ".summary.json"))) or {}).get("meta") or {}
        rules_cfg = config.load_rules(args.rules)
        if meta.get("rules") and not args.rules:
            rules_cfg = {**rules_cfg, "rules": meta["rules"]}
        if args.sessions or args.since:
            keep = set(select_sessions(args.sessions, args.since))
            recs = [r for r in recs if r["session"] in keep]
    else:
        sessions = select_sessions(args.sessions, args.since or (None if args.sessions else "7d"))
        recs, rules_cfg = live_records(sessions), config.load_rules(args.rules)
    if not recs:
        print("nothing to review: no recorded decisions (try --from-backtest RUN for imported sessions)")
        return 1
    done = set(backtest.load_labels(include_unsure=True))
    jt = config.load_config()["judge"].get("threshold")
    queue = build_queue(recs, rules_cfg, done, args.rule, args.negatives, jt, args.seed)
    if not queue:
        print("nothing left to review: every candidate call is already labelled")
        return 0
    kinds = {k: sum(1 for it in queue if it["kind"] == k) for k in ("disagree", "tripped", "near", "negative")}
    print(f"{len(queue)} to review: " + ", ".join(f"{n} {k}" for k, n in kinds.items() if n))
    written = loop(queue, rules_cfg, args.labeller or getpass.getuser())
    print(summarise(written, recs, rules_cfg))
    return 0
