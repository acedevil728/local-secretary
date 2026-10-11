import datetime as dt

from app.scheduling.business_days import KoreanBusinessCalendar, WeekendOnlyCalendar
from app.scheduling.engine import (
    EventIn,
    interval_drift,
    learned_gap,
    match_events,
    plan,
    priority,
    sort_key,
    status_of,
    suggest_interval,
)
from app.scheduling.rules import CalendarRule, IntervalRule, LearnedRule, OnceRule, monthly_rrule, yearly_rrule

D = dt.date.fromisoformat
KR = KoreanBusinessCalendar()
WK = WeekendOnlyCalendar()


def _plan(rule, events=(), *, since="2026-10-10", today="2026-10-10", until=None, window=0, cal=KR, override=None):
    t = D(today)
    return plan(
        rule,
        [EventIn(D(e)) if isinstance(e, str) else e for e in events],
        since=D(since),
        until=D(until) if until else t + dt.timedelta(days=90),
        today=t,
        window_days=window,
        calendar=cal,
        next_override=D(override) if override else None,
    )


def test_hair_scenario_from_plan():
    rule = IntervalRule(every=5, unit="week")
    p = _plan(rule, ["2026-10-10"], window=3)
    first = p[0]
    assert first.due_date == D("2026-11-14") and first.due_date.weekday() == 5  # 토요일
    assert (first.window_start, first.window_end) == (D("2026-11-11"), D("2026-11-17"))

    # 11/13에 완료 → 다음 기준일은 완료일 기준 12/18
    p2 = _plan(rule, ["2026-10-10", "2026-11-13"], today="2026-11-13", window=3)
    assert p2[0].due_date == D("2026-12-18")


def test_interval_without_history_starts_from_since():
    p = _plan(IntervalRule(every=2, unit="week"), since="2026-10-01")
    assert p[0].due_date == D("2026-10-15")


def test_interval_only_first_occurrence_can_be_overdue():
    p = _plan(IntervalRule(every=2, unit="week"), ["2026-01-01"], since="2026-01-01", today="2026-03-01")
    assert p[0].due_date == D("2026-01-15")
    assert all(x.due_date >= D("2026-03-01") for x in p[1:])


def test_month_interval_keeps_day_of_month():
    p = _plan(IntervalRule(every=1, unit="month"), ["2027-01-31"], since="2027-01-31", today="2027-01-31", until="2027-04-30")
    assert [x.due_date for x in p[:3]] == [D("2027-02-28"), D("2027-03-31"), D("2027-04-30")]


def test_reschedule_shift_future_moves_anchor():
    p = _plan(IntervalRule(every=5, unit="week"), ["2026-10-10"], override="2026-11-20")
    assert p[0].due_date == D("2026-11-20")
    assert p[1].due_date == D("2026-12-25")


def test_calendar_next_business_day_on_weekend():
    rule = CalendarRule(rrule=monthly_rrule(25), adjust="next_business_day")
    p = _plan(rule, since="2026-10-01")
    assert p[0].raw_date == D("2026-10-25") and p[0].due_date == D("2026-10-26")  # 일요일 → 월요일


def test_calendar_skips_korean_holidays():
    assert not KR.is_business_day(D("2026-10-05"))  # 개천절 대체공휴일
    assert not KR.is_business_day(D("2026-10-09"))  # 한글날
    rule = CalendarRule(rrule=monthly_rrule(3), adjust="next_business_day")
    p = _plan(rule, since="2026-10-01")
    assert p[0].due_date == D("2026-10-06")  # 10/3 토(개천절) → 10/5 대체공휴일 → 10/6


def test_month_end_in_february():
    rule = CalendarRule(rrule=monthly_rrule(-1))
    p = _plan(rule, since="2027-02-01", today="2027-02-01", until="2027-03-31")
    assert [x.due_date for x in p] == [D("2027-02-28"), D("2027-03-31")]
    adj = _plan(CalendarRule(rrule=monthly_rrule(-1), adjust="next_business_day"), since="2027-02-01", today="2027-02-01", until="2027-02-28")
    assert adj[0].due_date == D("2027-03-02")  # 2/28 일 → 3/1 삼일절 → 3/2


