"""LLM 출력 검증(코드). 통과한 것만 DB에 반영한다.

- 형식: 스키마, 날짜 파싱, 간격 상식 범위(1일~5년), RRULE 해석
- 근거: 규칙의 숫자·요일·날짜가 원문에 실제로 있는지(작은 모델의 지어내기를 잡는다). 없으면 '확인 필요'
- 이력: 원문에 적힌 날짜(또는 어제·오늘·그제)만 이력으로 받는다. 지어낸 날짜는 버린다
- 근거 문장(source_quote)이 원문에 없으면 본문 전체를 근거로 두고 '확인 필요'로 보낸다
- 알림 시점·허용 구간·중요도를 LLM이 주지 않으면 규칙과 분류로 정한다
- 코드가 확실하게 읽는 것은 코드가 이긴다(korean.py): 금액, 간격형의 지난 날짜, "주말이어도 그날"·"휴일이면" 같은 휴일 표현
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
    monthly_rrule,
    parse_rule,
    weekly_rrule,
    yearly_rrule,
)
from .korean import holiday_shift_hint, parse_amount, past_dates
from .schema import CATEGORIES, IMPORTANCES, WEEKDAY_CODES, ExtractionResult, LLMRule

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


def _interval(every: int | None, unit: str | None, errors: list[str]) -> IntervalRule | None:
    if not every or not unit:
        errors.append("interval 규칙에 every/unit이 없어요")
        return None
    rule = IntervalRule(every=every, unit=unit)
    days = interval_days(rule)
    if not (MIN_INTERVAL_DAYS <= days <= MAX_INTERVAL_DAYS):
        errors.append(f"간격 {days:.0f}일은 상식 범위(1일~5년)를 벗어나요")
        return None
    return rule


def _repeat(every: int | None) -> int:
    """격주·격월 같은 반복 배수. 작은 모델이 every에 날짜(25)를 넣는 실수를 막으려고 2~6만 받는다."""
    return every if every and 2 <= every <= 6 else 1


def _kind_to_engine_rule(r: LLMRule, errors: list[str]) -> EngineRule | None:
    """v2 출력(kind + 단순한 칸) → 엔진 규칙. RRULE은 여기서 만든다."""
    adjust = "next_business_day" if r.holiday_shift else "none"
    if r.kind == "interval" and r.weekdays:
        # "격주 토요일"을 interval(2주)+요일로 내는 경우(gemma3:4b 실측). 요일이 있으면 요일 규칙이다.
        r = r.model_copy(update={"kind": "weekly"})
    if r.kind == "interval":
        return _interval(r.every, r.unit, errors)
    if r.kind == "monthly":
        d = r.day_of_month
        if d is None or not (d == -1 or 1 <= d <= 31):
            errors.append("monthly 규칙의 day_of_month가 없거나 이상해요")
            return None
        return CalendarRule(rrule=monthly_rrule(d, _repeat(r.every)), adjust=adjust)
    if r.kind == "weekly":
        days = [WEEKDAY_CODES.index(c) for c in r.weekdays if c in WEEKDAY_CODES]
        if not days:
            errors.append("weekly 규칙에 요일이 없어요")
            return None
        return CalendarRule(rrule=weekly_rrule(days, _repeat(r.every)), adjust=adjust)
    if r.kind == "yearly":
        if not r.month or not (1 <= r.month <= 12) or not r.day_of_month or not (1 <= r.day_of_month <= 31):
            errors.append("yearly 규칙의 month/day_of_month가 없거나 이상해요")
            return None
        return CalendarRule(rrule=yearly_rrule(r.month, r.day_of_month), adjust=adjust)
    if r.kind == "once":
        if not r.date:
            errors.append("once 규칙에 date가 없어요")
            return None
        return OnceRule(date=dt.date.fromisoformat(r.date))
    if r.kind == "learned":
        return LearnedRule()
    errors.append(f"알 수 없는 kind: {r.kind}")
    return None


def _to_engine_rule(r: LLMRule, errors: list[str]) -> EngineRule | None:
    try:
        if r.kind is not None:
            return _kind_to_engine_rule(r, errors)
        if r.type == "interval":
            return _interval(r.every, r.unit, errors)
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


# ---- 근거 확인: 규칙의 값이 원문에 실제로 적혀 있는가 ----

UNIT_WORDS = {"day": r"일", "week": r"주", "month": r"(개월|달|월)", "year": r"년"}
UNIT_KO = {"day": "일", "week": "주", "month": "개월", "year": "년"}
EVERY_WORDS = {"day": r"매\s*일|하루", "week": r"매\s*주", "month": r"매\s*(달|월)", "year": r"매\s*년"}
OTHER_WORDS = {"day": "격일", "week": "격주", "month": "격월", "year": "격년"}
REPEAT_WORDS = {
    "MONTHLY": r"매\s*(달|월)|달마다|월마다|한\s*달에|격월|\d+\s*(개월|달)마다",
    "YEARLY": r"매\s*년|해마다|년마다|일\s*년에|1\s*년에",
}
WEEKDAY_KO = dict(zip(WEEKDAY_CODES, "월화수목금토일"))
RELATIVE_DAYS = (("오늘", 0), ("어제", 1), ("그저께", 2), ("그제", 2))


def _has_number(text: str, n: int, after: str) -> bool:
    """숫자 n 뒤에 단위가 붙어 있는가. 예: 5주, 6개월, 25일 (앞에 다른 숫자가 붙은 경우는 제외)."""
    return re.search(rf"(?<!\d){n}\s*{after}", text) is not None


def _weekday_in_text(code: str, text: str) -> bool:
    ch = WEEKDAY_KO[code]
    # "화요일", "화·목", "월, 수", "토/일" (10월의 '월' 같은 것은 빼려고 요일 표시나 구분자가 붙어 있어야 한다)
    return re.search(rf"{ch}\s*(요일|욜)|{ch}\s*[·,/、]|[·,/、]\s*{ch}(?!\d)", text) is not None


def _rrule_parts(rrule: str) -> dict[str, str]:
    parts = {}
    for p in rrule.split(";"):
        k, _, v = p.partition("=")
        parts[k.strip().upper()] = v.strip().upper()
    return parts


def grounding_issues(rule: EngineRule, text: str) -> list[str]:
    """규칙의 숫자·요일·날짜가 원문에 없으면 그 이유를 돌려준다(빈 목록 = 근거 있음)."""
    issues: list[str] = []
    if isinstance(rule, IntervalRule):
        e, u = rule.every, rule.unit
        ok = (
            _has_number(text, e, UNIT_WORDS[u])
            or (e == 1 and re.search(EVERY_WORDS[u], text) is not None)
            or (e == 2 and OTHER_WORDS[u] in text)
        )
        if not ok:
            issues.append(f"'{e}{UNIT_KO[u]}마다'가 문장에 보이지 않아요.")
    elif isinstance(rule, CalendarRule):
        p = _rrule_parts(rule.rrule)
        freq = p.get("FREQ")
        days = [d for d in p.get("BYMONTHDAY", "").split(",") if d]
        positive = [int(d) for d in days if not d.startswith("-")]
        # 반복을 뜻하는 말이 있어야 한다. "여권 11월 2일 만료"를 '매달 2일'로 읽은 실측 사례가 있다.
        if freq == "MONTHLY" and not re.search(REPEAT_WORDS["MONTHLY"], text):
            issues.append("'매달'처럼 반복을 뜻하는 말이 문장에 보이지 않아요.")
        if freq == "YEARLY" and not re.search(REPEAT_WORDS["YEARLY"], text):
            issues.append("'매년'처럼 반복을 뜻하는 말이 문장에 보이지 않아요.")
        if freq in ("MONTHLY", "YEARLY"):
            if positive and not _has_number(text, positive[0], "일"):
                issues.append(f"'{positive[0]}일'이 문장에 보이지 않아요.")
            elif not positive and days and not re.search(r"말일|마지막\s*날|31\s*일", text):
                issues.append("'말일'이 문장에 보이지 않아요.")
        if freq == "YEARLY" and p.get("BYMONTH") and not _has_number(text, int(p["BYMONTH"]), "월"):
            issues.append(f"'{p['BYMONTH']}월'이 문장에 보이지 않아요.")
        if freq == "WEEKLY":
            missing = [WEEKDAY_KO[c] for c in p.get("BYDAY", "").split(",") if c and c in WEEKDAY_KO and not _weekday_in_text(c, text)]
            if missing:
                issues.append(f"요일({'·'.join(missing)})이 문장에 보이지 않아요.")
        interval = int(p.get("INTERVAL", "1") or 1)
        if interval > 1 and "격" not in text and not re.search(rf"(?<!\d){interval}\s*(주|개월|달)", text):
            issues.append(f"'{interval}번에 한 번'이 문장에 보이지 않아요.")
    elif isinstance(rule, OnceRule):
        if not _date_in_text(rule.date, text):
            issues.append(f"날짜 {rule.date.month}/{rule.date.day}가 문장에 보이지 않아요.")
    return issues


def _date_in_text(d: dt.date, text: str) -> bool:
    if d.isoformat() in text:
        return True
    pattern = rf"(?<!\d){d.month}\s*월\s*{d.day}\s*일|(?<![\d/]){d.month}/{d.day}(?![\d/])"
    return re.search(pattern, text) is not None


def _event_grounded(d: dt.date, text: str, today: dt.date) -> bool:
    if _date_in_text(d, text):
        return True
    return any(word in text and d == today - dt.timedelta(days=back) for word, back in RELATIVE_DAYS)


def default_timing(rule: EngineRule, category: str) -> tuple[int, int]:
    """(알림 며칠 전, 허용 구간 ±일). LLM이 주지 않을 때 쓴다."""
    if isinstance(rule, IntervalRule):
        return {"day": (1, 1), "week": (3, 3), "month": (7, 7), "year": (14, 14)}[rule.unit]
    if isinstance(rule, LearnedRule):
        return (7, 7)
    if isinstance(rule, OnceRule):
        return (14 if category == "renewal" else 7, 0)
    freq = _rrule_parts(rule.rrule).get("FREQ")
    return {"MONTHLY": (3, 0), "WEEKLY": (1, 0), "YEARLY": (14, 0)}.get(freq or "", (1, 0))


DEFAULT_CONFIDENCE = 0.9  # LLM이 신뢰도를 주지 않을 때(v2). 근거 확인을 통과해야 자동 반영된다.


def validate(result: ExtractionResult, *, heading: str, text: str, today: dt.date) -> Validated:
    if not result.items:
        return Validated(None, confidence=0.0)
    item = result.items[0]
    errors: list[str] = []
    ambiguities = [a for a in item.ambiguities if a]
    if len(result.items) > 1:
        ambiguities.append("한 섹션에서 항목을 여러 개 읽었어요. 섹션을 나눠 주세요.")
    confidence = max(0.0, min(1.0, float(item.confidence if item.confidence is not None else DEFAULT_CONFIDENCE)))

    if item.rule is None:
        return Validated(None, errors, ambiguities, confidence, item.source_quote)

    rule = _to_engine_rule(item.rule, errors)

    events: list[dt.date] = []
    for raw in item.events_in_text:
        try:
            d = dt.date.fromisoformat(raw)
        except ValueError:
            continue  # 날짜가 아니면 버린다
        if d > today:
            ambiguities.append(f"{raw}은(는) 아직 오지 않은 날이라 이력으로 넣지 않았어요")
            continue
        if d < today - dt.timedelta(days=3660) or not _event_grounded(d, text, today):
            continue  # 원문에 없는 날짜(지어낸 것)는 버린다
        events.append(d)

    if errors or rule is None:
        return Validated(None, errors or ["규칙을 만들지 못했어요"], ambiguities, confidence, item.source_quote)

    # 코드가 확실하게 읽을 수 있는 건 코드가 정한다(korean.py)
    if isinstance(rule, (IntervalRule, LearnedRule)):
        events += past_dates(text, today)  # 간격형: 본문에 적힌 지난 날짜 = 마지막으로 한 날
    if isinstance(rule, CalendarRule) and (hint := holiday_shift_hint(text)) is not None:
        rule = rule.model_copy(update={"adjust": "next_business_day" if hint else "none"})
    code_amount = parse_amount(text)

    quote = item.source_quote.strip()
    squashed_quote = _squash(quote).rstrip(".,!?。 ")
    if not quote:
        quote = text  # 근거를 따로 못 집으면 본문 전체가 근거
    elif squashed_quote not in _squash(text) and squashed_quote not in _squash(heading):
        quote = text
        ambiguities.append("근거 문장을 원문에서 찾지 못해 본문 전체를 근거로 뒀어요.")
    ambiguities.extend(grounding_issues(rule, f"{heading} {text}"))

    category = item.category if item.category in CATEGORIES else "other"
    if item.importance in IMPORTANCES:
        importance = item.importance
    else:
        importance = "high" if category in ("bill", "loan", "saving") else "normal"
    if code_amount is not None:
        amount: int | None = code_amount
    else:
        amount = item.amount if item.amount is None or item.amount >= 0 else None
    lead, window = default_timing(rule, category)

    proposal = Proposal(
        title=heading,
        category=category,
        rule=rule,
        events=sorted(set(events)),
        amount=amount,
        importance=importance,
        lead_days=_clamp(item.lead_days, lead),
        window_days=_clamp(item.window_days, window),
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
