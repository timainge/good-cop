"""Rule selection, pattern evaluation, threshold and action logic. See plan.md §5."""

import fnmatch
import hashlib
import json
import re
import time

from good_cop import judge as judge_mod

SEVERITY = {"allow": 0, "log": 1, "ask": 2, "deny": 3}


def applies(rule: dict, tool: str) -> bool:
    tools = (rule.get("when") or {}).get("tools")
    return not tools or any(fnmatch.fnmatchcase(tool or "", t) for t in tools)


def pattern_text(call: dict) -> str:
    inp = call.get("input") or {}
    return inp.get("command") if isinstance(inp.get("command"), str) else json.dumps(inp)


def state_hash(state: dict) -> str:
    return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest()[:16]


def evaluate(rules_cfg: dict, state: dict, llm=None, timeout: float = 3.0) -> dict:
    """Run pattern rules in code and model rules in one judge call. Never raises."""
    call = state["call"]
    defaults = rules_cfg["defaults"]
    selected = [r for r in rules_cfg["rules"] if applies(r, call.get("tool"))]
    results, questions, error = {}, {}, None

    text = pattern_text(call)
    for r in selected:
        if r.get("pattern"):
            results[r["id"]] = {"p": 1.0 if re.search(r["pattern"], text or "") else 0.0, "source": "pattern"}
        elif r.get("question"):
            questions[r["id"]] = r["question"]

    # Enforcing and a pattern rule already denies: the model can't change the outcome, skip it.
    if rules_cfg.get("enforce") and any(
            results[r["id"]]["p"] >= r.get("threshold", defaults["threshold"])
            and r.get("action", defaults["action"]) == "deny" for r in selected if r.get("pattern")):
        questions = {}

    latency_ms = None
    if questions:
        t0 = time.monotonic()
        try:
            if llm is None:
                raise RuntimeError("no judge configured")
            probs = judge_mod.judge(llm, state, questions, timeout)
        except Exception as e:  # fail open
            probs, error = {}, f"{type(e).__name__}: {e}"[:500]
        latency_ms = round((time.monotonic() - t0) * 1000)
        for rid in questions:
            results[rid] = {"p": probs.get(rid), "source": "model"}

    action = "allow"
    for r in selected:
        res = results.get(r["id"])
        if not res:
            continue
        threshold = r.get("threshold", defaults["threshold"])
        res["tripped"] = res["p"] is not None and res["p"] >= threshold
        if res["tripped"]:
            a = r.get("action", defaults["action"])
            if SEVERITY[a] > SEVERITY[action]:
                action = a

    return {
        "results": results,
        "action": action,
        "enforced": action if rules_cfg.get("enforce") and action in ("ask", "deny") else "allow",
        "provider": getattr(llm, "name", None) if questions else None,
        "latency_ms": latency_ms,
        "error": error,
        "state_hash": state_hash(state),
    }


def reason(decision: dict) -> str:
    tripped = [f"{rid} (p={r['p']:.2f})" for rid, r in decision["results"].items() if r.get("tripped")]
    return "good-cop: " + ", ".join(tripped)
