# Getting Started

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), macOS or Linux, and an API key for the judge you choose (or a local model).

```sh
uv tool install git+https://github.com/timainge/good-cop   # PyPI release pending; or `pipx install git+…`
good-cop install                  # Claude Code: ~/.claude/settings.json (backed up first)
good-cop install --harness codex  # or Codex: ~/.codex/hooks.json, then trust it with /hooks
good-cop install --ruleset infra  # optionally add starter rulesets: infra, data, unattended (see [[Rulesets]])
```

The hook command written to your settings is the installed `good-cop` (so hooks keep working from any directory). `uvx good-cop install` also works; hooks then run `uvx good-cop hook`, which is slower to start than an installed tool. Working on good-cop itself? `git clone`, `uv sync`, then `uv run good-cop install` points the hooks at the repo's `.venv`.

This also creates `~/.good-cop/config.yaml` (the judge) and `~/.good-cop/rules.yaml` (your rules, which `include: [solo-dev]` by default; `good-cop rules show` prints what's in effect).

1. **Pick a judge.** The default is Claude Haiku 4.5, so export `ANTHROPIC_API_KEY` where you launch your agent. See [[Choosing a Judge]].
2. **Use your agent normally.** good-cop runs in log-only mode.
3. **Look at what it saw:**
   ```sh
   good-cop show        # ledger, recent decisions, latency
   good-cop review      # label what it flagged; suggests thresholds
   ```
4. **Tune your rules** ([[Writing Rules]]) and measure them ([[Backtesting]]).
5. **Turn on enforcement** when you trust a rule: `enforce: true` in `rules.yaml`. Tripped `ask`/`deny` rules then prompt you or block.

**Safety net:** every hook fails open. If good-cop crashes or a judge times out, the tool call proceeds and the error is written to `~/.good-cop/errors.log`.

**Uninstall:** `good-cop uninstall` (add `--harness codex` for Codex). It removes exactly what install added.
