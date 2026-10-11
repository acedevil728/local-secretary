"""아침 요약과 개별 알림. 같은 알림은 notification_log로 한 번만 보낸다."""

from __future__ import annotations

import datetime as dt
import logging
import sqlite3
from typing import Any

from ..core.clock import Clock
from ..core.db import Database
from ..occurrences.service import OccurrenceService
from ..people import PeopleService
from .channels import Channel

log = logging.getLogger(__name__)
WD = "월화수목금토일"


def md(iso: str) -> str:
    d = dt.date.fromisoformat(iso)
    return f"{d.month}/{d.day}({WD[d.weekday()]})"


def dlabel(v: dict[str, Any]) -> str:
    k = v["days_left"]
    if v["status"] == "overdue":
        return f"{-k}일 지남"
    if k == 0:
        return "오늘"
    if k < 0:
        return f"{-k}일 전·허용 중"
    return f"D-{k}"


class Notifier:
    def __init__(
        self,
        db: Database,
        clock: Clock,
        people: PeopleService,
        occurrences: OccurrenceService,
        channels: dict[str, Channel],
    ) -> None:
        self.db = db
        self.clock = clock
        self.people = people
        self.occurrences = occurrences
        self.channels = channels

    def send(self, person: dict[str, Any], key: str, kind: str, title: str, body: str, priority: str = "default") -> int:
        sent = 0
        for cfg in person.get("notify") or [{"type": "app"}]:
            ch = self.channels.get(cfg.get("type", ""))
            if ch is None:
                continue
            try:
                with self.db.tx() as c:
                    c.execute(
                        """INSERT INTO notification_log (key, person_id, kind, channel, title, body, sent_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (key, person["id"], kind, ch.type, title, body, self.clock.now().isoformat()),
                    )
            except sqlite3.IntegrityError:
                continue  # 이미 보냄
            try:
                ch.send(person, cfg, title, body, priority)
                sent += 1
            except Exception as exc:
                log.warning("%s 알림 실패(%s): %s", ch.type, person["id"], exc)
                with self.db.tx() as c:  # 실패하면 다음 기회에 다시 보낸다
                    c.execute(
                        "DELETE FROM notification_log WHERE key = ? AND person_id = ? AND kind = ? AND channel = ?",
                        (key, person["id"], kind, ch.type),
                    )
        return sent

    def summary_text(self, person_id: str, days: int = 7) -> tuple[str, str]:
        person = self.people.get(person_id) or {"name": person_id}
        ag = self.occurrences.agenda([person_id], days)["people"][0]
        c = ag["counts"]
        lines = [f"오늘 {c['today']}건 · 연체 {c['overdue']}건 · 다음 {days}일 {c['total']}건"]
        for v in [v for v in ag["occurrences"] if v["status"] != "snoozed"][:8]:
            amount = f" {v['amount']:,}원" if v["amount"] is not None else ""
            lines.append(f"• {md(v['effective_date'])} {v['title']} {dlabel(v)}{amount}")
        return f"{person['name']}님 오늘의 할 일", "\n".join(lines)

    def morning_summary(self) -> int:
        today = self.clock.today().isoformat()
        n = 0
        for person in self.people.list():
            title, body = self.summary_text(person["id"])
            n += self.send(person, f"summary:{today}", "summary", title, body)
        return n

    def lead_alerts(self) -> int:
        """중요도 높은 항목은 알림 구간(기준일 − lead_days)에 들어설 때 따로 알린다."""
        n = 0
        for person in self.people.list():
            ag = self.occurrences.agenda([person["id"]], 60)["people"][0]
            for v in ag["occurrences"]:
                if v["importance"] != "high" or v["status"] not in ("due", "overdue"):
                    continue
                amount = f" · {v['amount']:,}원" if v["amount"] is not None else ""
                n += self.send(
                    person,
                    f"occ:{v['item_id']}:{v['raw_date']}",
                    "lead",
                    f"{v['title']} {dlabel(v)}",
                    f"기준일 {md(v['effective_date'])}{amount}",
                    priority="high",
                )
        return n

    def recent(self, person_ids: list[str], limit: int = 30) -> list[dict[str, Any]]:
        marks = ",".join("?" * len(person_ids)) or "''"
        rows = self.db.read().execute(
            f"""SELECT key, person_id, kind, title, body, sent_at FROM notification_log
                WHERE channel = 'app' AND person_id IN ({marks}) ORDER BY sent_at DESC, id DESC LIMIT ?""",
            (*person_ids, limit),
        ).fetchall()
        return [dict(r) for r in rows]
