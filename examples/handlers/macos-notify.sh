#!/usr/bin/env bash
# good-cop on_trip handler: a macOS notification. Uses only environment variables, no jq needed.
#   handlers:
#     notify: {type: command, command: "~/.good-cop/handlers/macos-notify.sh", only: [ask, deny]}
osascript -e "display notification \"${GOOD_COP_RULES} on ${GOOD_COP_TOOL}\" with title \"good-cop: ${GOOD_COP_ACTION}\""
