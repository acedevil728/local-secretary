"""Occurrence 테이블 관리와 조회.

DB에는 아직 끝나지 않은 회차만 둔다. 끝난 회차는 Event(노트 이력 줄)로 남는다.
상태(upcoming/due/overdue/snoozed)는 '오늘'에 따라 바뀌므로 저장하지 않고 읽을 때 계산한다.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Iterable

from ..core.clock import Clock
from ..core.db import Database, loads
from ..scheduling.business_days import BusinessCalendar
from ..scheduling.engine import EventIn, learned_gap, plan, priority, sort_key, status_of
from ..scheduling.rules import LearnedRule, parse_rule

D = dt.date.fromisoformat

OCC_SELECT = """
SELECT o.*, i.title, i.category, i.importance, i.amount, i.assignees, i.lead_days, i.window_days,
       i.rule_json, i.section_id, d.person_id AS owner_id, s.heading
FROM occurrence o
JOIN tracking_item i ON i.id = o.item_id
JOIN section s ON s.id = i.section_id
JOIN document d ON d.id = s.document_id
"""


class OccurrenceNotFound(LookupError):
    pass


def _month_range(month: str) -> tuple[dt.date, dt.date]:
    y, m = (int(x) for x in month.split("-"))
    first = dt.date(y, m, 1)
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - dt.timedelta(days=1)


def _prev_month(month: str) -> str:
    y, m = (int(x) for x in month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


class OccurrenceService:
    def __init__(self, db: Database, clock: Clock, calendar: BusinessCalendar, horizon_days: int = 90) -> None:
        self.db = db
        self.clock = clock
        self.calendar = calendar
        self.horizon_days = horizon_days

    # ---- 생성 ----

    def regenerate(self, item_id: int) -> None:
        """규칙·이력이 바뀐 항목의 미래 회차를 다시 만든다. 사용자가 고친 회차(미루기·날짜 변경)는 유지한다."""
        with self.db.tx() as c:
            item = c.execute(
                """SELECT i.*, s.first_seen FROM tracking_item i JOIN section s ON s.id = i.section_id
                   WHERE i.id = ?""",
                (item_id,),
            ).fetchone()
            if item is None:
                return
            rule = parse_rule(loads(item["rule_json"]))
            events = [
                EventIn(D(r["occurred_on"]), r["status"])
                for r in c.execute("SELECT occurred_on, status FROM event WHERE section_id = ?", (item["section_id"],))
            ]
            since = min([D(item["first_seen"])] + [e.date for e in events])
            today = self.clock.today()
            planned = plan(
                rule,
                events,
                since=since,
                until=today + dt.timedelta(days=self.horizon_days),
                today=today,
                window_days=item["window_days"],
                calendar=self.calendar,
                next_override=D(item["next_override"]) if item["next_override"] else None,
            )
            existing = {
                r["raw_date"]: r
                for r in c.execute("SELECT * FROM occurrence WHERE item_id = ? AND state = 'pending'", (item_id,))
            }
            keep: set[str] = set()
            for p in planned:
                raw = p.raw_date.isoformat()
                keep.add(raw)
                if raw in existing:
                    c.execute(
                        "UPDATE occurrence SET due_date = ?, window_start = ?, window_end = ? WHERE id = ?",
                        (p.due_date.isoformat(), p.window_start.isoformat(), p.window_end.isoformat(), existing[raw]["id"]),
                    )
                else:
                    c.execute(
                        """INSERT INTO occurrence (item_id, raw_date, due_date, window_start, window_end)
                           VALUES (?, ?, ?, ?, ?)""",
                        (item_id, raw, p.due_date.isoformat(), p.window_start.isoformat(), p.window_end.isoformat()),
                    )
            for raw, r in existing.items():
                if raw not in keep:
                    c.execute("DELETE FROM occurrence WHERE id = ?", (r["id"],))

    def regenerate_all(self) -> None:
        for r in self.db.read().execute("SELECT id FROM tracking_item WHERE status = 'active'").fetchall():
            self.regenerate(r["id"])

    # ---- 보기 ----

    def view(self, r, today: dt.date | None = None) -> dict[str, Any]:
        today = today or self.clock.today()
        effective = D(r["override_date"] or r["due_date"])
        snoozed = D(r["snoozed_until"]) if r["snoozed_until"] else None
        status = status_of(
            effective, lead_days=r["lead_days"], window_days=r["window_days"], today=today, snoozed_until=snoozed
        )
        days_left = (effective - today).days
        w = dt.timedelta(days=r["window_days"])
        rule = loads(r["rule_json"])
        return {
            "id": r["id"],
            "item_id": r["item_id"],
            "title": r["title"],
            "category": r["category"],
            "importance": r["importance"],
            "amount": r["amount"],
            "assignees": loads(r["assignees"], []),
            "owner_id": r["owner_id"],
            "raw_date": r["raw_date"],
            "due_date": r["due_date"],
            "effective_date": effective.isoformat(),
            "window_start": (effective - w).isoformat(),
            "window_end": (effective + w).isoformat(),
            "window_days": r["window_days"],
            "lead_days": r["lead_days"],
            "status": status,
            "days_left": days_left,
            "snoozed_until": r["snoozed_until"],
            "moved": r["override_date"] is not None,
            "priority": priority(status, days_left, r["importance"]),
            "rule_type": rule.get("type"),
        }

    def _rows(self, where: str = "", params: Iterable[Any] = ()) -> list:
        sql = OCC_SELECT + " WHERE o.state = 'pending' AND i.status = 'active'" + (f" AND ({where})" if where else "")
        return self.db.read().execute(sql, tuple(params)).fetchall()

    @staticmethod
    def _for(people: list[str], views: list[dict[str, Any]]) -> list[dict[str, Any]]:
        s = set(people)
        return [v for v in views if s.intersection(v["assignees"])]

    @staticmethod
    def _sorted(views: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(views, key=lambda v: sort_key(v["status"], v["priority"], D(v["effective_date"])))

    def get(self, occ_id: int) -> dict[str, Any]:
        rows = self._rows("o.id = ?", (occ_id,))
        if not rows:
            raise OccurrenceNotFound(occ_id)
        return self.view(rows[0]) | {"heading": rows[0]["heading"], "section_id": rows[0]["section_id"]}

    def agenda(self, people: list[str], days: int) -> dict[str, Any]:
        today = self.clock.today()
        end = (today + dt.timedelta(days=days)).isoformat()
        views = [self.view(r, today) for r in self._rows("COALESCE(o.override_date, o.due_date) <= ?", (end,))]
        week = today + dt.timedelta(days=7)
        out = []
        for pid in people:
            mine = self._sorted(self._for([pid], views))
            active = [v for v in mine if v["status"] != "snoozed"]
            out.append(
                {
                    "person_id": pid,
                    "occurrences": mine,
                    "counts": {
                        "overdue": sum(1 for v in mine if v["status"] == "overdue"),
                        "today": sum(1 for v in active if v["effective_date"] == today.isoformat()),
                        "week": sum(1 for v in active if D(v["effective_date"]) <= week),
                        "total": len(active),
                    },
                }
            )
        return {"today": today.isoformat(), "days": days, "people": out}

    def calendar_range(self, people: list[str], start: dt.date, end: dt.date) -> dict[str, Any]:
        today = self.clock.today()
        s, e = start.isoformat(), end.isoformat()
        rows = self._rows(
            "(COALESCE(o.override_date, o.due_date) BETWEEN ? AND ?) OR (o.window_start <= ? AND o.window_end >= ?)",
            (s, e, e, s),
        )
        views = self._for(people, [self.view(r, today) for r in rows])
        return {
            "from": s,
            "to": e,
            "occurrences": self._sorted(views),
            "events": self.events(people, start, end),
            "holidays": [{"date": d.isoformat(), "name": n} for d, n in self._holidays(start, end)],
        }

    def _holidays(self, start: dt.date, end: dt.date) -> list[tuple[dt.date, str]]:
        fn = getattr(self.calendar, "holidays_between", None)
        return fn(start, end) if fn else []

    def events(self, people: list[str], start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        rows = self.db.read().execute(
            """SELECT e.*, s.heading, s.assignees AS section_assignees, d.person_id AS owner_id,
                      i.id AS item_id, i.title, i.assignees AS item_assignees, i.amount AS item_amount
               FROM event e
               JOIN section s ON s.id = e.section_id
               JOIN document d ON d.id = s.document_id
               LEFT JOIN tracking_item i ON i.section_id = s.id
               WHERE e.occurred_on BETWEEN ? AND ?
               ORDER BY e.occurred_on""",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        out = []
        want = set(people)
        for r in rows:
            assignees = loads(r["item_assignees"] or r["section_assignees"], [r["owner_id"]])
            if not want.intersection(assignees):
                continue
            out.append(
                {
                    "id": r["id"],
                    "item_id": r["item_id"],
                    "title": r["title"] or r["heading"],
                    "heading": r["heading"],
                    "owner_id": r["owner_id"],
                    "assignees": assignees,
                    "date": r["occurred_on"],
                    "status": r["status"],
                    "status_text": r["status_text"],
                    "amount": r["amount"],
                    "memo": r["memo"],
                    "source": r["source"],
                }
            )
        return out

    def day(self, people: list[str], d: dt.date) -> dict[str, Any]:
        today = self.clock.today()
        lo, hi = (d - dt.timedelta(days=60)).isoformat(), (d + dt.timedelta(days=60)).isoformat()
        views = [self.view(r, today) for r in self._rows("COALESCE(o.override_date, o.due_date) BETWEEN ? AND ?", (lo, hi))]
        events = self.events(people, d, d)
        groups = []
        for pid in people:
            mine = self._for([pid], views)
            due = [v for v in mine if v["effective_date"] == d.isoformat()]
            near = [
                v
                for v in mine
                if v["effective_date"] != d.isoformat()
                and v["window_days"] > 0
                and abs((D(v["effective_date"]) - d).days) <= v["window_days"]
            ]
            groups.append(
                {
                    "person_id": pid,
                    "due": self._sorted(due),
                    "near": sorted(near, key=lambda v: v["effective_date"]),
                    "done": [e for e in events if pid in e["assignees"]],
                }
            )
        return {"date": d.isoformat(), "today": today.isoformat(), "holiday": self.calendar.holiday_name(d), "people": groups}

    def finance(self, month: str, people: list[str]) -> dict[str, Any]:
        cur = self._finance_rows(month, people)
        prev_month = _prev_month(month)
        prev = self._finance_rows(prev_month, people)
        per_person = []
        for pid in people:
            mine = [r for r in cur if pid in r["assignees"]]
            per_person.append(
                {
                    "person_id": pid,
                    "due": sum(r["amount"] for r in mine if not r["paid"]),
                    "paid": sum(r["amount"] for r in mine if r["paid"]),
                }
            )
        return {
            "month": month,
            "rows": cur,
            "total_due": sum(r["amount"] for r in cur if not r["paid"]),
            "total_paid": sum(r["amount"] for r in cur if r["paid"]),
            "people": per_person,
            "previous": {
                "month": prev_month,
                "total_paid": sum(r["amount"] for r in prev if r["paid"]),
                "total_due": sum(r["amount"] for r in prev if not r["paid"]),
            },
        }

    def _finance_rows(self, month: str, people: list[str]) -> list[dict[str, Any]]:
        first, last = _month_range(month)
        want = set(people)
        rows: list[dict[str, Any]] = []
        c = self.db.read()
        items = c.execute(
            "SELECT id, section_id, title, amount, assignees FROM tracking_item WHERE amount IS NOT NULL AND status = 'active'"
        ).fetchall()
        for it in items:
            assignees = loads(it["assignees"], [])
            if not want.intersection(assignees):
                continue
            for e in c.execute(
                """SELECT occurred_on, amount FROM event
                   WHERE section_id = ? AND status = 'done' AND occurred_on BETWEEN ? AND ?""",
                (it["section_id"], first.isoformat(), last.isoformat()),
            ):
                rows.append(
                    {
                        "date": e["occurred_on"],
                        "item_id": it["id"],
                        "occurrence_id": None,
                        "title": it["title"],
                        "amount": e["amount"] if e["amount"] is not None else it["amount"],
                        "paid": True,
                        "assignees": assignees,
                    }
                )
            for o in c.execute(
                """SELECT id, COALESCE(override_date, due_date) AS eff FROM occurrence
                   WHERE item_id = ? AND state = 'pending' AND COALESCE(override_date, due_date) BETWEEN ? AND ?""",
                (it["id"], first.isoformat(), last.isoformat()),
            ):
                rows.append(
                    {
                        "date": o["eff"],
                        "item_id": it["id"],
                        "occurrence_id": o["id"],
                        "title": it["title"],
                        "amount": it["amount"],
                        "paid": False,
                        "assignees": assignees,
                    }
                )
        return sorted(rows, key=lambda r: (r["date"], r["title"]))

    # ---- 사용자 조작 (DB만 바뀌는 것) ----

    def snooze(self, occ_id: int, until: dt.date) -> dict[str, Any]:
        self.get(occ_id)
        with self.db.tx() as c:
            c.execute("UPDATE occurrence SET snoozed_until = ? WHERE id = ?", (until.isoformat(), occ_id))
        return self.get(occ_id)

    def reschedule(self, occ_id: int, date: dt.date, shift_future: bool) -> dict[str, Any]:
        occ = self.get(occ_id)
        rule = occ["rule_type"]
        if shift_future and rule in ("interval", "learned"):
            # 다음 기준점을 옮긴다. 이후 회차가 이 날짜부터 다시 계산된다.
            with self.db.tx() as c:
                c.execute("UPDATE tracking_item SET next_override = ? WHERE id = ?", (date.isoformat(), occ["item_id"]))
            self.regenerate(occ["item_id"])
            nxt = self.next_for_item(occ["item_id"])
            return nxt or occ
        with self.db.tx() as c:
            value = None if date.isoformat() == occ["due_date"] else date.isoformat()
            c.execute("UPDATE occurrence SET override_date = ? WHERE id = ?", (value, occ_id))
        return self.get(occ_id)

    def next_for_item(self, item_id: int, limit: int = 1) -> dict[str, Any] | None:
        items = self.upcoming_for_item(item_id, limit)
        return items[0] if items else None

    def upcoming_for_item(self, item_id: int, limit: int = 3) -> list[dict[str, Any]]:
        today = self.clock.today()
        views = [self.view(r, today) for r in self._rows("o.item_id = ?", (item_id,))]
        return sorted(views, key=lambda v: v["effective_date"])[:limit]

    def learned_gap_days(self, item_id: int) -> int | None:
        c = self.db.read()
        item = c.execute("SELECT rule_json, section_id FROM tracking_item WHERE id = ?", (item_id,)).fetchone()
        if item is None or not isinstance(parse_rule(loads(item["rule_json"])), LearnedRule):
            return None
        events = [
            EventIn(D(r["occurred_on"]), r["status"])
            for r in c.execute("SELECT occurred_on, status FROM event WHERE section_id = ?", (item["section_id"],))
        ]
        return learned_gap(events)
