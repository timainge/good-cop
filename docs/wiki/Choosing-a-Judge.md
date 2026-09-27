# Choosing a Judge

Set `judge` in `~/.good-cop/config.yaml`. Measured on our own sessions (anecdotal; [full results](https://github.com/timainge/good-cop/blob/main/docs/results.md)):

| judge | quality (mean F1) | p50 | cost / 1k calls | private? | config |
|---|---|---|---|---|---|
| **Jev** + criteria, threshold ~0.9 | 0.84–0.97 | **0.29 s** | ~$0.08 | no (redacted) | `provider: jev`, `TYPESAFE_API_KEY` |
| Claude Haiku 4.5 | 0.57–0.91 | 1.1 s | ~$2.40 | no (redacted) | `provider: anthropic` (default) |
| gpt-5-mini | 0.66–0.79 | 1.0 s | ~$0.85 | no (redacted) | `provider: openai` |
| Kev-4B (local) | 0.71–0.76 | 2.0 s | $0 | yes | `provider: jev`, `base_url: http://127.0.0.1:8009` |
| qwen2.5-7b (Ollama) | 0.74–0.84 | 8 s | $0 | yes | `provider: ollama` |

**Recommendations**
- **Live, cheap and fast:** Jev direct from TypeSafe, with rule criteria and `judge.threshold: 0.85`–`0.9` tuned on your labels. Use TypeSafe's API rather than a gateway: through Vercel's gateway, Jev was almost entirely rate-limited when we tested.
- **Accurate with no tuning:** Haiku 4.5.
- **Nothing leaves the machine:** Kev-4B (a Jev-compatible open model on Apple Silicon via MLX) at threshold ~0.7. Ollama is fine for backtests but slow live.

**Cascade (optional).** `escalate` re-asks a second judge only for answers in an uncertain band:
```yaml
judge: {provider: jev, model: jev-latest, base_url: https://api.typesafe.ai, threshold: 0.9}
escalate: {provider: anthropic, model: claude-haiku-4-5-20251001, band: [0.5, 0.9]}
```
It escalated 3–11% of calls and kept Jev's latency. It only helps when the second judge is better on the borderline cases, which wasn't true on our held-out data.

**Privacy.** For cloud judges, good-cop redacts common secret formats and secret-named environment variable values from the state before sending. Localhost endpoints are not redacted (`redact: auto`). See [SECURITY.md](https://github.com/timainge/good-cop/blob/main/SECURITY.md).
