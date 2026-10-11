"""LLM 출력 검증(코드). 통과한 것만 DB에 반영한다.

스키마 검사, 날짜 파싱, 간격 상식 범위(1일~5년), source_quote가 원문에 실제로 있는지 확인한다.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any

from dateutil.rrule import rrulestr

from ..scheduling.rules import (
    CalendarRule,
    IntervalRule,
    LearnedRule,
    OnceRule,
    dump_rule,
    interval_days,
    parse_rule,
)
from .schema import CATEGORIES, IMPORTANCES, ExtractionResult, LLMRule

EngineRule = IntervalRule | CalendarRule | LearnedRule | OnceRule

MIN_INTERVAL_DAYS = 1
MAX_INTERVAL_DAYS = 5 * 366


@dataclass
class Proposal:
    title: str
    category: str
    rule: EngineRule
    events: list[dt.date]
    amount: int | None
    importance: str
    lead_days: int
    window_days: int
    source_quote: str
    confidence: float
    ambiguities: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "category": self.category,
            "rule": dump_rule(self.rule),
            "events_in_text": [d.isoformat() for d in self.events],
            "amount": self.amount,
            "importance": self.importance,
            "lead_days": self.lead_days,
            "window_days": self.window_days,
            "source_quote": self.source_quote,
            "confidence": self.confidence,
            "ambiguities": list(self.ambiguities),
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> "Proposal":
        return Proposal(
            title=data.get("title") or "",
            category=data.get("category") or "other",
            rule=parse_rule(data["rule"]),
            events=[dt.date.fromisoformat(d) for d in data.get("events_in_text") or []],
            amount=data.get("amount"),
            importance=data.get("importance") or "normal",
            lead_days=int(data.get("lead_days") or 0),
            window_days=int(data.get("window_days") or 0),
            source_quote=data.get("source_quote") or "",
            confidence=float(data.get("confidence") or 0),
            ambiguities=list(data.get("ambiguities") or []),
        )


@dataclass
class Validated:
    proposal: Proposal | None  # None = 규칙 없음
    errors: list[str] = field(default_factory=list)
    ambiguities: list[str] = field(default_factory=list)
    confidence: float = 0.0
    quote: str = ""


def _squash(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _to_engine_rule(r: LLMRule, errors: list[str]) -> EngineRule | None:
    try:
        if r.type == "interval":
            if not r.every or not r.unit:
                errors.append("interval 규칙에 every/unit이 없어요")
                return None
            rule = IntervalRule(every=r.every, unit=r.unit)
            days = interval_days(rule)
            if not (MIN_INTERVAL_DAYS <= days <= MAX_INTERVAL_DAYS):
                errors.append(f"간격 {days:.0f}일은 상식 범위(1일~5년)를 벗어나요")
                return None
            return rule
        if r.type == "calendar":
            if not r.rrule:
                errors.append("calendar 규칙에 rrule이 없어요")
                return None
            text = r.rrule.strip()
            if text.upper().startswith("RRULE:"):
                text = text[6:]
            if "DTSTART" in text.upper():
                errors.append("rrule에 DTSTART를 넣으면 안 돼요")
                return None
            start = dt.datetime(2000, 1, 1)
            nxt = rrulestr(text, dtstart=start, ignoretz=True).after(start, inc=True)
            if nxt is None or nxt.date() > dt.date(2000 + 5, 12, 31):
                errors.append("rrule이 5년 안에 날짜를 만들지 않아요")
                return None
            return CalendarRule(rrule=text.upper(), adjust=r.adjust or "none")
        if r.type == "learned":
            return LearnedRule()
        if r.type == "once":
            if not r.date:
                errors.append("once 규칙에 date가 없어요")
                return None
            return OnceRule(date=dt.date.fromisoformat(r.date))
    except (ValueError, TypeError) as exc:
        errors.append(f"규칙을 읽지 못했어요: {exc}")
    return None


def _clamp(v: int | None, default: int, lo: int = 0, hi: int = 60) -> int:
    if v is None:
        return default
    return max(lo, min(hi, int(v)))


def validate(result: ExtractionResult, *, heading: str, text: str, today: dt.date) -> Validated:
    if not result.items:
        return Validated(None, confidence=0.0)
    item = result.items[0]
    errors: list[str] = []
    ambiguities = [a for a in item.ambiguities if a]
    if len(result.items) > 1:
        ambiguities.append("한 섹션에서 항목을 여러 개 읽었어요. 섹션을 나눠 주세요.")
    confidence = max(0.0, min(1.0, float(item.confidence)))

    if item.rule is None:
        return Validated(None, errors, ambiguities, confidence, item.source_quote)

    quote = item.source_quote.strip()
    if not quote:
        errors.append("근거 문장(source_quote)이 비어 있어요")
    elif _squash(quote) not in _squash(text) and _squash(quote) not in _squash(heading):
        errors.append("근거 문장이 원문에 없어요")

    rule = _to_engine_rule(item.rule, errors)

    events: list[dt.date] = []
    for raw in item.events_in_text:
        try:
            d = dt.date.fromisoformat(raw)
        except ValueError:
            errors.append(f"이력 날짜 '{raw}'를 읽지 못했어요")
            continue
        if d > today:
            ambiguities.append(f"{raw}은(는) 아직 오지 않은 날이라 이력으로 넣지 않았어요")
            continue
        if d < today - dt.timedelta(days=3660):
            continue
        events.append(d)

    if errors or rule is None:
        return Validated(None, errors or ["규칙을 만들지 못했어요"], ambiguities, confidence, quote)

    category = item.category if item.category in CATEGORIES else "other"
    importance = item.importance if item.importance in IMPORTANCES else "normal"
    if category in ("bill", "loan", "saving") and item.importance not in IMPORTANCES:
        importance = "high"
    amount = item.amount if item.amount is None or item.amount >= 0 else None

    default_window = 0
    if isinstance(rule, IntervalRule):
        default_window = {"day": 1, "week": 3, "month": 7, "year": 14}[rule.unit]
    proposal = Proposal(
        title=heading,
        category=category,
        rule=rule,
        events=sorted(set(events)),
        amount=amount,
        importance=importance,
        lead_days=_clamp(item.lead_days, 3),
        window_days=_clamp(item.window_days, default_window),
        source_quote=quote,
        confidence=confidence,
        ambiguities=ambiguities,
    )
    return Validated(proposal, [], ambiguities, confidence, quote)


def rules_equal(a: dict[str, Any] | None, b: dict[str, Any] | None) -> bool:
    if a is None or b is None:
        return a is b

    def norm(r: dict[str, Any]) -> dict[str, Any]:
        r = dict(r)
        if r.get("type") == "calendar" and r.get("rrule"):
            r["rrule"] = ";".join(sorted(p.strip().upper() for p in r["rrule"].split(";") if p.strip()))
        r.pop("anchor", None)
        return r

    return norm(a) == norm(b)
