"""Live hook entry: dispatch on hook_event_name, time-boxed, fail open. See plan.md §1."""

import json
import sys
import traceback

from good_cop import store


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        handle(payload)
    except Exception:
        store.log_error(traceback.format_exc())
    return 0  # never break Claude Code


def handle(payload: dict) -> None:
    # TODO(M1): normalise and append event; dispatch per hook_event_name.
    pass
