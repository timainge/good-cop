"""Deterministic ledger: fold/rebuild plus per-tool extractors. See plan.md §3."""


def empty() -> dict:
    return {
        "env": {},
        "files_written": {},
        "commands": {"count": 0, "last": []},
        "hosts_contacted": [],
        "context_changes": [],
        "flags": {},
        "last_event_seq": 0,
    }


def fold(ledger: dict, event: dict) -> dict:
    raise NotImplementedError  # M2


def rebuild(events: list[dict]) -> dict:
    ledger = empty()
    for e in events:
        ledger = fold(ledger, e)
    return ledger
