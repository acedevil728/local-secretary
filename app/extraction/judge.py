"""판정: 자동 반영할지, 확인 필요로 보낼지."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..scheduling.rules import dump_rule
from .validate import Validated, rules_equal

Action = Literal["apply", "update", "review"]


@dataclass(frozen=True)
class Decision:
    action: Action  # apply: 새 항목 생성, update: 기존 항목의 규칙 외 필드만 갱신, review: 확인 필요
    review_kind: str | None = None
    reason: str | None = None


def judge(v: Validated, existing_rule: dict[str, Any] | None, threshold: float) -> Decision:
    if v.errors:
        return Decision("review", "invalid", "분석 결과를 검증하지 못했어요: " + "; ".join(v.errors))

    if v.proposal is None:
        if existing_rule is not None:
            return Decision("review", "no_rule", "바뀐 문장에서 주기나 날짜를 찾지 못했어요. 기존 규칙을 그대로 쓰고 있어요.")
        hint = " ".join(v.ambiguities)
        return Decision(
            "review",
            "no_rule",
            (hint + " " if hint else "") + '주기나 날짜를 찾지 못했어요. "3주마다", "매달 25일", "11월 30일까지"처럼 적어 주세요.',
        )

    proposed_rule = dump_rule(v.proposal.rule)
    if existing_rule is None:
        if v.confidence >= threshold and not v.ambiguities:
            return Decision("apply")
        detail = " ".join(v.ambiguities) or "규칙을 읽긴 했는데 확실하지 않아요."
        if not detail.rstrip().endswith("?"):
            detail += " 맞는지 확인해 주세요."
        return Decision("review", "new_item", detail)

    if rules_equal(existing_rule, proposed_rule):
        return Decision("update")
    return Decision("review", "rule_change", "문장이 바뀌면서 규칙도 달라졌어요. 새 규칙으로 바꿀까요?")
