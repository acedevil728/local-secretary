"""규칙 타입. `rule_json`과 추출 스키마가 같은 모양을 쓴다."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, TypeAdapter

Unit = Literal["day", "week", "month", "year"]


class IntervalRule(BaseModel):
    """마지막 이력 + 간격. 이력이 없으면 시작일 + 간격."""

    type: Literal["interval"] = "interval"
    every: int = Field(ge=1)
    unit: Unit
    anchor: Literal["last_event"] = "last_event"


class CalendarRule(BaseModel):
    """달력 고정형. iCalendar RRULE(RFC 5545)로 표현한다. 예: FREQ=MONTHLY;BYMONTHDAY=-1"""

    type: Literal["calendar"] = "calendar"
    rrule: str
    adjust: Literal["none", "next_business_day"] = "none"


class LearnedRule(BaseModel):
    """주기는 안 적고 이력만 있음. 이력 간격의 중앙값으로 다음 날을 정한다."""

    type: Literal["learned"] = "learned"


class OnceRule(BaseModel):
    """지정일 1회. 완료되면 끝."""

    type: Literal["once"] = "once"
    date: dt.date


Rule = Annotated[Union[IntervalRule, CalendarRule, LearnedRule, OnceRule], Field(discriminator="type")]
_ADAPTER: TypeAdapter[Any] = TypeAdapter(Rule)


def parse_rule(data: Any) -> IntervalRule | CalendarRule | LearnedRule | OnceRule:
    return _ADAPTER.validate_python(data)


def dump_rule(rule: BaseModel) -> dict[str, Any]:
    return rule.model_dump(mode="json")


UNIT_DAYS: dict[str, float] = {"day": 1, "week": 7, "month": 30.4375, "year": 365.25}


def interval_days(rule: IntervalRule) -> float:
    return rule.every * UNIT_DAYS[rule.unit]


# ---- RRULE 조립 도우미 (한국어 표현 → RRULE) ----

BYDAY = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]  # Python weekday() 순서


def monthly_rrule(day: int, interval: int = 1) -> str:
    """매달 n일. 31일·말일은 BYMONTHDAY=-1, 29·30일은 짧은 달에 말일로 당긴다."""
    prefix = "FREQ=MONTHLY" + (f";INTERVAL={interval}" if interval > 1 else "")
    if day == -1 or day >= 31:
        return f"{prefix};BYMONTHDAY=-1"
    if day in (29, 30):
        return f"{prefix};BYMONTHDAY={day},-1;BYSETPOS=1"
    return f"{prefix};BYMONTHDAY={day}"


def weekly_rrule(weekdays: list[int], interval: int = 1) -> str:
    days = ",".join(BYDAY[w] for w in sorted(set(weekdays)))
    return "FREQ=WEEKLY" + (f";INTERVAL={interval}" if interval > 1 else "") + f";BYDAY={days}"


def yearly_rrule(month: int, day: int) -> str:
    if day >= 29:
        return f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day},-1;BYSETPOS=1"
    return f"FREQ=YEARLY;BYMONTH={month};BYMONTHDAY={day}"
