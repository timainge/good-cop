# Other Agents

| agent | status | install |
|---|---|---|
| Claude Code | verified | `good-cop install` |
| OpenAI Codex CLI | verified (real payloads + live block) | `good-cop install --harness codex`, then `/hooks` to trust |
| Cursor | adapter from docs, untested | `good-cop install --harness cursor`, or enable Cursor's third-party (Claude) hooks |
| GitHub Copilot | adapter from docs, untested | `good-cop install --harness copilot` |
| OpenCode | plugin sketch, untested | copy `examples/opencode/good-cop.ts` to `.opencode/plugins/` |

Internally everything speaks Claude Code's hook schema. `src/good_cop/harness.py`:
- translates each harness's payloads in, and decisions out;
- maps tool names (`Shell→Bash`, `view→Read`, …);
- treats Codex `apply_patch` as an edit;
- turns `ask` into `deny` where a harness can't ask.

**Codex notes:**
- Payloads match Claude's schema, plus `turn_id` and `model`.
- File edits arrive as `apply_patch`.
- For headless runs: `codex exec --dangerously-bypass-hook-trust ... </dev/null`.

**Help wanted:** capture real Cursor and Copilot payloads into `tests/fixtures/<harness>/` so their adapters can move from "from docs" to "verified". Research and sources: [docs/harnesses.md](https://github.com/timainge/good-cop/blob/main/docs/harnesses.md).
