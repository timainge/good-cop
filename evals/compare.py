"""Markdown comparison of backtest runs whose note starts with a tag, re-scored against the
current labels (so label fixes apply to old runs; the summaries keep their original scores).

    uv run python evals/compare.py [tag]
"""
import sys

from good_cop import backtest, store

tag = sys.argv[1] if len(sys.argv) > 1 else "comparison-"
labels = backtest.load_labels()
runs = []
for p in sorted((store.ROOT / "backtests").glob("*.summary.json")):
    doc = store.read_json(p)
    note = doc["meta"].get("note") or ""
    if note.startswith(tag):
        recs = store.read_jsonl(p.with_name(p.name.replace(".summary.json", ".jsonl")))
        if sum(1 for r in recs if r.get("error")) > len(recs) / 2:  # mostly failed: nothing to score
            print(f"(skipped {note!r}: {sum(1 for r in recs if r.get('error'))}/{len(recs)} judge errors)")
            continue
        runs.append((note.split(": ", 1)[-1], backtest.metrics(recs, doc["meta"]["rules"], labels)))

if not runs:
    sys.exit(f"no runs tagged {tag!r}")
model_rules = [rid for rid, x in runs[0][1]["rules"].items() if x["kind"] == "model"]
f = lambda v: "–" if v is None else f"{v:.2f}"
m0 = runs[0][1]
first = next(iter(m0["rules"][model_rules[0]]["by_config"]))
pos = {r: m0["rules"][r]["by_config"][first]["tp"] + m0["rules"][r]["by_config"][first]["fn"] for r in model_rules}
print(f"{m0['calls']} calls from {len(m0['sessions'])} sessions; cells are accuracy (precision/recall)\n")
print("| judge | " + " | ".join(f"{r} ({pos[r]}+)" for r in model_rules) + " | mean acc | mean recall | mean F1 | errors | p50 ms | p95 ms |")
print("|---" * (len(model_rules) + 7) + "|")
for name, m in runs:
    c = m["configs"][0]
    xs = [m["rules"][r]["by_config"][c["config"]] for r in model_rules]
    accs = [x["acc"] for x in xs if x["acc"] is not None]
    recalls = [x["recall"] or 0.0 for x in xs if x["tp"] + x["fn"]]
    f1s = [2 * x["tp"] / (2 * x["tp"] + x["fp"] + x["fn"]) for x in xs if x["tp"] + x["fp"] + x["fn"]]
    mean = lambda v: sum(v) / max(1, len(v))
    cells = [f"{f(x['acc'])} ({f(x['precision'])}/{f(x['recall'])})" for x in xs]
    print(f"| {name} | " + " | ".join(cells) +
          f" | {mean(accs):.3f} | {mean(recalls):.2f} | {mean(f1s):.2f} | {c['errors']}/{c['calls']} | {c['p50_ms']} | {c['p95_ms']} |")
