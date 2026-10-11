"""LLM 입력·출력 스키마.

LLM 출력은 일부러 느슨하게 받는다(카테고리 오타 하나로 전체가 버려지지 않게). 실제 판정은
validate.py가 코드로 한다.

출력 모양은 두 가지를 받는다.
- v2 (프롬프트가 지금 요구하는 모양, `LLMOutput`): 섹션 하나에 항목 하나. 규칙은 `kind` + 단순한 칸
  (every/unit, day_of_month, weekdays, month, date, holiday_shift). RRULE 문자열은 코드가 만든다.
  작은 모델(4B급)이 RRULE을 틀리게 쓰고, 선택 칸을 빼먹는 문제 때문에 바꿨다.
- v1 (`items[]`, rule.type + rrule): 평가셋 기대값과 RuleMock이 쓰는 모양.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

CATEGORIES = ("routine", "bill", "loan", "saving", "renewal", "health", "other")
IMPORTANCES = ("high", "normal", "low")
RULE_KINDS = ("interval", "monthly", "weekly", "yearly", "once", "learned", "none")
WEEKDAY_CODES = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# LLM에는 한글 요일을 받는다. 4B 모델이 TU/TH 같은 영문 약자를 자주 헷갈렸다(실측).
WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")
UNITS = ("day", "week", "month", "year")


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
    # v2: LLM이 쓰는 칸
    kind: Literal["interval", "monthly", "weekly", "yearly", "once", "learned", "none"] | None = None
    day_of_month: int | None = None
    weekdays: list[str] = Field(default_factory=list)
    month: int | None = None
    holiday_shift: bool | None = None
    # v1·공통: 평가셋·RuleMock이 쓰는 칸 (every/unit/date는 v2도 같이 쓴다)
    type: Literal["interval", "calendar", "learned", "once"] | None = None
    every: int | None = None
    unit: Literal["day", "week", "month", "year"] | None = None
    anchor: str | None = None
    rrule: str | None = None
    adjust: Literal["none", "next_business_day"] | None = None
    date: str | None = None

    @field_validator("weekdays", mode="before")
    @classmethod
    def _weekdays(cls, v: Any) -> list[str]:
        """한글 요일("화", "화요일")과 영문 약자("TU") 모두 받아 영문 약자로 맞춘다."""
        if not v:
            return []
        if isinstance(v, str):
            v = re.split(r"[,\s·/]+", v)
        out = []
        for x in v:
            s = str(x).strip()
            if s[:1] in WEEKDAY_KO:
                out.append(WEEKDAY_CODES[WEEKDAY_KO.index(s[:1])])
            elif s:
                out.append(s.upper()[:2])
        return out


def _to_int(v: Any) -> int | None:
    """금액처럼 숫자여야 하는 칸. "230,000" 같은 문자열도 받고, 못 읽으면 None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    digits = re.sub(r"[,\s원]", "", str(v))
    return int(digits) if digits.isdigit() else None


class ExtractedItem(BaseModel):
    title: str = ""
    category: str = "other"
    rule: LLMRule | None = None
    events_in_text: list[str] = Field(default_factory=list)
    amount: int | None = None
    importance: str | None = None  # 없으면 분류로 정한다(공과금·대출·저축 = high)
    lead_days: int | None = None  # 없으면 규칙으로 정한다
    window_days: int | None = None
    source_quote: str = ""
    confidence: float | None = None  # 없으면 코드가 정한다(검증·근거 확인을 통과하면 0.9)
    ambiguities: list[str] = Field(default_factory=list)

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> int | None:
        return _to_int(v)


class ExtractionResult(BaseModel):
    items: list[ExtractedItem] = Field(default_factory=list)


class LLMOutput(BaseModel):
    """프롬프트 v2의 응답 한 개."""

    source_quote: str = ""
    rule: LLMRule | None = None
    done_dates: list[str] = Field(default_factory=list)
    amount: int | None = None
    category: str = "other"

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v: Any) -> int | None:
        return _to_int(v)

    def to_result(self) -> ExtractionResult:
        rule = None if self.rule is None or self.rule.kind in (None, "none") else self.rule
        return ExtractionResult(
            items=[
                ExtractedItem(
                    category=self.category,
                    rule=rule,
                    events_in_text=list(self.done_dates),
                    amount=self.amount,
                    source_quote=self.source_quote,
                )
            ]
        )


class LLMResponse(BaseModel):
    result: ExtractionResult
    model: str
    raw: str | None = None


def ollama_format_schema() -> dict[str, Any]:
    """Ollama 구조화 출력(format)에 넘기는 JSON 스키마(v2).

    - 모든 칸을 required로 둔다. 선택 칸으로 두면 작은 모델이 every/unit 같은 핵심 칸을 빼먹는다.
    - source_quote를 맨 앞에 둔다. 근거 문장을 먼저 쓰게 해서 규칙이 문장에 붙어 있게 한다.
    """
    nullable_int = {"type": ["integer", "null"]}
    return {
        "type": "object",
        "properties": {
            "source_quote": {"type": "string"},
            "rule": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(RULE_KINDS)},
                    "every": nullable_int,
                    "unit": {"type": ["string", "null"], "enum": [*UNITS, None]},
                    "day_of_month": nullable_int,
                    "weekdays": {"type": "array", "items": {"type": "string", "enum": list(WEEKDAY_KO)}},
                    "month": nullable_int,
                    "date": {"type": ["string", "null"]},
                    "holiday_shift": {"type": "boolean"},
                },
                "required": ["kind", "every", "unit", "day_of_month", "weekdays", "month", "date", "holiday_shift"],
            },
            "done_dates": {"type": "array", "items": {"type": "string"}},
            "amount": nullable_int,
            "category": {"type": "string", "enum": list(CATEGORIES)},
        },
        "required": ["source_quote", "rule", "done_dates", "amount", "category"],
    }
