#!/usr/bin/env bash
# good-cop on_trip handler: post a message to a Slack incoming webhook.
# Needs: curl, jq, and SLACK_WEBHOOK_URL in the environment the agent (and so the hook) runs in.
#   handlers:
#     slack: {type: command, command: "~/.good-cop/handlers/slack.sh", only: [ask, deny], once_per_session: true}
set -euo pipefail
: "${SLACK_WEBHOOK_URL:?set SLACK_WEBHOOK_URL}"
jq '{text: (
      ":rotating_light: *good-cop \(.action)*" + (if .enforce then "" else " _(log only)_" end)
      + " in `\(.cwd | split("/") | last)` (\(.harness))\n"
      + "*Rules:* " + ([.tripped[] | "\(.id) (p=\(.p))"] | join(", ")) + "\n"
      + "*Tool:* `\(.tool)` " + ((.input.command // (.input | tostring))[:300] | "```\(.)```")
    )}' | curl -sS --max-time 8 -X POST -H 'Content-Type: application/json' --data @- "$SLACK_WEBHOOK_URL" >/dev/null
