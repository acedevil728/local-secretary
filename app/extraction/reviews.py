"""확인 필요 대기열(F6). 신뢰도가 낮거나 기존 규칙이 바뀌는 제안은 사람이 승인해야 반영된다."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import TYPE_CHECKING, Any

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.db import Database, dumps, loads
from ..notes.format import HistoryLine, SectionNotFound
from ..scheduling.engine import EventIn, interval_drift, suggest_interval
from ..scheduling.rules import IntervalRule, dump_rule, parse_rule
from .apply import ItemApplier
from .prompt import PROMPT_VERSION
from .validate import Proposal

if TYPE_CHECKING:
    from ..notes.writer import NoteWriter
    from ..occurrences.service import OccurrenceService

APPROVABLE = {"new_item", "rule_change", "no_rule", "invalid", "cycle_drift"}


class ReviewError(ValueError):
    pass


class ReviewNotFound(LookupError):
    pass


class ReviewService:
    def __init__(self, db: Database, clock: Clock, bus: EventBus, applier: ItemApplier) -> None:
        self.db = db
        self.clock = clock
        self.bus = bus
        self.applier = applier
        # 순환 의존을 피하려고 조립 후에 채운다
        self.occurrences: "OccurrenceService | None" = None
        self.writer: "NoteWriter | None" = None

    def create(
        self,
        c: sqlite3.Connection,
        *,
        person_id: str,
        kind: str,
        reason: str,
        section_id: int | None,
        item_id: int | None,
        quote: str | None = None,
        before: dict[str, Any] | None = None,
        proposed: dict[str, Any] | None = None,
        confidence: float | None = None,
        fingerprint: str | None = None,
    ) -> int:
        now = self.clock.now().isoformat()
        if section_id is not None and kind != "cycle_drift":
            c.execute(
                """UPDATE review_task SET state = 'superseded', resolved_at = ?
                   WHERE section_id = ? AND state = 'open' AND kind NOT IN ('write_failed', 'cycle_drift')""",
                (now, section_id),
            )
        cur = c.execute(
            """INSERT INTO review_task (person_id, section_id, item_id, kind, reason, quote, before_json,
                 proposed_json, confidence, fingerprint, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                person_id,
                section_id,
                item_id,
                kind,
                reason,
                quote,
                dumps(before) if before is not None else None,
                dumps(proposed) if proposed is not None else None,
                confidence,
                fingerprint,
                now,
            ),
        )
        return int(cur.lastrowid)

    def _view(self, r) -> dict[str, Any]:
        proposed = loads(r["proposed_json"])
        return {
            "id": r["id"],
            "person_id": r["person_id"],
            "section_id": r["section_id"],
            "section_heading": r["heading"],
            "item_id": r["item_id"],
            "kind": r["kind"],
            "reason": r["reason"],
            "quote": r["quote"],
            "before": loads(r["before_json"]),
            "proposed": proposed,
            "confidence": r["confidence"],
            "state": r["state"],
            "created_at": r["created_at"],
            "can_approve": r["kind"] in APPROVABLE and bool(proposed and proposed.get("rule")),
        }

    def list(self, people: list[str] | None = None, state: str = "open") -> list[dict[str, Any]]:
        sql = """SELECT r.*, s.heading FROM review_task r LEFT JOIN section s ON s.id = r.section_id
                 WHERE r.state = ?"""
        params: list[Any] = [state]
        if people:
            sql += f" AND r.person_id IN ({','.join('?' * len(people))})"
            params += people
        sql += " ORDER BY r.created_at, r.id"
        return [self._view(r) for r in self.db.read().execute(sql, params).fetchall()]

    def get(self, review_id: int) -> dict[str, Any]:
        r = self.db.read().execute(
            "SELECT r.*, s.heading FROM review_task r LEFT JOIN section s ON s.id = r.section_id WHERE r.id = ?",
            (review_id,),
        ).fetchone()
        if r is None:
            raise ReviewNotFound(review_id)
        return self._view(r)

    def counts(self) -> dict[str, int]:
        rows = self.db.read().execute(
            "SELECT person_id, COUNT(*) AS n FROM review_task WHERE state = 'open' GROUP BY person_id"
        ).fetchall()
        return {r["person_id"]: r["n"] for r in rows}

    # ---- 처리 ----

    def resolve(self, review_id: int, action: str, patch: dict[str, Any] | None = None) -> dict[str, Any]:
        rv = self.get(review_id)
        if rv["state"] != "open":
            raise ReviewError("이미 처리된 요청이에요")
        now = self.clock.now().isoformat()
        item_to_regen: int | None = None
        history_to_write: tuple[str, str, list[dt.date]] | None = None

        if action == "dismiss":
            with self.db.tx() as c:
                if rv["section_id"] is not None:
                    has_item = c.execute(
                        "SELECT 1 FROM tracking_item WHERE section_id = ?", (rv["section_id"],)
                    ).fetchone()
                    if rv["kind"] in ("new_item", "no_rule", "invalid") and not has_item:
                        # 이 문장은 추적하지 않는다. 문장을 고쳐 저장하면 다시 분석한다.
                        c.execute(
                            "UPDATE section SET ignored_hash = hash, parse_status = 'ignored' WHERE id = ?",
                            (rv["section_id"],),
                        )
                    elif rv["kind"] != "cycle_drift":
                        c.execute("UPDATE section SET parse_status = 'done' WHERE id = ?", (rv["section_id"],))
                c.execute("UPDATE review_task SET state = 'dismissed', resolved_at = ? WHERE id = ?", (now, review_id))

        elif action in ("approve", "edit"):
            if rv["kind"] not in APPROVABLE:
                raise ReviewError("이 요청은 승인할 수 없어요. 노트를 직접 고쳐 주세요.")
            proposed = dict(rv["proposed"] or {})
            if patch:
                proposed.update({k: v for k, v in patch.items() if v is not None})
            if not proposed.get("rule"):
                raise ReviewError("승인할 규칙이 없어요. 노트 문장을 고치거나 규칙을 직접 넣어 주세요.")
            try:
                parse_rule(proposed["rule"])
            except ValueError as exc:
                raise ReviewError(f"규칙 형식이 맞지 않아요: {exc}") from exc
            with self.db.tx() as c:
                sec = c.execute(
                    """SELECT s.*, d.person_id FROM section s JOIN document d ON d.id = s.document_id WHERE s.id = ?""",
                    (rv["section_id"],),
                ).fetchone()
                if sec is None:
                    raise ReviewError("노트에서 섹션이 사라졌어요")
                proposed.setdefault("title", sec["heading"])
                proposed.setdefault("source_quote", rv["quote"] or "")
                proposed.setdefault("confidence", rv["confidence"] or 0)
                if rv["kind"] == "cycle_drift":
                    defaults = c.execute("SELECT * FROM tracking_item WHERE id = ?", (rv["item_id"],)).fetchone()
                    for key in ("category", "importance", "lead_days", "window_days", "amount", "source_quote"):
                        proposed.setdefault(key, defaults[key])
                p = Proposal.from_json(proposed)
                item = c.execute("SELECT id FROM tracking_item WHERE section_id = ?", (sec["id"],)).fetchone()
                if item is None:
                    item_id = self.applier.create_item(c, sec["id"], p, model="review", prompt_version=PROMPT_VERSION)
                else:
                    item_id = item["id"]
                    self.applier.update_item(c, item_id, p, include_rule=True, model="review", prompt_version=PROMPT_VERSION)
                c.execute("UPDATE section SET parse_status = 'done' WHERE id = ?", (sec["id"],))
                c.execute("UPDATE review_task SET state = 'approved', resolved_at = ? WHERE id = ?", (now, review_id))
                item_to_regen = item_id
                if p.events:
                    history_to_write = (sec["person_id"], sec["heading"], p.events)
        else:
            raise ReviewError(f"알 수 없는 동작: {action}")

        if item_to_regen is not None and self.occurrences is not None:
            self.occurrences.regenerate(item_to_regen)
        if history_to_write and self.writer is not None:
            self.write_text_events(*history_to_write)
        self.bus.publish("review", person_id=rv["person_id"])
        self.bus.publish("section", person_id=rv["person_id"])
        self.bus.publish("schedule")
        return self.get(review_id)

    def write_text_events(self, person_id: str, heading: str, dates: list[dt.date]) -> None:
        """문장 속 날짜("10월 10일에 잘랐음")를 이력 줄로 옮겨 쓴다. 원문 문장은 그대로 둔다."""
        if self.writer is None or not dates:
            return
        sec = self.db.read().execute(
            """SELECT s.id FROM section s JOIN document d ON d.id = s.document_id
               WHERE d.person_id = ? AND s.heading = ?""",
            (person_id, heading),
        ).fetchone()
        have = set()
        if sec is not None:
            have = {r["occurred_on"] for r in self.db.read().execute("SELECT occurred_on FROM event WHERE section_id = ?", (sec["id"],))}
        missing = [d for d in sorted(set(dates)) if d.isoformat() not in have]
        if not missing:
            return
        entries = [HistoryLine(d, "done", "완료", None, None, "note") for d in missing]
        try:
            self.writer.append(person_id, heading, entries, f"이력 정리: {heading}")
        except SectionNotFound:
            pass

    # ---- 선언 주기 vs 실제 주기 ----

    def check_drift(self, item_id: int) -> None:
        c = self.db.read()
        item = c.execute(
            """SELECT i.*, d.person_id FROM tracking_item i JOIN section s ON s.id = i.section_id
               JOIN document d ON d.id = s.document_id WHERE i.id = ?""",
            (item_id,),
        ).fetchone()
        if item is None:
            return
        rule = parse_rule(loads(item["rule_json"]))
        if not isinstance(rule, IntervalRule):
            return
        events = [
            EventIn(dt.date.fromisoformat(r["occurred_on"]), r["status"])
            for r in c.execute("SELECT occurred_on, status FROM event WHERE section_id = ?", (item["section_id"],))
        ]
        drift = interval_drift(rule, events)
        now = self.clock.now().isoformat()
        with self.db.tx() as w:
            if drift is None:
                w.execute(
                    """UPDATE review_task SET state = 'superseded', resolved_at = ?
                       WHERE item_id = ? AND kind = 'cycle_drift' AND state = 'open'""",
                    (now, item_id),
                )
                return
            fingerprint = f"drift:{item_id}:{drift.samples}:{dump_rule(rule)}"
            if w.execute("SELECT 1 FROM review_task WHERE fingerprint = ?", (fingerprint,)).fetchone():
                return  # 같은 이력 수에서 이미 물어봤다(무시했으면 다시 묻지 않는다)
            w.execute(
                """UPDATE review_task SET state = 'superseded', resolved_at = ?
                   WHERE item_id = ? AND kind = 'cycle_drift' AND state = 'open'""",
                (now, item_id),
            )
            unit_label = {"day": ("일", 1), "week": ("주", 7), "month": ("개월", 30.4375), "year": ("년", 365.25)}[rule.unit]
            actual = drift.actual_days / unit_label[1]
            actual_text = f"{actual:.1f}".rstrip("0").rstrip(".")
            suggestion = suggest_interval(drift.actual_days)
            self.create(
                w,
                person_id=item["person_id"],
                kind="cycle_drift",
                reason=f"실제로는 약 {actual_text}{unit_label[0]}마다 하고 있어요. 주기를 바꿀까요?",
                section_id=item["section_id"],
                item_id=item_id,
                quote=item["source_quote"],
                before={"rule": dump_rule(rule)},
                proposed={"rule": dump_rule(suggestion)},
                confidence=None,
                fingerprint=fingerprint,
            )
        self.bus.publish("review", person_id=item["person_id"])