def test_day_30_clamps_in_short_months():
    rule = CalendarRule(rrule=monthly_rrule(30))
    p = _plan(rule, since="2027-02-01", today="2027-02-01", until="2027-03-31")
    assert [x.due_date for x in p] == [D("2027-02-28"), D("2027-03-30")]


def test_calendar_history_marks_occurrences_done():
    rule = CalendarRule(rrule=monthly_rrule(25), adjust="next_business_day")
    p = _plan(rule, ["2026-09-25"], since="2026-09-25")
    assert p[0].due_date == D("2026-10-26")


def test_calendar_missed_months_stay_overdue_and_late_payment_matches_oldest():
    rule = CalendarRule(rrule=monthly_rrule(25), adjust="next_business_day")
    missed = _plan(rule, since="2026-08-01")
    assert [x.raw_date for x in missed[:3]] == [D("2026-08-25"), D("2026-09-25"), D("2026-10-25")]
    # 9/8에 낸 건 가까운 8월분 → 9월만 남는다
    late = _plan(rule, ["2026-09-08"], since="2026-08-01")
    assert late[0].raw_date == D("2026-09-25")


def test_event_far_from_any_occurrence_closes_the_oldest_open_one():
    dues = [D("2026-01-01"), D("2026-03-01")]
    assert match_events(dues, [EventIn(D("2026-04-20"))], 0) == {0}
    assert match_events(dues, [EventIn(D("2026-02-27"))], 0) == {1}


def test_weekly_rule():
    rule = CalendarRule(rrule="FREQ=WEEKLY;BYDAY=TU,TH")
    p = _plan(rule, since="2026-10-10", until="2026-10-20")
    assert [x.due_date for x in p] == [D("2026-10-13"), D("2026-10-15"), D("2026-10-20")]


def test_yearly_rule_beyond_horizon_still_yields_one():
    p = _plan(CalendarRule(rrule=yearly_rrule(3, 1)), since="2026-10-10")
    assert len(p) == 1 and p[0].due_date == D("2027-03-01")


def test_once():
    assert [x.due_date for x in _plan(OnceRule(date=D("2026-10-20")))] == [D("2026-10-20")]
    assert _plan(OnceRule(date=D("2026-10-20")), ["2026-10-19"]) == []


def test_learned_median_gap():
    events = [EventIn(D("2025-10-02")), EventIn(D("2026-04-08"))]
    assert learned_gap(events) == 188
    p = _plan(LearnedRule(), events, since="2025-10-02", window=7)
    assert p[0].due_date == D("2026-10-13")
    assert _plan(LearnedRule(), ["2026-04-08"]) == []  # 이력 1개로는 만들지 않는다


def test_skip_counts_as_anchor_for_interval():
    p = _plan(IntervalRule(every=1, unit="week"), [EventIn(D("2026-10-01")), EventIn(D("2026-10-08"), "skipped")])
    assert p[0].due_date == D("2026-10-15")


def test_status_transitions():
    due = D("2026-11-14")
    s = lambda today, snooze=None: status_of(due, lead_days=3, window_days=3, today=D(today), snoozed_until=D(snooze) if snooze else None)
    assert s("2026-11-01") == "upcoming"
    assert s("2026-11-11") == "due"
    assert s("2026-11-17") == "due"
    assert s("2026-11-18") == "overdue"
    assert s("2026-11-12", "2026-11-15") == "snoozed"


def test_overdue_pinned_above_everything():
    high_soon = (sort_key("due", priority("due", 0, "high"), D("2026-10-10")))
    low_overdue = (sort_key("overdue", priority("overdue", -1, "low"), D("2026-10-09")))
    assert low_overdue < high_soon


def test_declared_vs_actual_cycle():
    rule = IntervalRule(every=5, unit="week")
    every_28 = [EventIn(D("2026-01-01") + dt.timedelta(days=28 * i)) for i in range(4)]
    drift = interval_drift(rule, every_28)
    assert drift is not None and drift.actual_days == 28
    assert suggest_interval(drift.actual_days) == IntervalRule(every=4, unit="week")
    every_34 = [EventIn(D("2026-01-01") + dt.timedelta(days=34 * i)) for i in range(4)]
    assert interval_drift(rule, every_34) is None
    assert interval_drift(rule, every_28[:2]) is None  # 이력 3개 미만


def test_weekend_only_calendar_for_tests():
    assert WK.next_business_day(D("2026-10-10")) == D("2026-10-12")
