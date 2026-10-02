"""Threshold sweep from saved probabilities, re-scored against current labels (no judge calls).

    uv run python evals/thresholds.py [tag]    # runs whose note starts with tag (default: comparison-)
"""
import sys

from good_cop import backtest, store

tag = sys.argv[1] if len(sys.argv) > 1 else "comparison-"
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)
labels = backtest.load_labels()


def score(recs, rule_ids, t):
    f1s, recalls, positives = [], [], 0
    for rid in rule_ids:
        s = backtest.score_at(recs, rid, labels, t)
        positives += s["tp"] + s["fn"]
        if s["f1"] is not None:
            f1s.append(s["f1"])
        if s["recall"] is not None:
            recalls.append(s["recall"])
    return sum(f1s) / len(f1s), sum(recalls) / len(recalls), positives


print(f"cells: mean F1 / mean recall over model rules, re-scored at each threshold\n")
print("| judge | " + " | ".join(f"t={t}" for t in THRESHOLDS) + " |")
print("|---" * (len(THRESHOLDS) + 1) + "|")
for p in sorted((store.ROOT / "backtests").glob("*.summary.json")):
    doc = store.read_json(p)
    note = doc["meta"].get("note") or ""
    if not note.startswith(tag):
        continue
    recs = store.read_jsonl(p.with_name(p.name.replace(".summary.json", ".jsonl")))
    if sum(1 for r in recs if r.get("error")) > len(recs) / 2:
        continue
    rule_ids = [r["id"] for r in doc["meta"]["rules"] if r.get("question")]
    cells = [score(recs, rule_ids, t) for t in THRESHOLDS]
    print(f"| {note.split(': ', 1)[-1]} ({cells[0][2]}+) | " + " | ".join(f"{f:.2f} / {r:.2f}" for f, r, _ in cells) + " |")
