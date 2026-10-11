"""앱 안의 정기 작업: 날짜가 바뀌면 Occurrence 범위 늘리기, 아침 요약, 개별 알림, LLM 상태 확인·재시도.

배치가 하루 몇 번뿐이라 별도 큐 없이 스레드 하나로 돌린다.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from ..core.clock import Clock
from ..core.config import Settings
from ..extraction.service import ExtractionService
from ..occurrences.service import OccurrenceService
from .notifier import Notifier

log = logging.getLogger(__name__)


class JobRunner:
    def __init__(
        self,
        clock: Clock,
        settings: Settings,
        occurrences: OccurrenceService,
        notifier: Notifier,
        extraction: ExtractionService,
        tick_seconds: float = 20.0,
    ) -> None:
        self.clock = clock
        self.settings = settings
        self.occurrences = occurrences
        self.notifier = notifier
        self.extraction = extraction
        self.tick_seconds = tick_seconds
        hh, mm = (int(x) for x in settings.morning_time.split(":"))
        self.morning = dt.time(hh, mm)
        self._regen_date: dt.date | None = None
        self._summary_date: dt.date | None = None
        self._last_alerts = 0.0
        self._last_retry = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="jobs", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("정기 작업 오류")
            self._stop.wait(self.tick_seconds)

    def tick(self) -> None:
        now = self.clock.now()
        today = now.date()
        if self._regen_date != today:
            self.occurrences.regenerate_all()
            self._regen_date = today
        if now.time() >= self.morning and self._summary_date != today:
            self.notifier.morning_summary()
            self._summary_date = today
        mono = time.monotonic()
        if mono - self._last_alerts >= 600:
            self.notifier.lead_alerts()
            self._last_alerts = mono
        if mono - self._last_retry >= self.settings.llm_retry_seconds:
            # LLM이 연결되어 있을 때만 밀린 분석을 이어서 한다. 꺼져 있으면 그대로 둔다.
            if self.extraction.check_health():
                self.extraction.retry_waiting()
            self._last_retry = mono
