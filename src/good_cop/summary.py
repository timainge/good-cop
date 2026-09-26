"""Optional rolling summary: trigger, detached worker, prompt + validation. See plan.md §4."""


def worker(session_id: str) -> int:
    raise NotImplementedError  # M5
