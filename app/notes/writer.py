"""앱이 노트에 이력 줄을 쓰는 유일한 길. 쓴 뒤에는 바로 다시 읽어 DB를 맞춘다."""

from __future__ import annotations

from .format import HistoryLine, insert_history
from .indexer import NoteIndexer
from .repo import NoteRepository


class NoteWriter:
    def __init__(self, notes: NoteRepository, indexer: NoteIndexer) -> None:
        self.notes = notes
        self.indexer = indexer

    def append(
        self,
        person_id: str,
        heading: str,
        entries: list[HistoryLine],
        message: str,
        *,
        sync: bool = True,
    ) -> bool:
        """해당 섹션 이력 블록에 줄을 넣는다. 섹션이 없으면 SectionNotFound.

        쓰기 직전에 파일 해시를 다시 비교한다. 사람이 그사이 편집했으면 다시 읽고 이력 줄만 넣는다.
        """
        changed = False
        with self.notes.lock(person_id):
            for _ in range(3):
                text, h = self.notes.read(person_id)
                new = text
                for e in entries:
                    new = insert_history(new, heading, e)
                if new == text:
                    break
                if self.notes.read(person_id)[1] != h:
                    continue  # 그사이 바뀜 → 다시 읽어서 합친다
                self.notes.write(person_id, new, message)
                changed = True
                break
        if sync:
            self.indexer.sync_person(person_id)
        return changed
