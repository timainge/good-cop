# Extending good-cop to other coding agents

*Research as of 2026-09-27, from official docs and changelogs (sources below). Items marked **unverified** could not be confirmed from an official source. Nothing here is implemented yet.*

## Which five

Adoption surveys: JetBrains, May–July 2026, ~15k developers [1]; Pragmatic Engineer, Jan–Feb 2026 [2]. Both put these on top: **Claude Code** (39% use it at work), **GitHub Copilot** (21%), **OpenAI Codex** (16%), **Cursor** (12%), and **OpenCode** (7%). Gemini CLI is left out because Google is retiring it in favour of Antigravity CLI [3].

## The short version

The Claude Code hook schema has become the de facto standard. Four of the five run *command* hooks with near-identical events, and two of them (Cursor and Copilot in VS Code) can read `.claude/settings.json` hooks directly. Differences come down to three things:

- **Tool names:** `Bash` vs `Shell` vs `bash`; `Edit` vs `apply_patch`.
- **Payload field names:** e.g. `sessionId` vs `session_id`.
- **Support for `ask`:** only Claude Code and Copilot honour it.

OpenCode is the exception. Its hooks are in-process TypeScript plugins.

| | Claude Code | Copilot (CLI / VS Code / cloud agent) | Codex CLI | Cursor | OpenCode |
|---|---|---|---|---|---|
| Mechanism | `hooks` in `.claude/settings.json` | `.github/hooks/*.json`, `~/.copilot/hooks/` | `.codex/hooks.json` or `[hooks]` in `config.toml` | `.cursor/hooks.json` (+ reads Claude hooks) | JS/TS plugins (Bun) |
| Session start / prompt | SessionStart / UserPromptSubmit | sessionStart / userPromptSubmitted | SessionStart / UserPromptSubmit | sessionStart / beforeSubmitPrompt | `session.created` / `chat.message` |
| Pre-tool can block? | allow / ask / deny | allow / ask / deny | deny only ("ask" not supported yet) | allow / deny ("ask" not enforced) | deny (throw) |
| Post-tool sees result? | yes | yes (`toolResult`) | yes (`tool_response`) | yes (`tool_output`) | yes (`output.output`) |
| Stop | Stop | agentStop | Stop | stop | `session.idle` |
| Subagent calls covered | yes (`agent_id`) | unverified | unverified | unverified | unverified |
| Shell / edits / MCP | all | shell + edits; MCP naming unverified | Bash, apply_patch, MCP; not hosted tools or Code Mode `exec` | all (+ dedicated MCP and shell hooks) | all (MCP fixed in PR #2320) |
| Adapter effort | done | S | S | XS (via Claude compat) – S | M |

## Per harness

### GitHub Copilot (CLI, VS Code agent mode, cloud agent)
- **Config:** `{"version":1,"hooks":{…}}` in `.github/hooks/*.json`. That one file is read by the CLI, the cloud agent and VS Code [5]. VS Code can also read `.claude/settings.json` when `chat.useClaudeHooks` is on [7].
- **Payload:** camelCase by default (`sessionId`, `toolName`, `toolArgs`, `toolResult`). Registering the PascalCase event name (`PreToolUse`) switches to a Claude-style snake_case payload [6].
- **Output:** `permissionDecision` (allow/deny/ask) plus reason. A crash or exit 2 on pre-tool fails *closed*, and a timeout fails *open* [6].
- **Gaps:** the cloud agent pre-approves tools, so `ask` is meaningless there, and it runs only `bash` hook commands [5]. Built-in tool names are `bash`, `edit`, `create`, `view` and others; MCP naming is unverified.
- **Adapter:** field mapping when payloads arrive camelCase; tool aliases (`bash→Bash`, `edit/create→Edit/Write`, `view→Read`); ship `.github/hooks/good-cop.json`.

### OpenAI Codex CLI
- **Config:** `.codex/hooks.json` (user or repo), or `[hooks]` in `config.toml`. Hooks are on by default, and hooks not from managed config need a trust review before they run [8].
- **Payload:** effectively Claude's: `session_id`, `cwd`, `tool_name`, `tool_input`, `tool_response`, plus `turn_id`. Tool names are `Bash`, `apply_patch` (matched by `Edit`/`Write` matchers) and `mcp__server__tool` [8].
- **Output:** `permissionDecision: "deny"` or exit 2. `ask` is "parsed but not supported yet" [8].
- **Gaps:** hosted tools (web search) and Code Mode `exec` don't fire PreToolUse [8][9]. There's an open request to cover read/grep [10]. The docs call hooks "a useful guardrail, not a complete enforcement boundary".
- **Adapter:** almost none. Degrade `ask` to `deny` with a reason, and teach the ledger about `apply_patch`.

### Cursor
- **Config:** `.cursor/hooks.json` at user, project and team (MDM) scope [11].
- **Payload:** `conversation_id`, `generation_id`, `workspace_roots`; pre-tool adds `tool_name`, `tool_input`, `tool_use_id`, `cwd`; post-tool adds `tool_output`. There are also dedicated `beforeShellExecution` / `beforeMCPExecution` / `beforeReadFile` hooks [11].
- **Output:** `permission` allow/deny, `agent_message`, `updated_input`. Exit 2 blocks; other failures pass unless `failClosed: true`. `ask` isn't enforced on preToolUse, and `afterFileEdit` is observe-only [11].
- **Claude compatibility:** Cursor loads `.claude/settings.json` hooks when third-party configs are enabled. It passes Claude-shaped payloads and honours `permissionDecision`, but renames tools (`Bash→Shell`, `Edit→Write`) [12].
- **Adapter:** document the Claude-compat route and add `Shell`/`Write` aliases (XS). A native adapter maps `conversation_id→session_id` and `workspace_roots[0]→cwd`.

### OpenCode
- **Config:** TS/JS plugins in `.opencode/plugins/` or npm packages under `"plugin"` in `opencode.json`. Blocking means throwing an error [13].
- **Hooks:** `tool.execute.before({tool, sessionID, callID}, {args})`, `tool.execute.after(…, {output})`, `chat.message`, `permission.ask` (status ask/deny/allow; reliability unverified), plus `event` for `session.created` / `session.idle` [13][14]. No `cwd` in tool hooks; use the plugin's `directory`.
- **Adapter:** a ~60-line plugin that spawns `good-cop hook` with a Claude-shaped payload and throws on `deny`. Published as an npm package.

### Runners-up
- **Antigravity CLI:** `hooks.json` with rich decisions (`ask`, `force_ask`, `deny_unless_prior_grant`) and `invoke_subagent` coverage. Beware that `{}` output denies [16][17].
- **Windsurf/Devin Cascade:** snake_case pre-hooks, exit-2 block only [18].
- **Cline:** Claude-spec hooks, macOS/Linux only [19].
- **Kiro, Amp:** unverified.

## Proposed design

1. **One internal event model.** good-cop already normalises hook payloads into events (`hook.normalise`). Add a per-harness *input adapter* in front of it and a per-harness *output adapter* after `rules.evaluate`: `good-cop hook --harness codex|cursor|copilot|claude`.
2. **Tool-name alias table** (`Shell→Bash`, `apply_patch→Edit`, `view→Read`, …) applied at normalisation, so rules and ledger extractors stay harness-agnostic. Record the original name too.
3. **Decision degradation.** Where `ask` isn't supported, choose `deny`-with-reason or `allow`-and-log per config. Default to deny when enforcing.
4. **Fail mode per harness.** good-cop fails open by design. Copilot fails *closed* on crashes, so the hook must never crash there. It already swallows all exceptions, but that becomes load-bearing.
5. **Install targets.** `good-cop install --harness …` writes the right file (`.codex/hooks.json`, `.cursor/hooks.json`, `.github/hooks/good-cop.json`).
6. **Fixtures first.** As with Claude Code, capture real payloads from each harness into `tests/fixtures/<harness>/` before writing its adapter. Most "unverified" cells above get answered by one capture run.

**Suggested order:** Codex (least translation) → Cursor (Claude-compat, then native) → Copilot (one file reaches CLI, cloud and VS Code) → OpenCode (TS plugin) → Antigravity.

## Harness-independent backstops

These don't replace hooks, but they cover what hooks can't. There is no shared hook standard; compatibility reads are doing the portability work [20].

| backstop | covers | misses |
|---|---|---|
| MCP proxy (good-cop between agent and each MCP server) | every MCP call in every harness, with results | built-in shell and edit tools |
| Shell shim (wrapper first on `PATH` / replaced `SHELL`) | every shell command | absolute-path bypass, no session context, no edits, can't ask |
| OS sandbox (e.g. Anthropic's `sandbox-runtime`: Seatbelt / bubblewrap + network proxy) [21] | a real filesystem and network boundary | coarse (paths and domains), no per-call intent or explanation |

A sandbox underneath and good-cop's contextual judgement on top is the layering [use-cases.md](use-cases.md) argues for.

## Sources
1. https://blog.jetbrains.com/research/2026/08/ai-coding-agent-adoption-2026/
2. https://newsletter.pragmaticengineer.com/p/ai-tooling-2026
3. https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
4. https://code.claude.com/docs/en/hooks
5. https://docs.github.com/en/copilot/reference/hooks-configuration
6. https://docs.github.com/en/copilot/reference/hooks-reference
7. https://github.com/microsoft/vscode-docs/blob/main/docs/agent-customization/hooks.md
8. https://developers.openai.com/codex/hooks
9. https://github.com/openai/codex/issues/23411
10. https://github.com/openai/codex/issues/18491
11. https://cursor.com/docs/agent/hooks
12. https://cursor.com/docs/reference/third-party-hooks
13. https://opencode.ai/docs/plugins/
14. https://raw.githubusercontent.com/sst/opencode/dev/packages/plugin/src/index.ts
15. https://github.com/sst/opencode/issues/2319
16. https://antigravity.google/docs/hooks/
17. https://medium.com/google-cloud/a-developers-guide-to-agent-hooks-in-antigravity-cli-4c1440febd11 (third party)
18. https://docs.devin.ai/desktop/cascade/hooks
19. https://docs.cline.bot/customization/hooks
20. https://codylindley.github.io/ai-harness-engineering-compatibility-matrix/ (third party)
21. https://github.com/anthropic-experimental/sandbox-runtime
