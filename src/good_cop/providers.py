"""The one model seam: LLM protocol with anthropic / openai / ollama over httpx. See plan.md §6."""

from typing import Protocol


class LLM(Protocol):
    name: str

    def complete(self, system: str, user: str, *, timeout: float) -> str: ...


def make_llm(cfg: dict) -> LLM:
    raise NotImplementedError  # M3
