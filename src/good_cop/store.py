"""Paths, per-session seq, locked append, atomic writes. See plan.md §2."""

import fcntl
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ.get("GOOD_COP_HOME", Path.home() / ".good-cop"))

MAX_FIELD = 8192


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def session_dir(session_id: str) -> Path:
    return ROOT / "sessions" / session_id


def log_error(msg: str) -> None:
    try:
        ROOT.mkdir(parents=True, exist_ok=True)
        with open(ROOT / "errors.log", "a") as f:
            f.write(f"--- {now()}\n{msg}\n")
    except Exception:
        pass


def truncate(obj, limit: int = MAX_FIELD):
    """Recursively truncate long strings, leaving a marker with the original size."""
    if isinstance(obj, str):
        if len(obj) <= limit:
            return obj
        return obj[:limit] + f"…[truncated {len(obj) - limit:,} bytes]"
    if isinstance(obj, dict):
        return {k: truncate(v, limit) for k, v in obj.items()}
    if isinstance(obj, list):
        return [truncate(v, limit) for v in obj]
    return obj


@contextmanager
def locked(session_id: str):
    d = session_dir(session_id)
    d.mkdir(parents=True, exist_ok=True)
    with open(d / ".lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def append_event(session_id: str, event: dict) -> dict:
    """Assign seq under flock, append one JSON line, return the event."""
    with locked(session_id) as d:
        seq_file = d / "seq"
        seq = int(seq_file.read_text() or 0) + 1 if seq_file.exists() else 1
        seq_file.write_text(str(seq))
        event = {"seq": seq, "ts": event.get("ts") or now(), "session_id": session_id, **event}
        append_jsonl(d / "events.jsonl", event)
    return event


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(record, default=str) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def read_events(session_id: str) -> list[dict]:
    return read_jsonl(session_dir(session_id) / "events.jsonl")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, default=str))
    os.replace(tmp, path)


def list_sessions() -> list[str]:
    """Session ids, oldest first by last event write."""
    base = ROOT / "sessions"
    if not base.exists():
        return []
    ds = [d for d in base.iterdir() if (d / "events.jsonl").exists()]
    return [d.name for d in sorted(ds, key=lambda d: (d / "events.jsonl").stat().st_mtime)]


def resolve_session(session: str | None) -> str | None:
    """Accept a full id, a unique prefix, or None for the latest session."""
    sessions = list_sessions()
    if not session:
        return sessions[-1] if sessions else None
    matches = [s for s in sessions if s.startswith(session)]
    return matches[0] if len(matches) == 1 else (session if session in sessions else None)
