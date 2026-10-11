"""한국어 메모에서 코드가 확실하게 읽을 수 있는 것: 날짜, 금액, 휴일 처리 표현.

LLM은 분류(어떤 규칙인지)만 하고, 계산이 필요한 변환은 여기서 한다.
gemma3:4b 실측에서 "68만 4천원"을 68400으로, 지난 날짜를 엉뚱한 칸에 넣는 실수가 나와 코드로 옮겼다.
RuleMock(clients/rule.py)과 검증(validate.py)이 같이 쓴다.
"""

from __future__ import annotations

import datetime as dt
import re

DATE_RE = re.compile(
    r"(?:(?P<y>\d{4})\s*년\s*)?(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"
    r"|(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})"
    r"|(?<![\d/])(?P<sm>\d{1,2})/(?P<sd>\d{1,2})(?![\d/])"
)
RELATIVE = (("그저께", -2), ("그제", -2), ("어제", -1), ("오늘", 0))


def parse_dates(text: str, today: dt.date) -> list[tuple[dt.date, bool]]:
    """(날짜, 연도가 적혀 있었는지) 목록. 연도가 없으면 올해로 둔다."""
    out = []
    for m in DATE_RE.finditer(text):
        try:
            if m.group("m"):
                y = int(m.group("y")) if m.group("y") else today.year
                out.append((dt.date(y, int(m.group("m")), int(m.group("d"))), bool(m.group("y"))))
            elif m.group("iy"):
                out.append((dt.date(int(m.group("iy")), int(m.group("im")), int(m.group("id"))), True))
            else:
                out.append((dt.date(today.year, int(m.group("sm")), int(m.group("sd"))), False))
        except ValueError:
            continue
    return out


FUTURE_WINDOW_DAYS = 60


def past_dates(text: str, today: dt.date) -> list[dt.date]:
    """본문에 적힌 지난 날짜(오늘 포함). 어제·그제·오늘도 읽는다.

    간격형·이력 학습형 규칙에서는 이게 '마지막으로 한 날'이다(예: "10월 1일에 새로 뜯음").
    연도가 없고 오늘보다 뒤인 날짜는: 60일 안이면 앞으로의 일("1월 10일 예약")이라 버리고,
    그보다 멀면 작년 일로 본다(1월 5일에 쓴 "12월 20일에 잘랐음").
    """
    out = []
    for d, explicit_year in parse_dates(text, today):
        if d > today and not explicit_year:
            if (d - today).days <= FUTURE_WINDOW_DAYS:
                continue
            try:
                d = d.replace(year=d.year - 1)
            except ValueError:  # 2/29
                continue
        if d <= today:
            out.append(d)
    for word, offset in RELATIVE:
        if word in text:
            out.append(today + dt.timedelta(days=offset))
            if word in ("그저께", "그제"):
                break  # '그저께' 안의 '그제'를 두 번 세지 않게
    return sorted(set(out))


def parse_amount(text: str) -> int | None:
    """원 단위 금액. "41만 2천원" → 412000, "보통 4~6만원" → 50000, "52,300원" → 52300."""
    if m := re.search(r"(\d+)\s*~\s*(\d+)\s*만\s*원", text):
        return int((int(m.group(1)) + int(m.group(2))) / 2 * 10000)
    if m := re.search(r"(\d+)\s*만\s*(?:(\d)\s*천\s*)?원", text):
        return int(m.group(1)) * 10000 + int(m.group(2) or 0) * 1000
    if m := re.search(r"(\d+)\s*천\s*원", text):
        return int(m.group(1)) * 1000
    if m := re.search(r"(\d[\d,]{3,})\s*원", text):
        return int(m.group(1).replace(",", ""))
    return None


def holiday_shift_hint(text: str) -> bool | None:
    """휴일 처리를 문장이 분명히 말할 때만 답한다. 모호하면 None(LLM 판단을 쓴다)."""
    if re.search(r"주말이어도|휴일이어도|그날\s*(이체|출금|납부)|당일", text):
        return False
    if re.search(r"휴일이면|영업일", text):
        return True
    return None
