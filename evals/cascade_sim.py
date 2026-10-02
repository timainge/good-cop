"""Per-rule cascade, simulated from two saved runs over the same calls (no judge calls).

    uv run python evals/cascade_sim.py FIRST_RUN SECOND_RUN [--band 0.5 0.9] [--t1 0.9] [--t2 0.6]

For each model rule: F1 of the first judge alone, the second alone, and first -> second when the first
answer is in the band, scored against the current labels. Shows which rules a cascade would help.
"""
import argparse

from good_cop import backtest, store

ap = argparse.ArgumentParser()
ap.add_argument("first")
ap.add_argument("second")
ap.add_argument("--band", nargs=2, type=float, default=[0.5, 0.9])
ap.add_argument("--t1", type=float, default=0.9)
ap.add_argument("--t2", type=float, default=0.6)
a = ap.parse_args()

load = lambda run: {(r["session"], r["seq"]): r for r in store.read_jsonl(backtest.store.ROOT / "backtests" / f"{run}.jsonl")}
A, B = load(a.first), load(a.second)
meta = store.read_json(store.ROOT / "backtests" / f"{a.first}.summary.json")["meta"]
labels = backtest.load_labels()
low, high = a.band
keys = sorted(set(A) & set(B))


def f1(hits):
    tp = sum(1 for k, h in hits if h and labels.get(k))
    fp = sum(1 for k, h in hits if h and labels.get(k) is False)
    fn = sum(1 for k, h in hits if not h and labels.get(k))
    return (2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None), tp + fn


print(f"{len(keys)} shared calls; band [{low}, {high}); t1={a.t1} t2={a.t2}\n")
print(f"| rule | {A[keys[0]]['provider']} | {B[keys[0]]['provider']} | cascade | escalated |")
print("|---|---|---|---|---|")
for rid in [r["id"] for r in meta["rules"] if r.get("question")]:
    sa, sb, sc, esc = [], [], [], 0
    for k in keys:
        pa, pb = (A[k]["results"].get(rid) or {}).get("p"), (B[k]["results"].get(rid) or {}).get("p")
        if pa is None or pb is None or labels.get((*k, rid)) is None:
            continue
        key = (*k, rid)
        sa.append((key, pa >= a.t1))
        sb.append((key, pb >= a.t2))
        if low <= pa < high:
            esc += 1
            sc.append((key, pb >= a.t2))
        else:
            sc.append((key, pa >= a.t1))
    (fa, pos), (fb, _), (fc, _) = f1(sa), f1(sb), f1(sc)
    fmt = lambda v: "-" if v is None else f"{v:.2f}"
    best = max((v for v in (fa, fb, fc) if v is not None), default=None)
    cell = lambda v: f"**{fmt(v)}**" if v is not None and v == best else fmt(v)
    print(f"| {rid} ({pos}+) | {cell(fa)} | {cell(fb)} | {cell(fc)} | {esc}/{len(sa)} |")
