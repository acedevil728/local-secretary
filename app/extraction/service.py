"""추출 대기열과 작업자.

바뀐 섹션만 대기열에 넣고, 작업 스레드 하나가 순서대로 LLM을 부른다. LLM이 꺼져 있으면
섹션은 'waiting_llm'으로 남고 잠시 뒤 다시 시도한다. 대시보드와 완료 기록은 이 작업과 무관하게 돈다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import queue
import threading
import time
from typing import Any

from ..core.bus import EventBus
from ..core.clock import Clock
from ..core.config import Settings
from ..core.db import Database, loads
from ..occurrences.service import OccurrenceService
from ..scheduling.rules import IntervalRule, LearnedRule
from .apply import ItemApplier
from .clients.base import BadLLMOutput, LLMClient, LLMUnavailable
from .judge import judge
from .prompt import PROMPT_VERSION
from .reviews import ReviewService
from .schema import ExtractionResult, LLMResponse, SectionInput
from .validate import Validated, validate

log = logging.getLogger(__name__)


def cache_key(model: str, inp: SectionInput) -> str:
    payload = json.dumps({"v": PROMPT_VERSION, "m": model, **inp.cache_payload()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExtractionService:
    def __init__(
        self,
        db: Database,
        client: LLMClient,
        clock: Clock,
        settings: Settings,
        bus: EventBus,
        applier: ItemApplier,
        reviews: ReviewService,
        occurrences: OccurrenceService,
    ) -> None:
        self.db = db
        self.client = client
        self.clock = clock
        self.settings = settings
        self.bus = bus
        self.applier = applier
        self.reviews = reviews
        self.occurrences = occurrences
        self._queue: queue.Queue[tuple[int, bool]] = queue.Queue()
        self._queued: set[int] = set()
        self._guard = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.status: dict[str, Any] = {"available": None, "endpoint": None, "last_error": None, "checked_at": None, "nodes": []}
        self._checked_mono = -1e9

    # ---- 대기열 ----

    def enqueue(self, section_id: int, bypass_cache: bool = False) -> None:
        with self._guard:
            if section_id in self._queued:
                return
            self._queued.add(section_id)
        self._queue.put((section_id, bypass_cache))

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="extraction-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                sid, bypass = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self._take(sid, bypass)

    def run_pending(self) -> int:
        """대기열을 지금 스레드에서 비운다(테스트, 작업자를 띄우지 않은 CLI)."""
        n = 0
        while True:
            try:
                sid, bypass = self._queue.get_nowait()
            except queue.Empty:
                return n
            self._take(sid, bypass)
            n += 1

    def _take(self, sid: int, bypass: bool) -> None:
        with self._guard:
            self._queued.discard(sid)
        try:
            self.process(sid, bypass_cache=bypass)
        except Exception:  # 작업자는 죽지 않는다
            log.exception("섹션 %s 분석 중 오류", sid)
            with self.db.tx() as c:
                c.execute("UPDATE section SET parse_status = 'failed' WHERE id = ?", (sid,))

    def retry_waiting(self) -> int:
        rows = self.db.read().execute(
            """SELECT id FROM section WHERE parse_status IN ('waiting_llm', 'pending', 'analyzing')
               AND (analyzed_hash IS NULL OR analyzed_hash != hash)
               AND (ignored_hash IS NULL OR ignored_hash != hash)"""
        ).fetchall()
        for r in rows:
            self.enqueue(r["id"])
        return len(rows)

    def reparse_person(self, person_id: str) -> int:
        """강제 재분석. 모델이나 프롬프트를 바꾼 뒤 쓴다(캐시를 건너뛴다)."""
        with self.db.tx() as c:
            rows = c.execute(
                """SELECT s.id FROM section s JOIN document d ON d.id = s.document_id
                   WHERE d.person_id = ? AND (s.ignored_hash IS NULL OR s.ignored_hash != s.hash)""",
                (person_id,),
            ).fetchall()
            for r in rows:
                c.execute("UPDATE section SET analyzed_hash = NULL, parse_status = 'pending' WHERE id = ?", (r["id"],))
        for r in rows:
            self.enqueue(r["id"], bypass_cache=True)
        self.bus.publish("section", person_id=person_id)
        return len(rows)

    # ---- LLM 상태 (화면의 빨간불/초록불) ----

    def _set_status(self, **kw: Any) -> None:
        before = self.status.get("available")
        self.status.update(kw)
        if self.status.get("available") != before:
            self.bus.publish("llm", available=self.status.get("available"))

    def check_health(self) -> bool:
        """모든 노드를 확인한다. 작업 스케줄러가 1분마다, 화면의 '다시 확인'이 바로 부른다."""
        try:
            nodes = self.client.probe()
            ok = any(n["reachable"] and n["has_model"] for n in nodes)
            err = None if ok else ("; ".join(f"{n['url']}: {n['error']}" for n in nodes if n.get("error")) or "노드 없음")
        except Exception as exc:  # pragma: no cover
            nodes, ok, err = [], False, str(exc)
        self._checked_mono = time.monotonic()
        self._set_status(
            available=ok,
            endpoint=self.client.active_endpoint() if ok else None,
            nodes=nodes,
            last_error=err,
            checked_at=self.clock.now().isoformat(),
        )
        return ok

    def _llm_ready(self) -> bool:
        """꺼진 걸 이미 알면 다시 부르지 않는다(대기열 전체가 타임아웃을 하나씩 기다리지 않게)."""
        available = self.status.get("available")
        if available is True:
            return True
        if available is False and time.monotonic() - self._checked_mono < self.settings.llm_retry_seconds:
            return False
        return self.check_health()

    def pending_count(self) -> int:
        row = self.db.read().execute(
            """SELECT COUNT(*) AS n FROM section WHERE parse_status IN ('waiting_llm', 'pending', 'analyzing')
               AND (analyzed_hash IS NULL OR analyzed_hash != hash)
               AND (ignored_hash IS NULL OR ignored_hash != hash)"""
        ).fetchone()
        return int(row["n"])

    def llm_status(self) -> dict[str, Any]:
        s = self.status
        return {
            "mode": self.settings.llm_mode,
            "available": s.get("available"),
            "endpoint": s.get("endpoint"),
            "last_error": s.get("last_error"),
            "checked_at": s.get("checked_at"),
            "nodes": s.get("nodes") or [],
            "pending": self.pending_count(),
        }

    # ---- 한 섹션 분석 ----

    def _input(self, row, item) -> SectionInput:
        history = [
            dt.date.fromisoformat(r["occurred_on"])
            for r in self.db.read().execute(
                "SELECT occurred_on FROM event WHERE section_id = ? AND status = 'done' ORDER BY occurred_on", (row["id"],)
            )
        ]
        existing = None
        if item is not None:
            existing = {
                "rule": loads(item["rule_json"]),
                "category": item["category"],
                "importance": item["importance"],
                "amount": item["amount"],
                "lead_days": item["lead_days"],
                "window_days": item["window_days"],
            }
        saved_at = dt.datetime.fromisoformat(row["parsed_at"]) if row["parsed_at"] else self.clock.now()
        return SectionInput(
            heading=row["heading"],
            text=row["text"],
            today=self.clock.today(),
            timezone=self.settings.timezone,
            saved_at=saved_at,
            history_dates=history,
            existing=existing,
        )

    def _cached(self, inp: SectionInput) -> LLMResponse | None:
        c = self.db.read()
        for model in self.client.model_ids():
            r = c.execute("SELECT result_json, model FROM extraction_cache WHERE key = ?", (cache_key(model, inp),)).fetchone()
            if r is not None:
                return LLMResponse(result=ExtractionResult.model_validate_json(r["result_json"]), model=r["model"])
        return None

    def process(self, section_id: int, bypass_cache: bool = False) -> str | None:
        c = self.db.read()
        row = c.execute(
            """SELECT s.*, d.person_id, d.parsed_at FROM section s JOIN document d ON d.id = s.document_id
               WHERE s.id = ?""",
            (section_id,),
        ).fetchone()
        if row is None or row["hash"] == row["analyzed_hash"] or row["hash"] == row["ignored_hash"]:
            return None
        pid = row["person_id"]
        item = c.execute("SELECT * FROM tracking_item WHERE section_id = ?", (section_id,)).fetchone()
        inp = self._input(row, item)
        resp = None if bypass_cache else self._cached(inp)
        from_cache = resp is not None

        def wait_for_llm() -> str:
            with self.db.tx() as w:
                w.execute("UPDATE section SET parse_status = 'waiting_llm' WHERE id = ?", (section_id,))
            self.bus.publish("section", person_id=pid, heading=row["heading"], status="waiting_llm")
            return "waiting_llm"

        if resp is None and not self._llm_ready():
            return wait_for_llm()  # LLM이 켜지면 작업 스케줄러가 다시 넣는다
        with self.db.tx() as w:
            w.execute("UPDATE section SET parse_status = 'analyzing' WHERE id = ?", (section_id,))
        self.bus.publish("section", person_id=pid, heading=row["heading"], status="analyzing")

        bad: str | None = None
        if resp is None:
            try:
                resp = self.client.extract(inp)
                self._set_status(available=True, endpoint=self.client.active_endpoint())
            except LLMUnavailable as exc:
                self._checked_mono = time.monotonic()
                self._set_status(available=False, endpoint=None, last_error=str(exc), checked_at=self.clock.now().isoformat())
                return wait_for_llm()
            except BadLLMOutput as exc:
                bad = str(exc)

        today = self.clock.today()
        if bad is not None:
            v = Validated(None, errors=[bad])
            model = "invalid"
        else:
            assert resp is not None
            v = validate(resp.result, heading=row["heading"], text=row["text"], today=today)
            model = resp.model
        decision = judge(v, loads(item["rule_json"]) if item is not None else None, self.settings.confidence_threshold)

        item_id: int | None = item["id"] if item is not None else None
        events_to_write: list[dt.date] = []
        with self.db.tx() as w:
            fresh = w.execute("SELECT hash FROM section WHERE id = ?", (section_id,)).fetchone()
            if fresh is None or fresh["hash"] != row["hash"]:
                return None  # 분석하는 사이 노트가 또 바뀜 → 새 작업이 이미 대기열에 있다
            if decision.action == "apply" and v.proposal is not None:
                item_id = self.applier.create_item(w, section_id, v.proposal, model=model, prompt_version=PROMPT_VERSION)
                status = "done"
            elif decision.action == "update" and v.proposal is not None and item_id is not None:
                self.applier.update_item(w, item_id, v.proposal, include_rule=False, model=model, prompt_version=PROMPT_VERSION)
                status = "done"
            else:
                before = None
                if item is not None:
                    before = {"rule": loads(item["rule_json"]), "amount": item["amount"], "category": item["category"]}
                self.reviews.create(
                    w,
                    person_id=pid,
                    kind=decision.review_kind or "invalid",
                    reason=decision.reason or "",
                    section_id=section_id,
                    item_id=item_id,
                    quote=v.quote or row["text"],
                    before=before,
                    proposed=v.proposal.to_json() if v.proposal is not None else None,
                    confidence=v.confidence,
                )
                status = "review"
            if status == "done" and v.proposal is not None and isinstance(v.proposal.rule, (IntervalRule, LearnedRule)):
                events_to_write = v.proposal.events
            w.execute(
                "UPDATE section SET analyzed_hash = ?, parse_status = ? WHERE id = ?", (row["hash"], status, section_id)
            )
            if resp is not None and not from_cache and not v.errors:
                w.execute(
                    """INSERT OR REPLACE INTO extraction_cache (key, result_json, model, prompt_version, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (cache_key(model, inp), resp.result.model_dump_json(), model, PROMPT_VERSION, self.clock.now().isoformat()),
                )

        if item_id is not None and status == "done":
            self.occurrences.regenerate(item_id)
        if events_to_write:
            self.reviews.write_text_events(pid, row["heading"], events_to_write)
        self.bus.publish("section", person_id=pid, heading=row["heading"], status=status)
        if status == "review":
            self.bus.publish("review", person_id=pid)
        self.bus.publish("schedule")
        return status

    def cards(self, person_id: str) -> list[dict[str, Any]]:
        """노트 편집 화면 오른쪽의 섹션별 분석 결과."""
        c = self.db.read()
        rows = c.execute(
            """SELECT s.*, i.id AS item_id FROM section s JOIN document d ON d.id = s.document_id
               LEFT JOIN tracking_item i ON i.section_id = s.id
               WHERE d.person_id = ? ORDER BY s.position""",
            (person_id,),
        ).fetchall()
        reviews = {r["section_id"]: r for r in self.reviews.list([person_id]) if r["section_id"] is not None}
        out = []
        for r in rows:
            item = None
            if r["item_id"] is not None:
                it = c.execute("SELECT * FROM tracking_item WHERE id = ?", (r["item_id"],)).fetchone()
                nxt = self.occurrences.next_for_item(r["item_id"])
                n_hist = c.execute("SELECT COUNT(*) AS n FROM event WHERE section_id = ?", (r["id"],)).fetchone()["n"]
                item = {
                    "id": it["id"],
                    "rule": loads(it["rule_json"]),
                    "learned_gap_days": self.occurrences.learned_gap_days(it["id"]),
                    "category": it["category"],
                    "importance": it["importance"],
                    "amount": it["amount"],
                    "confidence": it["confidence"],
                    "history_count": n_hist,
                    "next_date": nxt["effective_date"] if nxt else None,
                }
            out.append(
                {
                    "section_id": r["id"],
                    "heading": r["heading"],
                    "status": r["parse_status"],
                    "hash": r["hash"],
                    "item": item,
                    "review": reviews.get(r["id"]),
                }
            )
        return out
