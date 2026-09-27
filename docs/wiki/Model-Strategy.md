# Choosing judges as a ruleset matures

*Large LLMs, small LLMs, decision models, locally trained models and plain code: which one should answer a rule, and does that change as the rules mature? Written 2026-09-27 from good-cop's first evals (see [Results](Results)). The evidence is anecdotal: our own sessions, a few hundred tool calls, contrived rules.*

## Short answer

No single kind of judge wins. Which one fits depends on how well you understand the rule, and that changes over time. A new rule starts as an English question to a capable LLM. As labelled examples pile up and its edges become clear, it moves down a ladder: to a cheaper decision model, then to a locally trained one, and, where the answer turns out to be mechanical, to code. The end state is a hybrid. The model never goes away, because ambiguity never fully goes away, but it stops being the first thing asked.

Flexibility doesn't always beat static rules. It wins on ambiguity, novelty and indirection. Code wins on anything exact, auditable or adversarial. good-cop's first principle, *facts by code, judgement by model*, is this split applied to a single rule.

## The options, as seen in our data

| judge | strengths | weaknesses | our numbers (contrived rules) |
|---|---|---|---|
| **Code** (regex, ledger facts) | exact, instant, free, auditable, same answer every time | brittle to phrasing; each case hand-written | `git_commit` regex: 0.98 accuracy, fooled by commits inside quoted strings and by `git -c k=v commit` |
| **Large/frontier LLM** (Haiku 4.5, gpt-5-mini) | zero-shot on any English question; reads scripts and intent | ~1–2 s, per-token cost, data leaves the machine, self-reported probabilities | Haiku 0.93–1.00 across rules; gpt-5-mini 0.92–0.98 |
| **Small general LLM, local** (qwen2.5-7b on Ollama) | private, no marginal cost | slow on an 8k-token state (13 s p50 on an M5), weaker instruction following | 0.83–0.95; missed every test run in one sample |
| **Decision model, hosted** (Jev) | built for yes/no and choice answers: calibrated probabilities, all questions in one pass, 70–500 ms advertised, $0.042/M input tokens | hosted; capacity-limited at launch (most calls returned 429) | see results.md |
| **Decision model, local** (Kev-4B) | Jev's API, private, no marginal cost | ~9 GB download; ~2 s p50 on our states; flatter probabilities that need per-rule thresholds | 0.83–1.00, recall 1.00 on every rule; false positives cluster at p 0.5–0.77 |
| **Locally trained** (fine-tuned Kev/Laya on your labels) | learns *your* boundary cases; small and fast | needs hundreds of labels per rule, a training loop and re-validation | not tried yet; Laya's authors report base 0.36 → 0.77 accuracy after fine-tuning |

Two findings keep coming up:

- **The model was often right when our code was wrong.** Our first backtest's disagreements were mostly ledger bugs: Bash-written scripts, `cd dir && ./x.sh`, `$S/run.sh`. Haiku inferred what the parser missed. Models are a good way to *find* the facts code should capture.
- **The model was sometimes wrong where code is exact.** `outside_workspace` kept firing on reads of sibling repos even when told reads don't count, and even with `resolved.writes[].outside_cwd` in the state. When the answer is a comparison of two paths, compute it.

## A maturity ladder for one rule

```
 ambiguity high ─────────────────────────────────────────────────────────▶ low
 labels   none           tens             hundreds            thousands
 ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────┐
 │ 1. Explore   │→ │ 2. Measure   │→ │ 3. Delegate      │→ │ 4. Crystallise    │
 │ English      │  │ backtest +   │  │ decision model   │  │ code for the      │
 │ question to  │  │ labels; fix  │  │ (hosted or       │  │ mechanical part,  │
 │ a large LLM, │  │ wording and  │  │ local), tuned    │  │ trained model for │
 │ log only     │  │ missing      │  │ threshold, big   │  │ the residue, LLM  │
 │              │  │ ledger facts │  │ LLM on low       │  │ only when unsure  │
 │              │  │              │  │ confidence       │  │                   │
 └──────────────┘  └──────────────┘  └──────────────────┘  └───────────────────┘
```

1. **Explore.** You don't yet know what "touches production" means in your environment. Ask a capable LLM in log mode. It's the cheapest way to learn the rule's shape, and it produces candidate labels.
2. **Measure.** Label a sample (human or deterministic truth), backtest, read the disagreements. Most early errors are in wording or missing facts, not the model. Reword, and add ledger facts for anything the model had to infer.
3. **Delegate.** Once a rule is a crisp yes/no question with measured accuracy, a decision model answers it more cheaply and faster, with probabilities that can be thresholded. Keep a large LLM behind it for calls where the decision model is unsure (TypeSafe's "confidence-gated routing" pattern), and send high-stakes or low-confidence calls to `ask` (the human).
4. **Crystallise.** Move what's mechanical into code: path comparisons, known destructive commands, environment facts. Train a small local model on the accumulated labels for what's left. The LLM becomes the fallback for novelty.

Different rules sit at different rungs at the same time. In good-cop, `destructive_rm` starts at rung 4, `prod_target` sits at rung 1 for most teams, and `outside_workspace` showed it belongs at rung 4.

## Will flexibility always beat rules?

No. Four reasons the hybrid wins:

- **Adversarial pressure favours code.** The judge reads attacker-influenced text: file contents, command output, fetched pages. An LLM judge can be prompt-injected by the very thing it's judging. A decision model that doesn't generate text may be harder to steer, but that is unverified. A regex can't be talked out of matching, though it can be evaded by rephrasing. Neither alone is enough against a determined adversary, which is why good-cop's stated limit is "ordinary mistakes and indirection, not deliberate concealment".
- **Auditability and determinism.** A deny should be explainable and reproducible. Code gives the same answer on replay. A model's answer can shift with version, temperature or context order. Pinning model versions and backtesting on each upgrade mitigates this but doesn't remove it.
- **Latency and cost compound.** Every tool call pays the judge. At ~1,000 calls a day with ~2k-token states, a frontier LLM costs dollars per developer per day and adds 1–2 s to each call. Code costs nothing. A decision model costs cents.
- **The long tail favours models.** New tools, MCP servers, script languages and phrasings appear constantly. A rule written as code covers what its author thought of. A rule written as a question generalises. This is where models keep winning, and why the ladder never reaches "no model".

A practical corollary: **write every rule as a question first, even if you intend to encode it.** The question is the specification. Backtesting the question against labels tells you whether the code you later write is faithful, and the model remains a fallback for what the code misses.

## Implications for good-cop

- Support a cascade per rule: pattern or ledger check → decision model → large LLM when the decision model is unsure (`p` between two thresholds) → `ask`. Today each rule has one judge.
- Let rules be predicates over state (`resolved.writes[].outside_cwd`), not just regexes over the command.
- Store per-provider thresholds. Kev's calibration differs from Haiku's.
- Treat labels as the durable asset. They outlive any model choice and are what make a local fine-tune possible.
