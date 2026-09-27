# Getting Started

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), macOS or Linux, and an API key for the judge you choose (or a local model).

```sh
git clone https://github.com/timainge/good-cop && cd good-cop
uv sync
uv run good-cop install                  # Claude Code: ~/.claude/settings.json (backed up first)
uv run good-cop install --harness codex  # or Codex: ~/.codex/hooks.json, then trust it with /hooks
```

This also creates `~/.good-cop/config.yaml` (the judge) and `~/.good-cop/rules.yaml` (your rules).

1. **Pick a judge.** The default is Claude Haiku 4.5, so export `ANTHROPIC_API_KEY` where you launch your agent. See [[Choosing a Judge]].
2. **Use your agent normally.** good-cop runs in log-only mode.
3. **Look at what it saw:**
   ```sh
   uv run good-cop show        # ledger, recent decisions, latency
   ```
4. **Tune your rules** ([[Writing Rules]]) and measure them ([[Backtesting]]).
5. **Turn on enforcement** when you trust a rule: `enforce: true` in `rules.yaml`. Tripped `ask`/`deny` rules then prompt you or block.

**Safety net:** every hook fails open. If good-cop crashes or a judge times out, the tool call proceeds and the error is written to `~/.good-cop/errors.log`.

**Uninstall:** `uv run good-cop uninstall` (add `--harness codex` for Codex). It removes exactly what install added.
