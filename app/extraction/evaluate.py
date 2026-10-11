"""평가셋으로 추출 정확도를 잰다(Phase 0). 모델·프롬프트를 바꿀 때마다 돌린다.

    python -m app eval --mode ollama -v

평가셋은 tests/fixtures/extraction/*.json 의 {text, heading, today, expected} 목록이다.
규칙(타입·간격·RRULE·보정), 이력 날짜, 카테고리, 금액이 모두 맞아야 정답으로 센다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..core.config import Settings
from .clients import make_client
from .clients.base import BadLLMOutput, LLMUnavailable
from .clients.fixture import load_cases
from .schema import ExtractionResult, SectionInput
from .validate import rules_equal, validate


def _summary(result: ExtractionResult, heading: str, text: str, today: dt.date) -> dict[str, Any]:
    v = validate(result, heading=heading, text=text, today=today)
    if v.proposal is None:
        return {"rule": None, "events": [], "category": None, "amount": None, "errors": v.errors}
    p = v.proposal.to_json()
    return {"rule": p["rule"], "events": p["events_in_text"], "category": p["category"], "amount": p["amount"], "errors": []}


def compare(expected: dict[str, Any], got: dict[str, Any]) -> list[str]:
    diffs = []
    if not rules_equal(expected["rule"], got["rule"]):
        diffs.append(f"rule {expected['rule']} != {got['rule']}")
    if sorted(expected["events"]) != sorted(got["events"]):
        diffs.append(f"events {expected['events']} != {got['events']}")
    if expected["rule"] is not None:
        if expected["category"] != got["category"]:
            diffs.append(f"category {expected['category']} != {got['category']}")
        if expected["amount"] != got["amount"]:
            diffs.append(f"amount {expected['amount']} != {got['amount']}")
    return diffs


def run_eval(settings: Settings, verbose: bool = False, target: float = 0.9) -> bool:
    client = make_client(settings)
    cases = load_cases(settings.fixtures_dir)
    passed = 0
    for case in cases:
        today = dt.date.fromisoformat(case.get("today", "2026-10-10"))
        heading = case.get("heading", case.get("id", "항목"))
        inp = SectionInput(heading=heading, text=case["text"], today=today, history_dates=[
            dt.date.fromisoformat(d) for d in case.get("history_dates", [])
        ])
        expected = _summary(ExtractionResult.model_validate(case["expected"]), heading, case["text"], today)
        try:
            got = _summary(client.extract(inp).result, heading, case["text"], today)
            diffs = compare(expected, got) + got["errors"]
        except (LLMUnavailable, BadLLMOutput) as exc:
            diffs = [f"{type(exc).__name__}: {exc}"]
        ok = not diffs
        passed += ok
        if verbose or not ok:
            mark = "✓" if ok else "✗"
            print(f"{mark} {case.get('id', heading)}: {case['text']}")
            for d in diffs:
                print(f"    {d}")
    total = len(cases) or 1
    acc = passed / total
    print(f"\n{settings.llm_mode}: {passed}/{len(cases)} = {acc:.0%} (목표 {target:.0%})")
    return acc >= target
