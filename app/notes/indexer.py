"""노트 → DB 인덱스. 노트가 원본이고, 이 과정을 다시 돌리면 DB가 다시 만들어진다.

- 이력 줄은 LLM 없이 정규식으로 읽어 Event로 만든다.
- 사람의 영역이 바뀐 섹션만 추출 대기열에 넣는다(섹션 해시 비교).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.db import Database, dumps, loads
from .format import parse_note
from .repo import NoteRepository

if TYPE_CHECKING:
    from ..extraction.reviews import ReviewService
    from ..occurrences.service import OccurrenceService
    from ..people import PeopleService

log = logging.getLogger(__name__)


class NoteIndexer:
    def __init__(
        self,
        db: Database,
        notes: NoteRepository,
        people: "PeopleService",
        clock: Clock,
        occurrences: "OccurrenceService",
        reviews: "ReviewService",
        bus: EventBus,
    ) -> None:
        self.db = db
        self.notes = notes
        self.people = people
        self.clock = clock
        self.occurrences = occurrences
        self.reviews = reviews
        self.bus = bus
        self.enqueue: Callable[[int], None] = lambda section_id: None

    def ensure_note(self, person_id: str) -> None:
        person = self.people.get(person_id)
        if person is None:
            return  # 지운 사람의 노트를 다시 만들지 않는다
        with self.notes.lock(person_id):
            if not self.notes.exists(person_id):
                self.notes.write(person_id, f"# {person['name']}의 노트\n\n", f"{person['name']} 노트 만들기")

    def sync_all(self, force: bool = False) -> None:
        for pid in self.people.ids():
            self.sync_person(pid, force=force)

    def _assignees(self, owner: str, names: list[str]) -> list[str]:
        lookup = self.people.name_to_id()
        out = [owner]
        for n in names:
            pid = lookup.get(n)
            if pid and pid not in out:
                out.append(pid)
            elif not pid:
                log.warning("공동 담당자 '%s'를 사람 목록에서 찾지 못함", n)
        return out

    def sync_person(self, person_id: str, force: bool = False) -> bool:
        """노트를 다시 읽어 섹션·이력을 맞춘다. 바뀐 게 없으면 False."""
        if self.people.get(person_id) is None:
            return False
        self.ensure_note(person_id)
        with self.notes.lock(person_id):
            text, h = self.notes.read(person_id)
        note = parse_note(text)
        today = self.clock.today().isoformat()
        now = self.clock.now().isoformat()
        to_enqueue: list[int] = []
        to_regen: list[int] = []

        with self.db.tx() as c:
            doc = c.execute("SELECT * FROM document WHERE person_id = ?", (person_id,)).fetchone()
            if doc is None:
                c.execute(
                    "INSERT INTO document (person_id, path) VALUES (?, ?)",
                    (person_id, self.notes.rel_path(person_id)),
                )
                doc = c.execute("SELECT * FROM document WHERE person_id = ?", (person_id,)).fetchone()
            if not force and doc["content_hash"] == h:
                return False
            doc_id = doc["id"]
            existing = {r["heading"]: r for r in c.execute("SELECT * FROM section WHERE document_id = ?", (doc_id,))}
            seen: set[str] = set()

            for pos, sec in enumerate(note.sections):
                if sec.heading in seen:
                    continue  # 같은 제목의 두 번째 섹션은 추적하지 않는다
                seen.add(sec.heading)
                shash = sec.analysis_hash
                assignees = self._assignees(person_id, sec.shared_names)
                row = existing.get(sec.heading)
                if row is None:
                    cur = c.execute(
                        """INSERT INTO section (document_id, heading, position, text, hash, parse_status, assignees, first_seen)
                           VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)""",
                        (doc_id, sec.heading, pos, sec.llm_text, shash, dumps(assignees), today),
                    )
                    sid = cur.lastrowid
                    analyzed = ignored = None
                else:
                    sid = row["id"]
                    analyzed, ignored = row["analyzed_hash"], row["ignored_hash"]
                    if row["hash"] != shash:
                        # 문장이 바뀌면 이전 분석에서 나온 확인 요청은 의미가 없다
                        c.execute(
                            """UPDATE review_task SET state = 'superseded', resolved_at = ?
                               WHERE section_id = ? AND state = 'open' AND kind NOT IN ('write_failed', 'cycle_drift')""",
                            (now, sid),
                        )
                    c.execute(
                        "UPDATE section SET position = ?, text = ?, hash = ?, assignees = ? WHERE id = ?",
                        (pos, sec.llm_text, shash, dumps(assignees), sid),
                    )

                c.execute("DELETE FROM event WHERE section_id = ?", (sid,))
                for hl in sec.history:
                    c.execute(
                        """INSERT INTO event (section_id, occurred_on, status, status_text, source, amount, memo, line)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (sid, hl.date.isoformat(), hl.status, hl.status_text, hl.source, hl.amount, hl.memo, hl.render()),
                    )

                if ignored == shash:
                    c.execute("UPDATE section SET parse_status = 'ignored' WHERE id = ?", (sid,))
                elif analyzed != shash:
                    c.execute("UPDATE section SET parse_status = 'pending' WHERE id = ?", (sid,))
                    to_enqueue.append(sid)

                item = c.execute("SELECT id, assignees FROM tracking_item WHERE section_id = ?", (sid,)).fetchone()
                if item is not None:
                    if loads(item["assignees"], []) != assignees:
                        c.execute("UPDATE tracking_item SET assignees = ? WHERE id = ?", (dumps(assignees), item["id"]))
                    to_regen.append(item["id"])

            for heading, row in existing.items():
                if heading not in seen:
                    c.execute("DELETE FROM section WHERE id = ?", (row["id"],))

            c.execute(
                "UPDATE document SET content_hash = ?, parsed_at = ?, path = ? WHERE id = ?",
                (h, now, self.notes.rel_path(person_id), doc_id),
            )

        for item_id in to_regen:
            self.occurrences.regenerate(item_id)
            self.reviews.check_drift(item_id)
        for sid in to_enqueue:
            self.enqueue(sid)
        self.bus.publish("notes", person_id=person_id)
        self.bus.publish("schedule")
        return True

    def section_ids(self, person_id: str) -> list[int]:
        rows = self.db.read().execute(
            "SELECT s.id FROM section s JOIN document d ON d.id = s.document_id WHERE d.person_id = ?",
            (person_id,),
        ).fetchall()
        return [r["id"] for r in rows]
