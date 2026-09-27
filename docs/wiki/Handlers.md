# Handlers: do something when a rule trips

A rule's `action` (`log`, `ask`, `deny`) is what the **agent** sees. **Handlers** are side effects for **you**: post to Slack, write to syslog or a SIEM, pop a desktop notification. They're registered once by name and referenced from rules. The only handler type today is `command`: a shell command that receives the event as JSON on stdin. The integration logic lives in your script, not in good-cop.

```yaml
# ~/.good-cop/rules.yaml
handlers:
  slack:  {type: command, command: "~/.good-cop/handlers/slack.sh", only: [ask, deny], once_per_session: true}
  syslog: {type: command, command: "~/.good-cop/handlers/syslog.sh", timeout: 5}

defaults: {threshold: 0.6, action: ask, on_trip: [syslog]}   # every tripped rule, unless it says otherwise

rules:
  - id: prod_target
    question: Does this tool call deploy to or run commands against production?
    on_trip: [slack, syslog]                                  # replaces the default list
```

| handler option | meaning |
|---|---|
| `type` | `command` (more types may come later; rules won't need to change) |
| `command` | run with `sh -c`; `~` is expanded; inherits the agent's environment (e.g. `SLACK_WEBHOOK_URL`) |
| `timeout` | seconds, default 10; the handler is killed after that |
| `only` | fire only when the tripped rule's action is in this list, e.g. `[ask, deny]` |
| `once_per_session` | fire at most once per rule per agent session, so a looping agent doesn't spam you |

## What the command receives

JSON on stdin. It's compact and **redacted** (secret formats and secret-named env var values are masked), never the full decision state:

```json
{"ts": "…", "session_id": "…", "seq": 42, "harness": "claude", "cwd": "/home/me/project",
 "tool": "Bash", "input": {"command": "kubectl --context prod apply -f deploy.yaml"}, "agent_id": null,
 "action": "ask", "enforced": "ask", "enforce": true,
 "tripped": [{"id": "prod_target", "p": 0.97, "source": "model", "action": "ask"}],
 "provider": "jev:jev-latest"}
```

For simple scripts, the same facts are also in environment variables: `GOOD_COP_HANDLER`, `GOOD_COP_ACTION`, `GOOD_COP_RULES` (comma-separated), `GOOD_COP_TOOL`, `GOOD_COP_SESSION`.

`action` is what the rules decided. `enforced` is what was actually sent to the agent, which is `allow` in log-only mode. Handlers fire in log-only mode too, so you can be alerted without blocking anything.

## Examples

Copy from [`examples/handlers/`](https://github.com/timainge/good-cop/tree/main/examples/handlers) into `~/.good-cop/handlers/` and `chmod +x`.

**Slack** (needs `curl`, `jq`, and `SLACK_WEBHOOK_URL` from a [Slack incoming webhook](https://api.slack.com/messaging/webhooks)):
```bash
jq '{text: (":rotating_light: *good-cop \(.action)* in `\(.cwd | split("/") | last)`\n"
      + "*Rules:* " + ([.tripped[] | "\(.id) (p=\(.p))"] | join(", ")) + "\n"
      + "*Tool:* `\(.tool)` " + ((.input.command // (.input | tostring))[:300] | "```\(.)```"))}' |
  curl -sS --max-time 8 -X POST -H 'Content-Type: application/json' --data @- "$SLACK_WEBHOOK_URL"
```

**syslog / SIEM**: one JSON line per trip, which your log forwarder can ship:
```bash
jq -c '{event: "good-cop.trip", action, enforced, rules: [.tripped[].id], tool, harness, session_id, seq, cwd}' |
  logger -t good-cop -p auth.warning
```
Or, with no script at all: `command: "logger -t good-cop"` logs the raw event.

**macOS notification** (no jq):
```bash
osascript -e "display notification \"${GOOD_COP_RULES} on ${GOOD_COP_TOOL}\" with title \"good-cop: ${GOOD_COP_ACTION}\""
```

Any other webhook (Teams, Discord, PagerDuty, a logging API) is the same pattern: reshape with `jq` and `curl` it.

## Test a handler

```sh
uv run good-cop handler slack --test     # sends a sample event; errors go to ~/.good-cop/errors.log
```

## How it behaves

- **No added latency.** Handlers start detached after the decision is recorded. The tool call doesn't wait for Slack.
- **Fails open.** A failing, slow or missing handler never affects the agent. Non-zero exits and timeouts are logged to `~/.good-cop/errors.log`.
- **Audited.** Each firing is appended to the session's `handlers.jsonl`, and each decision records which handlers it triggered.
- **Backtest is a dry run.** `good-cop backtest` reports which handlers *would* have fired (e.g. `slack x3`) and runs none.
- **Trust.** Commands come from your own rules file, the same trust level as the hook itself. Anything that can edit `~/.good-cop/rules.yaml` could already edit the hook config.
