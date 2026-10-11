"""LLMClient 구현들. `LLM_MODE=ollama | fixture | rule | replay | record`로 고른다."""

from __future__ import annotations

from ...core.config import Settings
from .base import BadLLMOutput, LLMClient, LLMUnavailable


def make_client(settings: Settings) -> LLMClient:
    mode = settings.llm_mode
    if mode == "rule":
        from .rule import RuleMock

        return RuleMock()
    if mode == "fixture":
        from .fixture import FixtureMock

        return FixtureMock(settings.fixtures_dir)
    if mode in ("ollama", "record", "replay"):
        from .ollama import OllamaClient

        ollama = OllamaClient.from_settings(settings)
        if mode == "ollama":
            return ollama
        from .replay import ReplayClient

        return ReplayClient(settings.cassettes_dir, record_with=ollama if mode == "record" else None)
    raise ValueError(f"알 수 없는 LLM_MODE: {mode}")


__all__ = ["LLMClient", "LLMUnavailable", "BadLLMOutput", "make_client"]
