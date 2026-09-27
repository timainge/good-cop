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


def applies(rule: dict, tool: str) -> bool:
    tools = (rule.get("when") or {}).get("tools")
    names = (tool or "", *EQUIVALENT_TOOLS.get(tool, ()))
    return not tools or any(fnmatch.fnmatchcase(n, t) for n in names for t in tools)


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
    """Any value at `fact` meets the condition: `equals`, `matches` (regex), `in`, else truthy."""
    for v in lookup(state, rule["fact"]):
        if "equals" in rule:
            ok = v == rule["equals"]
        elif "matches" in rule:
            ok = isinstance(v, str) and re.search(rule["matches"], v) is not None
        elif "in" in rule:
            ok = v in rule["in"]
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


def evaluate(rules_cfg: dict, state: dict, llm=None, timeout: float = 3.0,
             judge_threshold: float | None = None, escalate: dict | None = None) -> dict:
    """Code rules (pattern, fact) first, then model rules in one judge call, then optionally
    re-ask the uncertain ones with an escalation judge. Never raises.

    judge_threshold: the judge's calibrated trip threshold (config `judge.threshold`); a rule's own
        `threshold` wins, then this, then the rules file default.
    escalate: {"llm", "band": [low, high], "timeout"}; model answers with low <= p < high are re-asked.
    """
    call = state["call"]
    defaults = rules_cfg["defaults"]
    selected = [r for r in rules_cfg["rules"] if applies(r, call.get("tool"))]
    results, questions, error = {}, {}, None

    text = pattern_text(call)
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

    latency_ms, escalated, esc_ms, esc_error = None, [], None, None
    if questions:
        probs, error, latency_ms = _ask(llm, state, questions, timeout)
        for rid in questions:
            results[rid] = {"p": probs.get(rid), "source": "model"}
        if escalate and not error:
            low, high = escalate.get("band", (0.3, 0.85))
            unsure = {rid: q for rid, q in questions.items()
                      if results[rid]["p"] is not None and low <= results[rid]["p"] < high}
            if unsure:
                probs2, esc_error, esc_ms = _ask(escalate["llm"], state, unsure, escalate.get("timeout", timeout))
                for rid, p in probs2.items():
                    results[rid] = {"p": p, "source": "escalated", "p0": results[rid]["p"]}
                    escalated.append(rid)
                latency_ms += esc_ms

    action = "allow"
    for r in selected:
        res = results.get(r["id"])
        if not res:
            continue
        res["tripped"] = res["p"] is not None and res["p"] >= _threshold(r, res["source"], defaults,
                                                                         judge_threshold, escalate)
        if res["tripped"]:
            a = r.get("action", defaults["action"])
            if SEVERITY[a] > SEVERITY[action]:
                action = a

    out = {
        "results": results,
        "action": action,
        "enforced": action if rules_cfg.get("enforce") and action in ("ask", "deny") else "allow",
        "provider": getattr(llm, "name", None) if questions else None,
        "latency_ms": latency_ms,
        "error": error,
        "state_hash": state_hash(state),
    }
    if escalated or esc_error:
        out.update(escalated=escalated, escalation_provider=escalate["llm"].name,
                   escalation_ms=esc_ms, escalation_error=esc_error)
    return out


def _threshold(rule, source, defaults, judge_threshold, escalate) -> float:
    """A rule's own threshold, else the answering judge's calibrated one, else the rules default."""
    if "threshold" in rule:
        return rule["threshold"]
    if source == "model" and judge_threshold is not None:
        return judge_threshold
    if source == "escalated" and (escalate or {}).get("threshold") is not None:
        return escalate["threshold"]
    return defaults["threshold"]


def reason(decision: dict) -> str:
    tripped = [f"{rid} (p={r['p']:.2f})" for rid, r in decision["results"].items() if r.get("tripped")]
    return "good-cop: " + ", ".join(tripped)
