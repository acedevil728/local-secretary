"""다음 일정(Occurrence) 계산. 입력이 같으면 결과도 같은 순수 함수들이다."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrulestr

from .business_days import BusinessCalendar
from .rules import UNIT_DAYS, CalendarRule, IntervalRule, LearnedRule, OnceRule, interval_days

EventStatus = Literal["done", "skipped"]
OccStatus = Literal["upcoming", "due", "overdue", "snoozed"]

MAX_PLANNED = 400
MAX_SCAN = 4000


@dataclass(frozen=True)
class EventIn:
    date: dt.date
    status: EventStatus = "done"


@dataclass(frozen=True)
class Planned:
    raw_date: dt.date  # 규칙이 만든 날(보정 전). 회차의 고정 키로 쓴다.
    due_date: dt.date  # 기준일(영업일 보정 후)
    window_start: dt.date
    window_end: dt.date


def learned_gap(events: Iterable[EventIn]) -> int | None:
    """완료 이력 간격의 중앙값(일). 이력 2개 이상일 때만."""
    days = sorted({e.date for e in events if e.status == "done"})
    if len(days) < 2:
        return None
    gaps = sorted((b - a).days for a, b in zip(days, days[1:]))
    k = len(gaps) // 2
    if len(gaps) % 2:
        return gaps[k]
    return int((gaps[k - 1] + gaps[k]) / 2 + 0.5)


def _shift(rule: IntervalRule | LearnedRule, base: dt.date, n: int, gap: int | None) -> dt.date:
    # 기준점에서 n배를 한 번에 더한다. 1/31 + 1개월씩 반복하면 2/28 → 3/28로 밀리기 때문이다.
    if isinstance(rule, LearnedRule):
        return base + dt.timedelta(days=(gap or 0) * n)
    k = rule.every * n
    if rule.unit == "day":
        return base + dt.timedelta(days=k)
    if rule.unit == "week":
        return base + dt.timedelta(weeks=k)
    if rule.unit == "month":
        return base + relativedelta(months=k)
    return base + relativedelta(years=k)


def _plan_interval(
    rule: IntervalRule | LearnedRule,
    events: Sequence[EventIn],
    since: dt.date,
    until: dt.date,
    today: dt.date,
    next_override: dt.date | None,
    min_future: int,
) -> list[tuple[dt.date, dt.date]]:
    gap = None
    if isinstance(rule, LearnedRule):
        gap = learned_gap(events)
        if not gap or gap <= 0:
            return []
    # 건너뜀도 기준점이 된다(그 회차를 넘기고 다음 회차부터 다시 센다).
    last = max((e.date for e in events), default=None)
    if next_override is not None and (last is None or next_override > last):
        base, n = next_override, 0
    else:
        base, n = (last or since), 1

    out: list[tuple[dt.date, dt.date]] = []
    future = 0
    first = True
    for _ in range(MAX_PLANNED * 4):
        d = _shift(rule, base, n, gap)
        n += 1
        if d > until and future >= min_future:
            break
        # 첫 회차만 과거(연체)일 수 있다. 그 뒤 회차는 '제때 했다면'의 가정이라 미래 것만 둔다.
        if first or d >= today:
            out.append((d, d))
            if d >= today:
                future += 1
        first = False
        if len(out) >= MAX_PLANNED:
            break
    return out


def _parse_rrule(text: str, since: dt.date):
    s = text.strip()
    if s.upper().startswith("RRULE:"):
        s = s[6:]
    return rrulestr(s, dtstart=dt.datetime.combine(since, dt.time()), ignoretz=True)


def match_events(dues: Sequence[dt.date], events: Sequence[EventIn], window_days: int) -> set[int]:
    """이력 줄을 달력 회차에 짝짓는다.

    가까운 회차(허용 범위 안)를 먼저 찾고, 없으면 그보다 앞선 가장 오래된 미완료 회차에 붙인다
    (늦게 낸 공과금). 짝지어진 회차는 끝난 것으로 본다.
    """
    if not dues:
        return set()
    ordered = sorted(dues)
    gaps = [(b - a).days for a, b in zip(ordered, ordered[1:]) if (b - a).days > 0]
    tol = max(window_days, (min(gaps) // 2) if gaps else 15, 1)
    matched: set[int] = set()
    for ev in sorted(events, key=lambda e: e.date):
        best: tuple[int, int] | None = None
        for i, due in enumerate(dues):
            if i in matched:
                continue
            diff = abs((due - ev.date).days)
            if diff <= tol and (best is None or diff < best[0]):
                best = (diff, i)
        if best is None:
            earlier = [i for i, due in enumerate(dues) if i not in matched and due < ev.date]
            if earlier:
                best = (0, min(earlier, key=lambda i: dues[i]))
        if best is not None:
            matched.add(best[1])
    return matched


def _plan_calendar(
    rule: CalendarRule,
    events: Sequence[EventIn],
    since: dt.date,
    until: dt.date,
    today: dt.date,
    window_days: int,
    calendar: BusinessCalendar,
    min_future: int,
) -> list[tuple[dt.date, dt.date]]:
    rr = iter(_parse_rrule(rule.rrule, since))

    def adjust(raw: dt.date) -> dt.date:
        return calendar.next_business_day(raw) if rule.adjust == "next_business_day" else raw

    cands: list[tuple[dt.date, dt.date]] = []
    for _ in range(MAX_SCAN):
        when = next(rr, None)
        if when is None:
            break
        raw = when.date()
        if raw > until:
            cands.append((raw, adjust(raw)))  # 범위 밖 첫 회차는 '최소 1건'용 후보로 남긴다
            break
        cands.append((raw, adjust(raw)))

    matched = match_events([due for _, due in cands], events, window_days)
    out = [c for i, c in enumerate(cands) if i not in matched and (c[0] <= until)]
    future = sum(1 for _, due in out if due >= today)
    # 범위 안 미래 회차가 모자라면 범위 밖에서 채운다(매년 갱신처럼 드문 일정).
    spill = [c for i, c in enumerate(cands) if i not in matched and c[0] > until]
    for c in spill:
        if future >= min_future:
            break
        out.append(c)
        future += 1
    for _ in range(MAX_SCAN):
        if future >= min_future:
            break
        when = next(rr, None)
        if when is None:
            break
        raw = when.date()
        out.append((raw, adjust(raw)))
        future += 1
    return out[:MAX_PLANNED]


def plan(
    rule: IntervalRule | CalendarRule | LearnedRule | OnceRule,
    events: Iterable[EventIn],
    *,
    since: dt.date,
    until: dt.date,
    today: dt.date,
    window_days: int,
    calendar: BusinessCalendar,
    next_override: dt.date | None = None,
    min_future: int = 1,
) -> list[Planned]:
    """아직 끝나지 않은 회차 목록. 과거의 미완료 회차(연체)도 포함한다."""
    evs = list(events)
    if isinstance(rule, (IntervalRule, LearnedRule)):
        pairs = _plan_interval(rule, evs, since, until, today, next_override, min_future)
    elif isinstance(rule, CalendarRule):
        pairs = _plan_calendar(rule, evs, since, until, today, window_days, calendar, min_future)
    elif isinstance(rule, OnceRule):
        pairs = [] if evs else [(rule.date, rule.date)]
    else:  # pragma: no cover
        raise TypeError(f"unknown rule {rule!r}")
    w = dt.timedelta(days=max(window_days, 0))
    return [Planned(raw, due, due - w, due + w) for raw, due in pairs]


# ---- 상태와 정렬 ----

IMPORTANCE_WEIGHT = {"high": 3.0, "normal": 2.0, "low": 1.0}
STATUS_RANK = {"overdue": 0, "due": 1, "upcoming": 1, "snoozed": 2}


def status_of(
    effective: dt.date,
    *,
    lead_days: int,
    window_days: int,
    today: dt.date,
    snoozed_until: dt.date | None = None,
) -> OccStatus:
    """upcoming(알림 전) → due(기준일 − lead_days) → overdue(기준일 + window_days 경과). 미루기는 알림만 늦춘다."""
    if snoozed_until is not None and snoozed_until > today:
        return "snoozed"
    if effective + dt.timedelta(days=window_days) < today:
        return "overdue"
    if effective - dt.timedelta(days=lead_days) <= today:
        return "due"
    return "upcoming"


def priority(status: str, days_left: int, importance: str) -> float:
    """중요도 가중치 × 긴급도. 연체는 크게 올린다."""
    w = IMPORTANCE_WEIGHT.get(importance, 2.0)
    if status == "overdue":
        urgency = 2.0 + min(-days_left, 60) / 30
    else:
        urgency = 1.0 / (1 + max(days_left, 0))
    return round(w * urgency, 4)


def sort_key(status: str, prio: float, effective: dt.date) -> tuple:
    """연체는 맨 위 고정, 미룬 일은 맨 아래, 나머지는 우선순위 점수 순."""
    return (STATUS_RANK.get(status, 1), -prio, effective)


# ---- 선언 주기 vs 실제 주기 ----


@dataclass(frozen=True)
class Drift:
    declared_days: float
    actual_days: float
    ratio: float
    samples: int


def interval_drift(rule: IntervalRule, events: Iterable[EventIn], threshold: float = 0.2, min_events: int = 3) -> Drift | None:
    days = sorted({e.date for e in events if e.status == "done"})
    if len(days) < min_events:
        return None
    gaps = [(b - a).days for a, b in zip(days, days[1:])]
    actual = sum(gaps) / len(gaps)
    declared = interval_days(rule)
    ratio = abs(actual - declared) / declared
    if ratio < threshold:
        return None
    return Drift(declared, round(actual, 1), round(ratio, 3), len(days))


def suggest_interval(actual_days: float) -> IntervalRule:
    """실제 평균 간격을 사람이 읽기 쉬운 단위로 바꾼다. 자동 적용하지 않고 제안에만 쓴다."""
    if actual_days >= 60:
        return IntervalRule(every=max(1, round(actual_days / UNIT_DAYS["month"])), unit="month")
    weeks = actual_days / 7
    if actual_days >= 14 and abs(weeks - round(weeks)) <= 0.15:
        return IntervalRule(every=round(weeks), unit="week")
    return IntervalRule(every=max(1, round(actual_days)), unit="day")
