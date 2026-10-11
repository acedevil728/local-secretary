"""사용자(Person) 관리. 원본은 `data/people.json`이고 DB에는 복사본을 둔다.

화면(사람 관리)에서 추가·수정·삭제하면 `people.json`을 고치고 다시 읽는다. 삭제한 사람의 노트는 지우지 않고
`people/_archive/<id>-<시각>/`로 옮긴다(노트 git 저장소에도 남는다).
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .core.bus import EventBus
from .core.db import Database, dumps, loads

if TYPE_CHECKING:
    from .notes.indexer import NoteIndexer
    from .notes.repo import NoteRepository

DEFAULT_PEOPLE = {
    "people": [
        {"id": "me", "name": "나", "color": "#3866d1", "color_dark": "#7fa2f2", "notify": [{"type": "app"}]},
    ]
}

# (라이트, 다크) 쌍. 새 사람에게 아직 안 쓴 색부터 준다.
PALETTE = [
    ("#3866d1", "#7fa2f2"),
    ("#c04c78", "#ec8db1"),
    ("#7a58d0", "#ad94ee"),
    ("#2e7a4c", "#6cc391"),
    ("#b8661a", "#e8a15c"),
    ("#1f8a99", "#6fd0dc"),
    ("#8a6d1f", "#d6b85a"),
    ("#a33b3b", "#ee8b8b"),
]

# 노트의 "(공동: 이름·이름)" 줄에서 이름을 가르는 문자와 공백은 이름에 쓸 수 없다.
NAME_RE = re.compile(r"[^\s·,、/()（）:：]{1,20}")
COLOR_RE = re.compile(r"#[0-9a-fA-F]{6}")


class PersonError(ValueError):
    pass


def lighten(hex_color: str, amount: float = 0.45) -> str:
    """다크 테마용 밝은 색. 흰색과 섞는다."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    mix = lambda c: round(c + (255 - c) * amount)  # noqa: E731
    return "#{:02x}{:02x}{:02x}".format(mix(r), mix(g), mix(b))


