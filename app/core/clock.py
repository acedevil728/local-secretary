"""오늘 날짜 주입.

코드는 OS 시계를 직접 읽지 않고 Clock 하나로 받는다. 시간대는 OS가 아니라 설정값으로 고정한다.
테스트와 시연에서는 FixedClock으로 날짜를 고정하거나 앞당겨 연체·알림을 재현한다.
"""

from __future__ import annotations

import datetime as dt
import threading
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    tz: ZoneInfo

    def now(self) -> dt.datetime: ...

    def today(self) -> dt.date: ...


class SystemClock:
    adjustable = False

    def __init__(self, tz: str) -> None:
        self.tz = ZoneInfo(tz)

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.tz)

    def today(self) -> dt.date:
        return self.now().date()


class FixedClock:
    """고정 시각. `set()`으로 바꿀 수 있다(개발 서버의 '기준일')."""

    adjustable = True

    def __init__(self, at: dt.datetime | dt.date | str, tz: str = "Asia/Seoul") -> None:
        self.tz = ZoneInfo(tz)
        self._lock = threading.Lock()
        self._at = self._coerce(at)

    def _coerce(self, at: dt.datetime | dt.date | str) -> dt.datetime:
        if isinstance(at, str):
            at = dt.datetime.fromisoformat(at) if "T" in at else dt.date.fromisoformat(at)
        if isinstance(at, dt.date) and not isinstance(at, dt.datetime):
            at = dt.datetime.combine(at, dt.time(9, 0))
        if at.tzinfo is None:
            at = at.replace(tzinfo=self.tz)
        return at.astimezone(self.tz)

    def set(self, at: dt.datetime | dt.date | str) -> None:
        with self._lock:
            self._at = self._coerce(at)

    def now(self) -> dt.datetime:
        with self._lock:
            return self._at

    def today(self) -> dt.date:
        return self.now().date()


def make_clock(timezone: str, fixed: str | None) -> Clock:
    return FixedClock(fixed, timezone) if fixed else SystemClock(timezone)
