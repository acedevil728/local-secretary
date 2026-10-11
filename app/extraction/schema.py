"""LLM 입력·출력 스키마.

LLM 출력은 일부러 느슨하게 받는다(카테고리 오타 하나로 전체가 버려지지 않게). 실제 판정은
validate.py가 코드로 한다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

CATEGORIES = ("routine", "bill", "loan", "saving", "renewal", "health", "other")
IMPORTANCES = ("high", "normal", "low")


class SectionInput(BaseModel):
    heading: str
    text: str
    today: dt.date
    timezone: str = "Asia/Seoul"
    saved_at: dt.datetime | None = None
    history_dates: list[dt.date] = Field(default_factory=list)
    existing: dict[str, Any] | None = None  # 기존 항목(rule, category, amount, ...)

    def cache_payload(self) -> dict[str, Any]:
        """캐시 키에 들어가는 부분. 날짜 계산은 LLM이 하지 않으므로 '오늘'은 넣지 않는다."""
        return {"heading": self.heading, "text": self.text, "existing": self.existing}


class LLMRule(BaseModel):
    type: Literal["interval", "calendar", "learned", "once"]
    every: int | None = None
    unit: Literal["day", "week", "month", "year"] | None = None
    anchor: str | None = None
    rrule: str | None = None
    adjust: Literal["none", "next_business_day"] | None = None
    date: str | None = None


class ExtractedItem(BaseModel):
    title: str = ""
    category: str = "other"
    rule: LLMRule | None = None
    events_in_text: list[str] = Field(default_factory=list)
    amount: int | None = None
    importance: str = "normal"
    lead_days: int | None = None
    window_days: int | None = None
    source_quote: str = ""
    confidence: float = 0.0
    ambiguities: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)


class LLMResponse(BaseModel):
    result: ExtractionResult
    model: str
    raw: str | None = None


def ollama_format_schema() -> dict[str, Any]:
    """Ollama 구조화 출력(format)에 넘기는 JSON 스키마. 작은 모델도 따르기 쉽게 평평하게 둔다."""
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "category": {"type": "string", "enum": list(CATEGORIES)},
                        "rule": {
                            "type": ["object", "null"],
                            "properties": {
                                "type": {"type": "string", "enum": ["interval", "calendar", "learned", "once"]},
                                "every": nullable_int,
                                "unit": {"type": ["string", "null"], "enum": ["day", "week", "month", "year", None]},
                                "anchor": {"type": ["string", "null"]},
                                "rrule": {"type": ["string", "null"]},
                                "adjust": {"type": ["string", "null"], "enum": ["none", "next_business_day", None]},
                                "date": {"type": ["string", "null"]},
                            },
                            "required": ["type"],
                        },
                        "events_in_text": {"type": "array", "items": {"type": "string"}},
                        "amount": nullable_int,
                        "importance": {"type": "string", "enum": list(IMPORTANCES)},
                        "lead_days": nullable_int,
                        "window_days": nullable_int,
                        "source_quote": {"type": "string"},
                        "confidence": {"type": "number"},
                        "ambiguities": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["title", "category", "rule", "events_in_text", "source_quote", "confidence"],
                },
            }
        },
        "required": ["items"],
    }
