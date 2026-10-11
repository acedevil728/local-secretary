"""추출 프롬프트. 바꾸면 PROMPT_VERSION을 올린다(캐시 키에 들어간다)."""

from __future__ import annotations

import json
from typing import Any

from .schema import SectionInput

PROMPT_VERSION = "2026-10-10.1"

SYSTEM_PROMPT = """너는 개인 노트의 한 섹션을 읽고 "추적 항목"으로 구조화하는 도우미다.
섹션 하나는 할 일 하나다. 제목은 이미 정해져 있다. 반드시 JSON으로만 답한다.

규칙(rule.type)은 넷 중 하나다.
- interval: "5주에 1번", "6개월마다", "2주용"처럼 마지막으로 한 날부터 세는 간격. every + unit(day|week|month|year).
- calendar: "매달 25일", "매달 말일", "매주 화·목", "격주 토요일", "매년 3월 1일"처럼 달력에 고정된 날.
  rrule에 iCalendar RRULE을 쓴다(DTSTART 없이). 말일·31일은 BYMONTHDAY=-1.
  예: FREQ=MONTHLY;BYMONTHDAY=25 / FREQ=WEEKLY;BYDAY=TU,TH / FREQ=WEEKLY;INTERVAL=2;BYDAY=SA / FREQ=YEARLY;BYMONTH=3;BYMONTHDAY=1
  "휴일이면 다음 영업일", 자동이체·출금처럼 은행 영업일을 따르는 일은 adjust=next_business_day, 아니면 none.
- learned: 주기는 안 적혀 있고 다녀온 날만 기록하는 일. 다른 필드는 비운다.
- once: "10월 20일 만료", "12월 18일까지 제출"처럼 한 번만 하는 일. date에 YYYY-MM-DD.
주기나 날짜를 찾을 수 없으면 rule은 null, confidence는 낮게.

중요:
- 날짜를 계산하지 마라. 다음 날짜를 구하는 것은 프로그램이 한다. 원문에 적힌 날짜만 옮긴다.
- events_in_text: 원문에 적힌 '이미 한 날'(예: "10월 10일에 잘랐음")만 YYYY-MM-DD로. 만료일·마감일은 넣지 않는다.
  연도가 없으면 오늘 기준으로 지나간 가장 가까운 날로 본다. "어제", "지난주 토요일"은 note_saved_at 기준으로 푼다.
- source_quote: 규칙의 근거가 된 원문 문장을 글자 그대로 복사한다. 고치거나 요약하지 마라.
- category: routine|bill|loan|saving|renewal|health|other. 공과금·요금은 bill, 대출 이자·상환은 loan, 적금·저축은 saving.
- importance: bill·loan·saving은 high, 나머지는 보통 normal.
- amount: 원 단위 정수. "41만 2천원" → 412000, "보통 4~6만원" → 50000. 없으면 null.
- lead_days: 기준일 며칠 전에 알릴지. window_days: "이 근처"로 봐줄 허용 일수(주 단위 루틴 3, 월 단위 7, 고정일 0).
- confidence: 0~1. 애매하면 낮추고 ambiguities에 한국어로 이유를 적는다.
- existing_item이 있으면 기존 규칙이다. 문장이 같은 뜻이면 같은 규칙을 그대로 내라."""


def user_payload(inp: SectionInput) -> dict[str, Any]:
    return {
        "today": inp.today.isoformat(),
        "timezone": inp.timezone,
        "note_saved_at": inp.saved_at.isoformat() if inp.saved_at else None,
        "section": {"heading": inp.heading, "text": inp.text},
        "history_dates": [d.isoformat() for d in inp.history_dates],
        "existing_item": inp.existing,
    }


def build_messages(inp: SectionInput) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload(inp), ensure_ascii=False)},
    ]
