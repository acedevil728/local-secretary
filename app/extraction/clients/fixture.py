"""FixtureMock: 섹션 원문 → 기대 JSON 표에서 찾아 돌려준다(평가셋 재사용).

표에 없는 문장은 '규칙 없음'으로 답한다. 단위 테스트와 CI에서 쓴다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..schema import ExtractedItem, ExtractionResult, LLMResponse, SectionInput
from .base import local_probe


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_cases(directory: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        cases.extend(data if isinstance(data, list) else [data])
    return cases


class FixtureMock:
    name = "fixture"

    def __init__(self, directory: Path) -> None:
        self._table: dict[str, ExtractionResult] = {}
        for case in load_cases(directory) if directory.exists() else []:
            self._table[_key(case["text"])] = ExtractionResult.model_validate(case["expected"])

    def add(self, text: str, expected: dict[str, Any] | ExtractionResult) -> None:
        self._table[_key(text)] = (
            expected if isinstance(expected, ExtractionResult) else ExtractionResult.model_validate(expected)
        )

    def health(self) -> bool:
        return True

    def model_ids(self) -> list[str]:
        return ["fixture"]

    def active_endpoint(self) -> str | None:
        return None

    def probe(self) -> list[dict]:
        return local_probe("fixture")

    def extract(self, section: SectionInput) -> LLMResponse:
        found = self._table.get(_key(section.text))
        if found is None:
            found = ExtractionResult(items=[ExtractedItem(title=section.heading, rule=None, confidence=0.0)])
        return LLMResponse(result=found.model_copy(deep=True), model="fixture")
