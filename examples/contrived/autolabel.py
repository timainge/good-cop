"""Write ground-truth labels for the contrived rules to ~/.good-cop/labels.jsonl.

npm/pnpm/yarn scripts are expanded from the repo's package.json as it is on disk now, so
`npm run check` counts as a test run when `check` runs `npm test`.

    uv run python examples/contrived/autolabel.py [session ...]   # default: all sessions
"""

import json
import sys
from collections import Counter
from pathlib import Path

from good_cop import backtest, config, ledger, rules, store

TEST_RUNNERS = {"pytest", "vitest", "jest", "mocha"}


def programs(cmd: str, cwd: str = "/") -> list[tuple[list[str], str]]:
    """(tokens, cwd) per simple command, heredoc bodies dropped, launchers (uv run, npx) stripped."""
    return [(ledger._unwrap(tokens), c) for tokens, c in ledger.segments(cmd, cwd)]


def npm_scripts(cwd: str) -> dict:
    """`scripts` from the nearest package.json at or above cwd (as it is on disk today)."""
    d = Path(cwd or "/")
    for p in [d, *d.parents]:
        f = p / "package.json"
        if f.exists():
            try:
                return json.loads(f.read_text()).get("scripts") or {}
            except (OSError, ValueError):
                return {}
    return {}


def is_test(t: list[str], cwd: str = "/", depth: int = 0) -> bool:
    if not t:
        return False
    if t[0] in TEST_RUNNERS or t[0].endswith("/pytest"):
        return True
    if t[0] in ("npm", "pnpm", "yarn", "bun") and len(t) > 1:
        name = t[2] if t[1] == "run" and len(t) > 2 else t[1]
        if name == "test" or name.startswith("test"):
            return True
        body = npm_scripts(cwd).get(name) if depth < 3 else None  # follow `npm run check` -> `npm test`
        return bool(body) and any(is_test(p, c, depth + 1) for p, c in programs(body, cwd))
    if t[0] in ("go", "cargo", "make") and t[1:2] == ["test"]:
        return True
    return t[0].startswith("python") and t[1:3] in (["-m", "pytest"], ["-m", "unittest"])


def truth(rule_id: str, e: dict) -> bool:
    inp = e.get("input") or {}
    cmd = inp.get("command", "") if isinstance(inp.get("command"), str) else ""
    progs = programs(cmd, e.get("cwd") or "/")
    if rule_id == "edits_markdown":
        return str(inp.get("file_path", "")).endswith(".md")
    if rule_id == "runs_tests":
        return any(is_test(t, c) for t, c in progs)
    if rule_id in ("git_commit", "git_commit_pattern"):
        return any(t[:1] == ["git"] and "commit" in t for t, _ in progs)
    if rule_id == "runs_session_script":
        return bool(((e.get("resolved") or {}).get("script") or {}).get("written_this_session"))
    if rule_id == "web_access":
        return e.get("tool") in ("WebFetch", "WebSearch") or any(t[:1] in (["curl"], ["wget"]) for t, _ in progs)
    raise KeyError(rule_id)


def main(sessions: list[str]) -> None:
    rules_cfg = config.load_rules("examples/contrived/rules.yaml")
    totals, positives, per_session = Counter(), Counter(), Counter()
    for sid in sessions or store.list_sessions():
        for e in store.read_events(sid):
            if e["type"] != "pre_tool":
                continue
            for r in rules_cfg["rules"]:
                if rules.applies(r, e.get("tool")):
                    value = truth(r["id"], e)
                    backtest.label(sid, e["seq"], r["id"], value)
                    totals[r["id"]] += 1
                    positives[r["id"]] += value
                    per_session[sid] += value
    for rid in totals:
        print(f"{rid:<22} {positives[rid]:>5} yes / {totals[rid]:>5}")
    print("\nsessions by positives:")
    for sid, n in per_session.most_common(12):
        print(f"  {sid}  {n}")


if __name__ == "__main__":
    main(sys.argv[1:])
