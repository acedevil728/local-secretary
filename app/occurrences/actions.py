"""완료·건너뛰기: 노트에 이력 줄을 쓰고(F4) 다시 읽어 다음 일정을 계산한다.

Event 행은 노트 이력 줄에서만 만들어지므로 '노트 쓰기'와 'Event 추가'가 한 작업 단위가 된다.
노트 쓰기가 실패하면 DB는 바뀌지 않는다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.db import Database
from ..notes.format import HistoryLine, SectionNotFound
from ..notes.indexer import NoteIndexer
from ..notes.writer import NoteWriter
from .service import OccurrenceService


class WriteFailed(RuntimeError):
    def __init__(self, message: str, review_id: int | None) -> None:
        super().__init__(message)
        self.review_id = review_id


class ActionService:
    def __init__(
        self,
        db: Database,
        writer: NoteWriter,
        indexer: NoteIndexer,
        occurrences: OccurrenceService,
        reviews,
        clock: Clock,
        bus: EventBus,
    ) -> None:
        self.db = db
        self.writer = writer
        self.indexer = indexer
        self.occurrences = occurrences
        self.reviews = reviews
        self.clock = clock
        self.bus = bus

    def _record(self, occ: dict[str, Any], entry: HistoryLine, message: str) -> dict[str, Any]:
        try:
            self.writer.append(occ["owner_id"], occ["heading"], [entry], message, sync=False)
        except SectionNotFound:
            # 노트에서 섹션 제목이 바뀌었거나 지워졌다. 쓰지 않고 확인 필요로 보낸다.
            with self.db.tx() as c:
                review_id = self.reviews.create(
                    c,
                    person_id=occ["owner_id"],
                    kind="write_failed",
                    reason=f"노트에서 '{occ['heading']}' 섹션을 찾지 못해 이력을 쓰지 못했어요. 직접 적어 주세요.",
                    section_id=None,
                    item_id=None,
                    quote=entry.render(),
                )
            self.bus.publish("review", person_id=occ["owner_id"])
            raise WriteFailed("노트에서 섹션을 찾지 못해 기록하지 못했어요. 확인 필요에 남겼어요.", review_id)
        with self.db.tx() as c:
            # 새 이력이 생기면 '이후 일정도 이 날짜 기준' 기준점은 할 일을 다했다.
            c.execute("UPDATE tracking_item SET next_override = NULL WHERE id = ?", (occ["item_id"],))
        self.indexer.sync_person(occ["owner_id"], force=True)
        nxt = self.occurrences.next_for_item(occ["item_id"])
        return {"item_id": occ["item_id"], "line": entry.render(), "next": nxt}

    def complete(self, occ_id: int, on: dt.date | None, amount: int | None, memo: str | None) -> dict[str, Any]:
        occ = self.occurrences.get(occ_id)
        day = on or self.clock.today()
        entry = HistoryLine(day, "done", "완료", amount, (memo or "").strip() or None, "dashboard")
        return self._record(occ, entry, f"완료: {occ['title']} {day.isoformat()}")

    def skip(self, occ_id: int) -> dict[str, Any]:
        occ = self.occurrences.get(occ_id)
        day = dt.date.fromisoformat(occ["effective_date"])
        entry = HistoryLine(day, "skipped", "건너뜀", None, None, "dashboard")
        return self._record(occ, entry, f"건너뜀: {occ['title']} {day.isoformat()}")
