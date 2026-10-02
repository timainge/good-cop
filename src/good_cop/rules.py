"""Rule selection, pattern/fact evaluation, judge cascade, threshold and action logic. See plan.md §5."""

import fnmatch
import hashlib
import json
import re
import time

from good_cop import judge as judge_mod

SEVERITY = {"allow": 0, "log": 1, "ask": 2, "deny": 3}
CODE_KINDS = ("pattern", "fact")


EQUIVALENT_TOOLS = {"apply_patch": ("Edit", "Write", "MultiEdit")}  # Codex file edits


def applies(rule: dict, tool: str, text: str | None = None) -> bool:
    """`when.tools` globs match the tool; `when.command` (regex) matches the command text, when given.
    Without text (pre-filtering) only tools are checked, so the answer is a superset."""
    when = rule.get("when") or {}
    tools = when.get("tools")
    names = (tool or "", *EQUIVALENT_TOOLS.get(tool, ()))
    if tools and not any(fnmatch.fnmatchcase(n, t) for n in names for t in tools):
        return False
    return text is None or not when.get("command") or re.search(when["command"], text) is not None


def kind(rule: dict) -> str:
    return next((k for k in CODE_KINDS if rule.get(k)), "model")


def pattern_text(call: dict) -> str:
    inp = call.get("input") or {}
    return inp.get("command") if isinstance(inp.get("command"), str) else json.dumps(inp)


def lookup(state, path: str) -> list:
    """Values at a dotted path; `[]` fans out over a list. `resolved.writes[].outside_cwd` -> [bool, ...]."""
    values = [state]
    for part in path.split("."):
        fan = part.endswith("[]")
        key = part[:-2] if fan else part
        nxt = []
        for v in values:
            v = v.get(key) if isinstance(v, dict) else None
            if fan:
                nxt += v if isinstance(v, list) else []
            elif v is not None:
                nxt.append(v)
        values = nxt
    return values


def fact_holds(rule: dict, state: dict) -> bool:
    """Any value at `fact` meets the condition: `equals`, `matches` (regex), `in`, `not_in`,
    `not_matches`, else truthy."""
    for v in lookup(state, rule["fact"]):
        if "equals" in rule:
            ok = v == rule["equals"]
        elif "matches" in rule:
            ok = isinstance(v, str) and re.search(rule["matches"], v) is not None
        elif "not_matches" in rule:
            ok = isinstance(v, str) and re.search(rule["not_matches"], v) is None
        elif "in" in rule:
            ok = v in rule["in"]
        elif "not_in" in rule:
            ok = v not in rule["not_in"]
        else:
            ok = bool(v)
        if ok:
            return True
    return False


def state_hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _ask(llm, state, questions, timeout):
    """One judge call -> (probs, error, latency_ms). Never raises."""
    t0 = time.monotonic()
    try:
        if llm is None:
            raise RuntimeError("no judge configured")
        probs, error = judge_mod.judge(llm, state, questions, timeout), None
    except Exception as e:  # fail open
        probs, error = {}, f"{type(e).__name__}: {e}"[:500]
    return probs, error, round((time.monotonic() - t0) * 1000)


DEFAULT_BAND = (0.3, 0.85)


def _chain(rule: dict, judges: dict, escalate: dict | None) -> list[str]:
    """Judge names a rule's question goes through, first to last."""
    if rule.get("cascade"):
        return [j for j in rule["cascade"] if j in judges] or ["default"]
    return ["default", "escalate"] if escalate else ["default"]


def _order(chains: list[list[str]]) -> list[str]:
    """Judges in an order where every judge comes after the ones that precede it in any chain, so
    each is asked once per call. Contradictory chains fall back to first-seen order."""
    import graphlib
    ts = graphlib.TopologicalSorter()
    for c in chains:
        ts.add(c[0])
        for a, b in zip(c, c[1:]):
            ts.add(b, a)
    try:
        return list(ts.static_order())
    except graphlib.CycleError:
        return list(dict.fromkeys(j for c in chains for j in c))


