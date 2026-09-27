#!/usr/bin/env bash
# good-cop on_trip handler: one JSON line per trip to syslog (macOS unified log / journald / rsyslog),
# where a log forwarder or SIEM agent can pick it up. Needs: jq.
#   handlers:
#     syslog: {type: command, command: "~/.good-cop/handlers/syslog.sh"}
# Without jq, `command: "logger -t good-cop"` also works: it logs the raw JSON event.
set -euo pipefail
jq -c '{event: "good-cop.trip", action, enforced, rules: [.tripped[].id], tool, harness, session_id, seq, cwd}' |
  logger -t good-cop -p auth.warning
