import datetime as dt

import pytest

from app.core.config import ROOT, load_settings
from app.extraction.clients.fixture import load_cases
from app.extraction.clients.rule import RuleMock
from app.extraction.evaluate import _summary, compare, run_eval
from app.extraction.judge import judge
from app.extraction.schema import ExtractedItem, ExtractionResult, LLMRule, SectionInput
from app.extraction.validate import validate

D = dt.date.fromisoformat
CASES = {c["id"]: c for c in load_cases(ROOT / "tests" / "fixtures" / "extraction")}
TODAY = D("2026-10-10")

# 예시 노트에 실제로 쓰인 문장은 RuleMock도 맞혀야 개발 화면이 프로토타입과 같아진다
SAMPLE_CASE_IDS = [
    "hair", "maintenance-fee", "loan-interest", "dental-learned", "engine-oil", "gym-expiry", "nail",
    "phone-bill", "savings", "lens", "passport", "gas-month-end", "car-insurance", "water-filter",
    "electricity-range", "plant-prototype-hint", "rent-month-end", "year-boundary", "relative-yesterday", "no-rule",
]


@pytest.mark.parametrize("case_id", SAMPLE_CASE_IDS)
def test_rule_mock_reads_sample_sentences(case_id):
    case = CASES[case_id]
    today = D(case.get("today", "2026-10-10"))
    inp = SectionInput(
        heading=case["heading"], text=case["text"], today=today,
        history_dates=[D(d) for d in case.get("history_dates", [])],
    )
    got = _summary(RuleMock().extract(inp).result, case["heading"], case["text"], today)
    expected = _summary(ExtractionResult.model_validate(case["expected"]), case["heading"], case["text"], today)
    assert compare(expected, got) == [] and got["errors"] == []


def test_fixture_mode_eval_passes():
    s = load_settings("ci", overrides={"LLM_MODE": "fixture"})
    assert run_eval(s)


def _item(**kw):
    base = dict(title="머리", category="routine", rule=LLMRule(type="interval", every=5, unit="week"),
                events_in_text=["2026-10-10"], source_quote="5주에 1번", confidence=0.9)
    base.update(kw)
    return ExtractionResult(items=[ExtractedItem(**base)])


TEXT = "나는 5주에 1번 머리를 잘라. 2026년 10월 10일에 잘랐음"


def test_validate_accepts_good_output():
    v = validate(_item(), heading="머리", text=TEXT, today=TODAY)
    assert v.errors == [] and v.proposal.events == [TODAY] and v.proposal.window_days == 3


def test_validate_rejects_quote_not_in_text():
    v = validate(_item(source_quote="6주에 1번"), heading="머리", text=TEXT, today=TODAY)
    assert v.proposal is None and "근거 문장이 원문에 없어요" in v.errors


def test_validate_rejects_absurd_interval():
    v = validate(_item(rule=LLMRule(type="interval", every=30, unit="year")), heading="머리", text=TEXT, today=TODAY)
    assert v.proposal is None and any("상식 범위" in e for e in v.errors)
    v0 = validate(_item(rule=LLMRule(type="interval", every=0, unit="week")), heading="머리", text=TEXT, today=TODAY)
    assert v0.proposal is None


def test_validate_rejects_bad_rrule_and_future_events():
    bad = validate(_item(rule=LLMRule(type="calendar", rrule="FREQ=SOMETIMES")), heading="머리", text=TEXT, today=TODAY)
    assert bad.proposal is None
    fut = validate(_item(events_in_text=["2026-12-01"]), heading="머리", text=TEXT, today=TODAY)
    assert fut.proposal.events == [] and fut.ambiguities


def test_judge_paths():
    good = validate(_item(), heading="머리", text=TEXT, today=TODAY)
    assert judge(good, None, 0.75).action == "apply"
    low = validate(_item(confidence=0.5), heading="머리", text=TEXT, today=TODAY)
    assert judge(low, None, 0.75).review_kind == "new_item"
    same = {"type": "interval", "every": 5, "unit": "week", "anchor": "last_event"}
    assert judge(good, same, 0.75).action == "update"
    changed = {"type": "interval", "every": 4, "unit": "week"}
    assert judge(good, changed, 0.75).review_kind == "rule_change"
    none = validate(_item(rule=None), heading="머리", text=TEXT, today=TODAY)
    assert judge(none, None, 0.75).review_kind == "no_rule"
    bad = validate(_item(source_quote="없는 말"), heading="머리", text=TEXT, today=TODAY)
    assert judge(bad, None, 0.75).review_kind == "invalid"
