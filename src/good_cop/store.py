"""Paths, per-session seq, locked append, atomic writes. See plan.md §2."""

import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("GOOD_COP_HOME", Path.home() / ".good-cop"))


def session_dir(session_id: str) -> Path:
    return ROOT / "sessions" / session_id


def log_error(msg: str) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(ROOT / "errors.log", "a") as f:
            f.write(f"--- {datetime.now(timezone.utc).isoformat()}\n{msg}\n")
    except Exception:
        pass


def append_event(session_id: str, event: dict) -> dict:
    """Assign seq under flock, append one JSON line, return the event."""
    raise NotImplementedError  # M1


def read_events(session_id: str) -> list[dict]:
    raise NotImplementedError  # M1


def write_json_atomic(path: Path, data: dict) -> None:
    raise NotImplementedError  # M1
