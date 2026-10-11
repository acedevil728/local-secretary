"""영업일 보정. 주말과 한국 공휴일(대체공휴일 포함)을 건너뛴다."""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class BusinessCalendar(Protocol):
    def holiday_name(self, d: dt.date) -> str | None: ...

    def is_business_day(self, d: dt.date) -> bool: ...

    def next_business_day(self, d: dt.date) -> dt.date: ...


class KoreanBusinessCalendar:
    """`holidays` 라이브러리의 KR 달력 + 설정으로 넣는 임시공휴일."""

    def __init__(self, extra: dict[dt.date, str] | None = None) -> None:
        import holidays

        try:
            self._kr = holidays.country_holidays("KR", language="ko")
        except (NotImplementedError, TypeError, ValueError):
            self._kr = holidays.country_holidays("KR")
        self._extra = dict(extra or {})

    def holiday_name(self, d: dt.date) -> str | None:
        if d in self._extra:
            return self._extra[d]
        name = self._kr.get(d)
        return str(name) if name else None

    def is_business_day(self, d: dt.date) -> bool:
        return d.weekday() < 5 and self.holiday_name(d) is None

    def next_business_day(self, d: dt.date) -> dt.date:
        for _ in range(30):
            if self.is_business_day(d):
                return d
            d += dt.timedelta(days=1)
        return d

    def holidays_between(self, start: dt.date, end: dt.date) -> list[tuple[dt.date, str]]:
        out = []
        d = start
        while d <= end:
            name = self.holiday_name(d)
            if name:
                out.append((d, name))
            d += dt.timedelta(days=1)
        return out


class WeekendOnlyCalendar:
    """테스트용: 주말만 쉬는 달력."""

    def __init__(self, holidays: dict[dt.date, str] | None = None) -> None:
        self._h = dict(holidays or {})

    def holiday_name(self, d: dt.date) -> str | None:
        return self._h.get(d)

    def is_business_day(self, d: dt.date) -> bool:
        return d.weekday() < 5 and d not in self._h

    def next_business_day(self, d: dt.date) -> dt.date:
        while not self.is_business_day(d):
            d += dt.timedelta(days=1)
        return d

    def holidays_between(self, start: dt.date, end: dt.date) -> list[tuple[dt.date, str]]:
        return sorted((d, n) for d, n in self._h.items() if start <= d <= end)
