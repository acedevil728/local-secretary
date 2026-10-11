"""검증을 통과한 제안을 추적 항목에 반영한다."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..core.clock import Clock
from ..core.db import dumps, loads
from ..scheduling.rules import dump_rule
from .validate import Proposal

USER_FIELDS = ("importance", "lead_days", "window_days")


class ItemApplier:
    def __init__(self, clock: Clock) -> None:
        self.clock = clock

    def create_item(self, c: sqlite3.Connection, section_id: int, p: Proposal, *, model: str, prompt_version: str) -> int:
        sec = c.execute("SELECT heading, assignees FROM section WHERE id = ?", (section_id,)).fetchone()
        old = c.execute("SELECT id FROM tracking_item WHERE section_id = ?", (section_id,)).fetchone()
        if old is not None:
            self.update_item(c, old["id"], p, include_rule=True, model=model, prompt_version=prompt_version)
            return old["id"]
        cur = c.execute(
            """INSERT INTO tracking_item (section_id, title, category, rule_json, importance, lead_days, window_days,
                 amount, assignees, confidence, source_quote, prompt_version, model, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                section_id,
                sec["heading"],
                p.category,
                dumps(dump_rule(p.rule)),
                p.importance,
                p.lead_days,
                p.window_days,
                p.amount,
                sec["assignees"],
                p.confidence,
                p.source_quote,
                prompt_version,
                model,
                self.clock.now().isoformat(),
            ),
        )
        return int(cur.lastrowid)

    def update_item(
        self,
        c: sqlite3.Connection,
        item_id: int,
        p: Proposal,
        *,
        include_rule: bool,
        model: str,
        prompt_version: str,
    ) -> None:
        """규칙 외 필드(금액·분류·근거)를 갱신한다. 사용자가 대시보드에서 바꾼 값은 덮어쓰지 않는다."""
        item = c.execute("SELECT user_overrides FROM tracking_item WHERE id = ?", (item_id,)).fetchone()
        overrides = loads(item["user_overrides"], {})
        sets: dict[str, Any] = {
            "category": p.category,
            "amount": p.amount,
            "confidence": p.confidence,
            "source_quote": p.source_quote,
            "prompt_version": prompt_version,
            "model": model,
            "updated_at": self.clock.now().isoformat(),
        }
        for key in USER_FIELDS:
            if key not in overrides:
                sets[key] = getattr(p, key)
        if include_rule:
            sets["rule_json"] = dumps(dump_rule(p.rule))
            sets["next_override"] = None
        cols = ", ".join(f"{k} = ?" for k in sets)
        c.execute(f"UPDATE tracking_item SET {cols} WHERE id = ?", (*sets.values(), item_id))
