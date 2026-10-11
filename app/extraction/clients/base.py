from __future__ import annotations

from typing import Protocol

from ..schema import LLMResponse, SectionInput


class LLMUnavailable(RuntimeError):
    """응답하는 LLM 노드가 없다. 분석은 대기열에서 기다렸다가 다시 이어진다."""


class BadLLMOutput(ValueError):
    """JSON이 아니거나 스키마에 맞지 않는 응답. 검증 실패로 처리한다."""


class LLMClient(Protocol):
    name: str

    def health(self) -> bool: ...

    def model_ids(self) -> list[str]:
        """이 클라이언트가 답할 수 있는 모델 이름들(캐시 조회용)."""
        ...

    def active_endpoint(self) -> str | None: ...

    def probe(self) -> list[dict]:
        """노드별 상태(화면의 LLM 불). [{url, model, reachable, has_model, error}]"""
        ...

    def extract(self, section: SectionInput) -> LLMResponse: ...


def local_probe(model: str) -> list[dict]:
    """네트워크 없이 도는 클라이언트(mock)용."""
    return [{"url": None, "model": model, "reachable": True, "has_model": True, "error": None}]
