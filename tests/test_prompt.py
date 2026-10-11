"""프롬프트 v2: kind 형식, 예시(few-shot), 근거 확인."""

import datetime as dt
import json

from app.core.config import ROOT
from app.extraction.clients.fixture import load_cases
from app.extraction.clients.ollama import parse_result
from app.extraction.judge import judge
from app.extraction.prompt import EXAMPLES, build_messages
from app.extraction.schema import SectionInput, ollama_format_schema
from app.extraction.validate import validate
from app.scheduling.rules import CalendarRule, IntervalRule, LearnedRule, OnceRule

D = dt.date.fromisoformat


def _v2(text, *, today="2026-10-11", heading="항목", **out):
    payload = {
        "source_quote": out.pop("source_quote", text),
        "rule": {"kind": "none", "every": None, "unit": None, "day_of_month": None, "weekdays": [], "month": None,
                 "date": None, "holiday_shift": False, **out.pop("rule", {})},
        "done_dates": out.pop("done_dates", []),
        "amount": out.pop("amount", None),
        "category": out.pop("category", "routine"),
    }
    return validate(parse_result(json.dumps(payload, ensure_ascii=False)), heading=heading, text=text, today=D(today))


def test_examples_are_valid_grounded_and_auto_applied():
    for example_in, example_out in EXAMPLES:
        v = validate(
            parse_result(json.dumps(example_out, ensure_ascii=False)),
            heading=example_in["title"], text=example_in["text"], today=D(example_in["today"]),
        )
        if example_out["rule"]["kind"] == "none":
            assert v.proposal is None
            continue
        assert v.errors == [] and v.ambiguities == [], (example_in["text"], v.ambiguities)
        assert [d.isoformat() for d in v.proposal.events] == example_out["done_dates"]
        assert judge(v, None, 0.75).action == "apply"


def test_examples_do_not_leak_evaluation_sentences():
    eval_texts = {c["text"] for c in load_cases(ROOT / "tests" / "fixtures" / "extraction")}
    example_texts = {e[0]["text"] for e in EXAMPLES}
    assert not eval_texts & example_texts


def test_messages_put_static_prefix_first_and_hide_history_dates():
    inp = SectionInput(heading="치과", text="치과 다녀온 날 기록", today=D("2026-10-11"),
                       history_dates=[D("2025-10-02"), D("2026-04-08")])
    msgs = build_messages(inp)
    assert msgs[0]["role"] == "system" and len(msgs) == 2 + 2 * len(EXAMPLES)
    last = json.loads(msgs[-1]["content"])
    assert last == {"today": "2026-10-11", "title": "치과", "text": "치과 다녀온 날 기록", "record_count": 2}
    other = build_messages(SectionInput(heading="x", text="y", today=D("2026-12-01")))
    assert msgs[:-1] == other[:-1]  # 앞부분이 같아야 Ollama 프롬프트 캐시가 재사용된다


def test_schema_requires_every_field():
    s = ollama_format_schema()
    assert s["required"][0] == "source_quote"
    assert set(s["properties"]["rule"]["required"]) == set(s["properties"]["rule"]["properties"])


def test_kind_builds_rrule_in_code():
    hair = _v2("나는 5주에 1번 머리를 잘라. 10월 10일에 잘랐음", rule={"kind": "interval", "every": 5, "unit": "week"},
               done_dates=["2026-10-10"])
    assert hair.proposal.rule == IntervalRule(every=5, unit="week") and hair.proposal.events == [D("2026-10-10")]
    assert (hair.proposal.lead_days, hair.proposal.window_days) == (3, 3)

    fee = _v2("관리비는 매달 25일, 휴일이면 다음 영업일. 보통 23만원", rule={"kind": "monthly", "day_of_month": 25, "holiday_shift": True},
              amount="230,000", category="bill")
    assert fee.proposal.rule == CalendarRule(rrule="FREQ=MONTHLY;BYMONTHDAY=25", adjust="next_business_day")
    assert fee.proposal.amount == 230000 and fee.proposal.importance == "high" and fee.ambiguities == []

    end = _v2("도시가스 매달 말일 출금", rule={"kind": "monthly", "day_of_month": -1, "every": 25, "holiday_shift": True})
    assert end.proposal.rule.rrule == "FREQ=MONTHLY;BYMONTHDAY=-1"  # every에 들어간 엉뚱한 25는 무시

    yoga = _v2("요가는 매주 화·목요일 저녁", rule={"kind": "weekly", "weekdays": ["화", "목"]})
    assert yoga.proposal.rule.rrule == "FREQ=WEEKLY;BYDAY=TU,TH" and yoga.ambiguities == []
    legacy_codes = _v2("요가는 매주 화·목요일 저녁", rule={"kind": "weekly", "weekdays": ["tu", "TH"]})
    assert legacy_codes.proposal.rule == yoga.proposal.rule

    trash = _v2("분리수거는 격주 토요일", rule={"kind": "weekly", "weekdays": ["토"], "every": 2})
    assert trash.proposal.rule.rrule == "FREQ=WEEKLY;INTERVAL=2;BYDAY=SA" and trash.ambiguities == []

    tax = _v2("자동차세 매년 1월 16일까지 연납", rule={"kind": "yearly", "month": 1, "day_of_month": 16})
    assert tax.proposal.rule.rrule == "FREQ=YEARLY;BYMONTH=1;BYMONTHDAY=16"

    passport = _v2("여권 11월 2일 만료", rule={"kind": "once", "date": "2026-11-02"}, category="renewal")
    assert passport.proposal.rule == OnceRule(date=D("2026-11-02")) and passport.proposal.lead_days == 14

    dental = _v2("치과 스케일링 다녀온 날 기록", rule={"kind": "learned"}, source_quote="")
    assert isinstance(dental.proposal.rule, LearnedRule) and dental.ambiguities == []

    nothing = _v2("언젠가 해야 함", rule={"kind": "none"})
    assert nothing.proposal is None and nothing.errors == []


