"""Red-team scenarios: replay hand-written adversarial sessions through the rules and each judge.

    uv run python evals/redteam/run.py                        # code rules only (patterns, facts): free, CI
    uv run python evals/redteam/run.py --config examples/configs/jev-typesafe.yaml --config examples/configs/anthropic.yaml

Scenario files (`evals/redteam/*.jsonl`): line 1 is metadata
  {"type": "scenario", "name", "about", "caught_if": "any"|"all", "code_caught": bool, "limit": "..."}
then events as live mode would record them. A `{"type": "call", "tool", "input", "result"?, "resolved"?,
"agent_id"?, "expect"?: [rule ids]}` line expands to a pre_tool + post_tool pair; `expect` marks a call
that should be caught by any of those rules. Nothing is executed. `code_caught` documents what the
code-only rules catch today; tests/test_redteam.py fails if that changes, so fixes update the file.
"""
import argparse
import json
import sys
from pathlib import Path

from good_cop import backtest, config, providers, rules

HERE = Path(__file__).parent
RULES = HERE / "rules.yaml"


def load(path: Path) -> tuple[dict, list[dict], dict[int, list[str]]]:
    """(meta, events with seq, {seq: expected rule ids})."""
    lines = [json.loads(l) for l in path.read_text().splitlines() if l.strip() and not l.startswith("//")]
    meta, events, expect = lines[0], [], {}
    sid = meta["name"]
    for raw in lines[1:]:
        if raw["type"] == "call":
            base = {k: raw[k] for k in ("tool", "input", "agent_id", "agent_type") if k in raw}
            base.update(cwd=raw.get("cwd", meta.get("cwd", "/home/dev/app")), tool_use_id=f"t{len(events)}")
            pre = {"type": "pre_tool", **base, **({"resolved": raw["resolved"]} if "resolved" in raw else {})}
            events.append(pre)
            if raw.get("expect"):
                expect[len(events)] = raw["expect"]
            events.append({"type": "post_tool", **base, "result": raw.get("result", "")})
        else:
            events.append({"cwd": meta.get("cwd", "/home/dev/app"), **raw})
    for i, e in enumerate(events, 1):
        e.update(seq=i, ts=f"2026-10-03T00:00:{i:02d}.000+00:00", session_id=sid)
    return meta, events, expect


def scenarios() -> list[Path]:
    return sorted(HERE.glob("*.jsonl"))


def evaluate(path: Path, rules_cfg: dict, opts: dict | None) -> dict:
    """Which expected calls each rule caught. opts=None: code rules only (no judge)."""
    meta, events, expect = load(path)
    cfg = config.load_config(HERE / "replay.yaml")
    per_call = {}
    for e, state in backtest.replay(events, cfg):
        if e["seq"] not in expect:
            continue
        d = rules.evaluate(rules_cfg, state, **(opts or {"llm": None}))
        tripped = [rid for rid, r in d["results"].items() if r.get("tripped")]
        per_call[e["seq"]] = {"caught_by": [rid for rid in tripped if rid in expect[e["seq"]]],
                              "tripped": tripped, "error": d.get("error") if opts else None}
    hits = [bool(c["caught_by"]) for c in per_call.values()]
    caught = all(hits) if meta.get("caught_if") == "all" else any(hits)
    return {"name": meta["name"], "about": meta.get("about", ""), "caught": caught, "calls": per_call, "meta": meta}


def run(config_paths: list[str], rules_path: Path = RULES) -> dict:
    rules_cfg = config.load_rules(rules_path)
    columns = {"code only": None}
    for p in config_paths:
        opts = providers.judge_options(config.load_config(p), backtest=True)
        columns[f"{opts['llm'].name} ({Path(p).stem})"] = opts
    return {name: [evaluate(s, rules_cfg, opts) for s in scenarios()] for name, opts in columns.items()}


def render(results: dict) -> str:
    names = list(results)
    rows = list(zip(*results.values()))
    out = ["| scenario | " + " | ".join(names) + " |", "|---" * (len(names) + 1) + "|"]
    for row in rows:
        cells = []
        for r in row:
            by = sorted({rid for c in r["calls"].values() for rid in c["caught_by"]})
            err = any(c.get("error") for c in r["calls"].values())
            cells.append(("caught" if r["caught"] else "**missed**") + (f" ({', '.join(by)})" if by else "")
                         + (" ⚠ judge error" if err else ""))
        out.append(f"| {row[0]['name']} | " + " | ".join(cells) + " |")
    out.append("")
    out.append("| | " + " | ".join(f"{sum(r['caught'] for r in results[n])}/{len(results[n])}" for n in names) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", action="append", default=[])
    ap.add_argument("--rules", default=str(RULES))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = run(a.config, Path(a.rules))
    if a.json:
        json.dump(res, sys.stdout, indent=1, default=str)
    else:
        print(render(res))
