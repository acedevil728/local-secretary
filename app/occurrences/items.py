"""추적 항목 상세와 대시보드에서 바꾸는 설정(중요도·알림)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..core.bus import EventBus
from ..core.db import Database, dumps, loads
from ..notes.format import parse_note
from ..notes.repo import NoteRepository
from .service import OccurrenceService

USER_FIELDS = ("importance", "lead_days", "window_days")


class ItemNotFound(LookupError):
    pass


class ItemService:
    def __init__(self, db: Database, notes: NoteRepository, occurrences: OccurrenceService, bus: EventBus) -> None:
        self.db = db
        self.notes = notes
        self.occurrences = occurrences
        self.bus = bus

    def _row(self, item_id: int):
        r = self.db.read().execute(
            """SELECT i.*, s.heading, s.first_seen, d.person_id AS owner_id
               FROM tracking_item i JOIN section s ON s.id = i.section_id JOIN document d ON d.id = s.document_id
               WHERE i.id = ?""",
            (item_id,),
        ).fetchone()
        if r is None:
            raise ItemNotFound(item_id)
        return r

    def detail(self, item_id: int) -> dict[str, Any]:
        r = self._row(item_id)
        history = self.occurrences.events([r["owner_id"], *loads(r["assignees"], [])], dt.date(1900, 1, 1), dt.date(9999, 12, 31))
        history = [e for e in history if e["item_id"] == item_id]
        history.sort(key=lambda e: e["date"], reverse=True)
        text, _ = self.notes.read(r["owner_id"])
        sec = parse_note(text).find(r["heading"])
        return {
            "id": r["id"],
            "title": r["title"],
            "heading": r["heading"],
            "category": r["category"],
            "importance": r["importance"],
            "lead_days": r["lead_days"],
            "window_days": r["window_days"],
            "amount": r["amount"],
            "assignees": loads(r["assignees"], []),
            "owner_id": r["owner_id"],
            "rule": loads(r["rule_json"]),
            "learned_gap_days": self.occurrences.learned_gap_days(item_id),
            "source_quote": r["source_quote"],
            "confidence": r["confidence"],
            "prompt_version": r["prompt_version"],
            "model": r["model"],
            "user_overrides": loads(r["user_overrides"], {}),
            "next_override": r["next_override"],
            "since": r["first_seen"],
            "note_path": self.notes.rel_path(r["owner_id"]),
            "note_excerpt": "\n".join(sec.lines()).rstrip() if sec else None,
            "history": history,
            "next": self.occurrences.upcoming_for_item(item_id, 3),
        }

    def patch(self, item_id: int, changes: dict[str, Any]) -> dict[str, Any]:
        r = self._row(item_id)
        overrides = loads(r["user_overrides"], {})
        sets: dict[str, Any] = {}
        for key in USER_FIELDS:
            if changes.get(key) is not None:
                sets[key] = changes[key]
                overrides[key] = changes[key]
        if sets:
            with self.db.tx() as c:
                cols = ", ".join(f"{k} = ?" for k in sets)
                c.execute(
                    f"UPDATE tracking_item SET {cols}, user_overrides = ? WHERE id = ?",
                    (*sets.values(), dumps(overrides), item_id),
                )
            self.occurrences.regenerate(item_id)
            self.bus.publish("schedule")
        return self.detail(item_id)