class PeopleService:
    def __init__(self, db: Database, data_dir: Path) -> None:
        self.db = db
        self.path = data_dir / "people.json"
        self._lock = threading.RLock()

    # ---- 파일 ----

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            self._write(DEFAULT_PEOPLE)
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".people.json.{os.getpid()}.tmp")
        tmp.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
        os.replace(tmp, self.path)

    def load(self) -> list[dict[str, Any]]:
        """people.json → DB. 파일에서 빠진 사람은 DB에서 지워진다(노트 인덱스도 함께)."""
        with self._lock:
            people = self._read().get("people", [])
            ids = [p["id"] for p in people]
            with self.db.tx() as c:
                for i, p in enumerate(people):
                    c.execute(
                        """INSERT INTO person (id, name, color, color_dark, timezone, notify_channels, sort)
                           VALUES (?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(id) DO UPDATE SET name=excluded.name, color=excluded.color,
                             color_dark=excluded.color_dark, timezone=excluded.timezone,
                             notify_channels=excluded.notify_channels, sort=excluded.sort""",
                        (
                            p["id"],
                            p["name"],
                            p.get("color"),
                            p.get("color_dark"),
                            p.get("timezone"),
                            dumps(p.get("notify", [{"type": "app"}])),
                            i,
                        ),
                    )
                if ids:
                    marks = ",".join("?" * len(ids))
                    c.execute(f"DELETE FROM person WHERE id NOT IN ({marks})", ids)
            return self.list()

    # ---- 조회 ----

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.read().execute("SELECT * FROM person ORDER BY sort, id").fetchall()
        return [self._row(r) for r in rows]

    def get(self, person_id: str) -> dict[str, Any] | None:
        r = self.db.read().execute("SELECT * FROM person WHERE id = ?", (person_id,)).fetchone()
        return self._row(r) if r else None

    def ids(self) -> list[str]:
        return [p["id"] for p in self.list()]

    def name_to_id(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in self.list():
            out[p["name"]] = p["id"]
            out[p["id"]] = p["id"]
        return out

    @staticmethod
    def _row(r) -> dict[str, Any]:
        return {
            "id": r["id"],
            "name": r["name"],
            "color": r["color"],
            "color_dark": r["color_dark"],
            "timezone": r["timezone"],
            "notify": loads(r["notify_channels"], []),
        }

    # ---- 변경 (people.json) ----

    @staticmethod
    def _check_name(name: str, people: list[dict[str, Any]], exclude: str | None = None) -> str:
        name = (name or "").strip()
        if not NAME_RE.fullmatch(name):
            raise PersonError("이름은 1~20자, 공백과 · , / ( ) : 없이 적어 주세요")
        if any(p["name"] == name and p["id"] != exclude for p in people):
            raise PersonError(f"'{name}'은(는) 이미 있어요")
        return name

    @staticmethod
    def _check_color(color: str | None) -> str | None:
        if color is None:
            return None
        if not COLOR_RE.fullmatch(color):
            raise PersonError("색은 #RRGGBB 형식이어야 해요")
        return color.lower()

    def create(self, name: str, color: str | None = None) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            people = data.setdefault("people", [])
            name = self._check_name(name, people)
            color = self._check_color(color)
            taken = {p["id"] for p in people}
            n = 1
            while f"p{n}" in taken or (self.path.parent / "people" / f"p{n}").exists():
                n += 1
            used = {(p.get("color") or "").lower() for p in people}
            if color is None:
                light, dark = next(((l, d) for l, d in PALETTE if l not in used), PALETTE[len(people) % len(PALETTE)])
            else:
                light, dark = color, lighten(color)
            person = {"id": f"p{n}", "name": name, "color": light, "color_dark": dark, "notify": [{"type": "app"}]}
            people.append(person)
            self._write(data)
            self.load()
            return self.get(person["id"])  # type: ignore[return-value]

    def update(self, person_id: str, name: str | None = None, color: str | None = None) -> tuple[dict[str, Any], str]:
        """바꾼 뒤의 사람과 바꾸기 전 이름을 돌려준다."""
        with self._lock:
            data = self._read()
            people = data.get("people", [])
            p = next((x for x in people if x["id"] == person_id), None)
            if p is None:
                raise LookupError(person_id)
            old_name = p["name"]
            if name is not None:
                p["name"] = self._check_name(name, people, exclude=person_id)
            color = self._check_color(color)
            if color is not None:
                p["color"], p["color_dark"] = color, lighten(color)
            self._write(data)
            self.load()
            return self.get(person_id), old_name  # type: ignore[return-value]

    def remove(self, person_id: str) -> dict[str, Any]:
        with self._lock:
            data = self._read()
            people = data.get("people", [])
            p = next((x for x in people if x["id"] == person_id), None)
            if p is None:
                raise LookupError(person_id)
            if len(people) <= 1:
                raise PersonError("마지막 한 사람은 지울 수 없어요")
            data["people"] = [x for x in people if x["id"] != person_id]
            self._write(data)
            self.load()
            return p


class PeopleManager:
    """사람 추가·수정·삭제와 그에 따른 노트·인덱스 정리."""

    def __init__(
        self,
        people: PeopleService,
        notes: "NoteRepository",
        indexer: "NoteIndexer",
        db: Database,
        bus: EventBus,
    ) -> None:
        self.people = people
        self.notes = notes
        self.indexer = indexer
        self.db = db
        self.bus = bus

    def _shared_mentions(self, name: str, skip: str | None = None) -> list[str]:
        """다른 노트의 '(공동: 이름)' 줄에 이 이름이 있는 곳. 앱은 사람의 문장을 고치지 않으므로 알려만 준다."""
        from .notes.format import parse_note

        out = []
        for p in self.people.list():
            if p["id"] == skip:
                continue
            text, _ = self.notes.read(p["id"])
            for sec in parse_note(text).sections:
                if name in sec.shared_names:
                    out.append(f"{p['name']}의 노트 '{sec.heading}' 섹션의 (공동: {name}) 줄")
        return out

    def create(self, name: str, color: str | None = None) -> dict[str, Any]:
        person = self.people.create(name, color)
        self.indexer.ensure_note(person["id"])  # 노트 파일 + git 커밋(people.json 변경도 함께)
        self.indexer.sync_person(person["id"])
        self.bus.publish("people")
        return person

    def update(self, person_id: str, name: str | None = None, color: str | None = None) -> dict[str, Any]:
        person, old_name = self.people.update(person_id, name, color)
        warnings: list[str] = []
        if person["name"] != old_name:
            mentions = self._shared_mentions(old_name)
            if mentions:
                warnings.append(
                    f"공동 담당은 이름으로 적혀 있어요. 다음 줄을 '{person['name']}'(으)로 고쳐야 계속 공동으로 잡혀요: "
                    + ", ".join(mentions)
                )
            self.indexer.sync_all(force=True)  # 공동 담당자 다시 계산
        if self.notes.git:
            self.notes.git.commit(f"사람 정보 변경: {old_name} → {person['name']}")
        self.bus.publish("people")
        self.bus.publish("schedule")
        return {"person": person, "warnings": warnings}

    def delete(self, person_id: str) -> dict[str, Any]:
        removed = self.people.remove(person_id)  # 먼저 목록에서 빼야 파일 감시가 노트를 다시 만들지 않는다
        with self.notes.lock(person_id):
            archived = self.notes.archive(person_id)
        with self.db.tx() as c:
            c.execute("DELETE FROM review_task WHERE person_id = ?", (person_id,))
            c.execute("DELETE FROM notification_log WHERE person_id = ?", (person_id,))
        mentions = self._shared_mentions(removed["name"])
        if self.notes.git:
            self.notes.git.commit(f"사람 삭제: {removed['name']} (노트는 {archived or '없음'})")
        self.indexer.sync_all(force=True)  # 남은 사람들의 공동 담당에서 빠진다
        self.bus.publish("people")
        self.bus.publish("schedule")
        warnings = []
        if mentions:
            warnings.append("다음 줄의 공동 담당에서 빠졌어요: " + ", ".join(mentions))
        return {"archived_to": archived, "warnings": warnings}

    def stats(self) -> dict[str, dict[str, int]]:
        rows = self.db.read().execute(
            """SELECT d.person_id, COUNT(DISTINCT s.id) AS sections, COUNT(DISTINCT i.id) AS items
               FROM document d LEFT JOIN section s ON s.document_id = d.id
               LEFT JOIN tracking_item i ON i.section_id = s.id GROUP BY d.person_id"""
        ).fetchall()
        return {r["person_id"]: {"sections": r["sections"], "items": r["items"]} for r in rows}