def evaluate(rules_cfg: dict, state: dict, llm=None, timeout: float = 3.0,
             judge_threshold: float | None = None, escalate: dict | None = None,
             judges: dict | None = None) -> dict:
    """Code rules (pattern, fact) first, then model rules through their judge chain: one request
    per judge, covering the rules that reached it. Never raises.

    judge_threshold: the default judge's calibrated trip threshold (config `judge.threshold`); a rule's
        own `threshold` wins, then the answering judge's, then the rules file default.
    escalate: {"llm", "band": [low, high], "timeout", "threshold"}; default-judge answers with
        low <= p < high are re-asked (rules without their own `cascade`).
    judges: named judges {name: {"llm", "timeout", "threshold"}} for per-rule `cascade: [a, b]`;
        a rule's `band` (else `defaults.band`) sets when to move on to the next judge.
    """
    call = state["call"]
    defaults = rules_cfg["defaults"]
    text = pattern_text(call)
    selected = [r for r in rules_cfg["rules"] if applies(r, call.get("tool"), text or "")]
    results, questions, error = {}, {}, None

    for r in selected:
        k = kind(r)
        if k == "pattern":
            results[r["id"]] = {"p": 1.0 if re.search(r["pattern"], text or "") else 0.0, "source": "pattern"}
        elif k == "fact":
            results[r["id"]] = {"p": 1.0 if fact_holds(r, state) else 0.0, "source": "fact"}
        elif r.get("question"):
            questions[r["id"]] = {"question": r["question"], "criteria": r["criteria"]} if r.get("criteria") else r["question"]

    # Enforcing and a code rule already denies: the model can't change the outcome, skip it.
    if rules_cfg.get("enforce") and any(
            results[r["id"]]["p"] >= 1.0 and r.get("action", defaults["action"]) == "deny"
            for r in selected if kind(r) != "model"):
        questions = {}

    registry = {**(judges or {}), "default": {"llm": llm, "timeout": timeout, "threshold": judge_threshold}}
    if escalate:
        registry["escalate"] = {"band": DEFAULT_BAND, **escalate}
    by_id = {r["id"]: r for r in selected}
    chains = {rid: _chain(by_id[rid], registry, escalate) for rid in questions}
    bands = {rid: tuple(by_id[rid].get("band") or (registry["escalate"]["band"] if chains[rid][-1:] == ["escalate"]
                                                   else defaults.get("band") or DEFAULT_BAND)) for rid in questions}
    rung = {rid: 0 for rid in questions}
    asked, latency_ms, escalated, esc_ms, esc_error = {}, None, [], None, None
    for name in _order(list(chains.values())) if questions else []:
        batch = {rid: questions[rid] for rid in questions if rung[rid] is not None and chains[rid][rung[rid]] == name}
        if not batch:
            continue
        j = registry[name]
        probs, err, ms = _ask(j["llm"], state, batch, j.get("timeout", timeout))
        asked[name] = {"provider": getattr(j["llm"], "name", None), "ms": ms, "error": err, "rules": list(batch)}
        latency_ms = (latency_ms or 0) + ms
        if name == "default":
            error = err
        elif name == "escalate":
            esc_ms, esc_error = ms, err
        for rid in batch:
            prev = results.get(rid)
            if prev and (err or rid not in probs):  # a later judge failed: keep the earlier answer
                rung[rid] = None
                continue
            res = {"p": probs.get(rid), "source": "model" if not prev else "escalated"}
            if prev:
                res["p0"] = prev.get("p0", prev["p"])
                escalated.append(rid)
            if by_id[rid].get("cascade"):
                res["judge"] = name
            results[rid] = res
            low, high = bands[rid]
            more = rung[rid] + 1 < len(chains[rid])
            rung[rid] = rung[rid] + 1 if more and res["p"] is not None and low <= res["p"] < high else None

    action = "allow"
    for r in selected:
        res = results.get(r["id"])
        if not res:
            continue
        judge_name = res.get("judge") or ("escalate" if res["source"] == "escalated" else "default")
        t = threshold(r, res["source"], defaults, registry.get(judge_name, {}).get("threshold"))
        res["tripped"] = res["p"] is not None and res["p"] >= t
        a = r.get("action", defaults["action"]) if res["tripped"] else None
        if not res["tripped"] and r.get("ask_when_unsure") and res["p"] is not None and r["id"] in bands:
            low, high = bands[r["id"]]
            if low <= res["p"] < high:  # the last judge is still unsure: let a human decide
                res["unsure"] = True
                a = "ask"
        if a and SEVERITY[a] > SEVERITY[action]:
            action = a

    out = {
        "results": results,
        "action": action,
        "enforced": action if rules_cfg.get("enforce") and action in ("ask", "deny") else "allow",
        "provider": getattr(llm, "name", None) if "default" in asked else None,
        "latency_ms": latency_ms,
        "error": error,
        "state_hash": state_hash(state),
    }
    if escalate and (esc_ms is not None):
        out.update(escalated=[rid for rid in escalated if chains[rid][-1:] == ["escalate"]],
                   escalation_provider=escalate["llm"].name, escalation_ms=esc_ms, escalation_error=esc_error)
        if not out["escalated"] and not esc_error:
            for k in ("escalated", "escalation_provider", "escalation_ms", "escalation_error"):
                out.pop(k)
    if set(asked) - {"default", "escalate"}:
        out["judges"] = asked
        if len(asked) > 1:  # time spent past the first judge
            out["escalation_ms"] = latency_ms - next(iter(asked.values()))["ms"]
    return out


def threshold(rule: dict, source: str, defaults: dict, judge_threshold: float | None = None) -> float:
    """A rule's own threshold, else the answering judge's calibrated one, else the rules default."""
    if "threshold" in rule:
        return rule["threshold"]
    if source in ("model", "escalated") and judge_threshold is not None:
        return judge_threshold
    return defaults["threshold"]


def reason(decision: dict) -> str:
    tripped = [f"{rid} (p={r['p']:.2f})" for rid, r in decision["results"].items() if r.get("tripped")]
    return "good-cop: " + ", ".join(tripped)