def test_hallucinations_seen_with_gemma3_4b_are_caught():
    # v1 실측: 치과(주기 없음)에 '매주 화요일'을 지어냄 → 근거 없음 → 확인 필요
    dental = _v2("치과 스케일링 다녀온 날 기록", rule={"kind": "weekly", "weekdays": ["화"]})
    assert dental.ambiguities and judge(dental, None, 0.75).review_kind == "new_item"

    # v2 실측: 화·목을 TH·SA로 헷갈림 → 토가 문장에 없음 → 확인 필요
    yoga = _v2("요가는 매주 화·목요일 저녁", rule={"kind": "weekly", "weekdays": ["TH", "SA"]})
    assert any("토" in a for a in yoga.ambiguities)

    # 납부일(10/25)과 오늘을 '한 날'로 지어냄 → 원문에 없는 날짜는 버린다
    fee = _v2("관리비는 매달 25일", rule={"kind": "monthly", "day_of_month": 25}, done_dates=["2026-10-11", "2026-10-25"])
    assert fee.proposal.events == []

    # 숫자는 맞는데 단위가 틀림(6개월 → 6주) → 확인 필요
    oil = _v2("엔진오일은 6개월마다 교체", rule={"kind": "interval", "every": 6, "unit": "week"})
    assert oil.ambiguities

    # 날짜에 없는 숫자로 매달 규칙을 만듦 → 확인 필요
    phone = _v2("휴대폰 요금 매달 21일", rule={"kind": "monthly", "day_of_month": 12})
    assert phone.ambiguities

    # v2 실측(평가 24개 중 유일한 오답): "여권 11월 2일 만료"를 '매달 2일'로 읽음 → 반복하는 말이 없음 → 확인 필요
    passport = _v2("여권 11월 2일 만료, 해외여행 전에 재발급", rule={"kind": "monthly", "day_of_month": 2})
    assert any("매달" in a for a in passport.ambiguities) and judge(passport, None, 0.75).action == "review"

    # 필수 칸을 비움 → 형식 오류
    broken = _v2("나는 5주에 1번 머리를 잘라", rule={"kind": "interval", "every": None, "unit": "week"})
    assert broken.proposal is None and broken.errors


def test_code_fixes_what_gemma3_4b_got_wrong_in_eval():
    # 금액: "68만 4천원"을 68400으로 냄 → 코드가 원문에서 계산
    car = _v2("자동차 보험 10월 28일 만기. 작년 68만 4천원", rule={"kind": "once", "date": "2026-10-28"}, amount=68400,
              category="renewal")
    assert car.proposal.amount == 684000

    # 한 날을 rule.date에 넣고 done_dates는 비움 → 간격형이면 본문의 지난 날짜가 이력
    lens = _v2("2주용 렌즈, 10월 1일에 새로 뜯음", rule={"kind": "interval", "every": 2, "unit": "week", "date": "2026-10-01"})
    assert lens.proposal.events == [D("2026-10-01")]

    # "주말이어도 그날 이체"인데 holiday_shift=true → 문장의 명시적 표현이 이긴다
    savings = _v2("적금 매달 10일 50만원 (주말이어도 그날 이체)", rule={"kind": "monthly", "day_of_month": 10, "holiday_shift": True})
    assert savings.proposal.rule.adjust == "none" and savings.proposal.amount == 500000

    # "격주 토요일"을 interval(2주)+요일로 냄 → 요일 규칙
    trash = _v2("분리수거는 격주 토요일", rule={"kind": "interval", "every": 2, "unit": "week", "weekdays": ["토"]})
    assert trash.proposal.rule == CalendarRule(rrule="FREQ=WEEKLY;INTERVAL=2;BYDAY=SA")


def test_korean_parsers():
    from app.extraction.korean import holiday_shift_hint, parse_amount, past_dates

    assert parse_amount("작년 68만 4천원") == 684000
    assert parse_amount("보통 4~6만원") == 50000
    assert parse_amount("52,300원 냄") == 52300
    assert parse_amount("5주마다") is None
    today = D("2027-01-05")
    # 멀리 떨어진 날짜는 작년 일, 60일 안의 앞날은 예약 같은 앞으로의 일이라 버린다
    assert past_dates("12월 20일에 잘랐음, 1월 10일 예약", today) == [D("2026-12-20")]
    assert past_dates("그저께 함", today) == [D("2027-01-03")]
    assert past_dates("2027년 2월 1일 예정", today) == []
    assert holiday_shift_hint("휴일이면 다음 영업일") is True
    assert holiday_shift_hint("주말이어도 그날 이체") is False
    assert holiday_shift_hint("매달 15일 자동이체") is None


def test_relative_and_year_boundary_dates():
    v = _v2("화분은 10일마다 물. 어제 줌", rule={"kind": "interval", "every": 10, "unit": "day"}, done_dates=["2026-10-10"])
    assert v.proposal.events == [D("2026-10-10")]
    v = _v2("5주에 1번 자름. 12월 20일에 잘랐음", today="2027-01-05", rule={"kind": "interval", "every": 5, "unit": "week"},
            done_dates=["2026-12-20"])
    assert v.proposal.events == [D("2026-12-20")]
