"""추출 프롬프트. 바꾸면 PROMPT_VERSION을 올린다(캐시 키에 들어간다).

v2 (2026-10-11): gemma3:4b 실측에서 v1이 RRULE을 틀리게 쓰고(BYDAY=25), interval의 every를 빼먹고,
입력으로 준 기록 날짜를 '한 날'로 복사하는 문제가 나와 바꿨다.
- 규칙은 kind + 단순한 칸으로 받고 RRULE은 코드가 만든다(schema.ollama_format_schema).
- 짧은 규칙 설명 + 예시 대화(few-shot, 11개). 예시 문장은 평가셋(tests/fixtures/extraction)과 겹치지 않게 한다
  (tests/test_prompt.py가 검사).
- 메시지 순서는 [시스템, 예시들, 실제 입력]. 앞부분이 매번 같아서 Ollama가 프롬프트 캐시를 재사용한다.
- 기록 날짜 대신 기록 '개수'만 넘긴다(날짜를 주면 작은 모델이 done_dates로 베낀다).
- 요일은 한글 한 글자로 받는다("화", "목"). 영문 약자(TU/TH)는 4B 모델이 헷갈렸다.
"""

from __future__ import annotations

import json
from typing import Any

from .schema import SectionInput

PROMPT_VERSION = "2026-10-11.4"

SYSTEM_PROMPT = """너는 한국어 메모 한 항목을 읽고 일정 규칙을 JSON으로 옮기는 변환기다.
날짜를 계산하지 마라. text에 적힌 숫자와 날짜만 옮긴다.

rule.kind:
- interval: 마지막으로 한 날부터 세는 간격. "5주에 1번"→every=5,unit="week" / "6개월마다"→every=6,unit="month" / "2주용"→every=2,unit="week" / "매일"→every=1,unit="day"
- monthly: 매달 같은 날. "매달 25일"→day_of_month=25 / "매달 말일"→day_of_month=-1
- weekly: 정해진 요일. "매주 화·목"→weekdays=["화","목"] / "격주 토요일"→weekdays=["토"],every=2
- yearly: 매년 같은 날. "매년 3월 1일"→month=3,day_of_month=1
- once: 한 번만 하는 일. "10월 20일 만료", "12월 18일까지"→date="YYYY-MM-DD"
- learned: 주기는 없고 한 날만 기록하는 일. "다녀온 날 기록"
- none: 주기도 날짜도 없음
쓰지 않는 칸은 null, weekdays는 []로 둔다.

holiday_shift: "휴일이면 다음 영업일", 자동이체, 출금, 빠져나감이면 true. "주말이어도 그날"이면 false. 그 밖에는 false.
done_dates: text에 '이미 한 날'로 적힌 날짜만("잘랐음", "받음", "했음", "갈았음", "뜯음", "줌", "어제 함"). 만료일·마감일·납부일은 넣지 않는다.
  연도가 없으면 today보다 앞선 가장 가까운 날로 쓴다. "어제"는 today 하루 전. text에 없는 날짜는 절대 넣지 않는다.
amount: 원 단위 정수. "41만 2천원"→412000, "보통 4~6만원"→50000. 없으면 null.
category: bill(요금·관리비·공과금·월세·카드값) / loan(대출 이자·상환) / saving(적금·저축) / renewal(만료·만기·갱신) / health(병원·치과·약·렌즈) / routine(그 밖에 반복하는 일) / other
source_quote: 규칙의 근거가 된 부분을 text에서 글자 그대로 복사한다. kind가 none이면 ""."""

# (입력, 기대 출력). 평가셋 문장과 겹치면 안 된다.
EXAMPLES: list[tuple[dict[str, Any], dict[str, Any]]] = [
    (
        {"today": "2026-10-11", "title": "에어컨 필터 청소", "text": "에어컨 필터는 2주마다 청소. 9월 28일에 했음", "record_count": 0},
        {"source_quote": "에어컨 필터는 2주마다 청소", "rule": {"kind": "interval", "every": 2, "unit": "week", "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": ["2026-09-28"], "amount": None, "category": "routine"},
    ),
    (
        {"today": "2026-10-11", "title": "인터넷 요금", "text": "인터넷 요금 매달 17일 자동이체, 3만 3천원", "record_count": 1},
        {"source_quote": "인터넷 요금 매달 17일 자동이체", "rule": {"kind": "monthly", "every": None, "unit": None, "day_of_month": 17, "weekdays": [], "month": None, "date": None, "holiday_shift": True}, "done_dates": [], "amount": 33000, "category": "bill"},
    ),
    (
        {"today": "2026-10-11", "title": "카드값", "text": "카드값은 매달 말일에 빠져나감", "record_count": 2},
        {"source_quote": "카드값은 매달 말일에 빠져나감", "rule": {"kind": "monthly", "every": None, "unit": None, "day_of_month": -1, "weekdays": [], "month": None, "date": None, "holiday_shift": True}, "done_dates": [], "amount": None, "category": "bill"},
    ),
    (
        {"today": "2026-10-11", "title": "수영", "text": "수영은 매주 월·수요일 아침", "record_count": 0},
        {"source_quote": "수영은 매주 월·수요일", "rule": {"kind": "weekly", "every": None, "unit": None, "day_of_month": None, "weekdays": ["월", "수"], "month": None, "date": None, "holiday_shift": False}, "done_dates": [], "amount": None, "category": "routine"},
    ),
    (
        {"today": "2026-10-11", "title": "비타민", "text": "매일 밤 비타민 먹기", "record_count": 0},
        {"source_quote": "매일 밤 비타민 먹기", "rule": {"kind": "interval", "every": 1, "unit": "day", "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": [], "amount": None, "category": "health"},
    ),
    (
        {"today": "2026-10-11", "title": "소모임", "text": "독서 소모임은 격주 일요일 오후", "record_count": 0},
        {"source_quote": "독서 소모임은 격주 일요일", "rule": {"kind": "weekly", "every": 2, "unit": None, "day_of_month": None, "weekdays": ["일"], "month": None, "date": None, "holiday_shift": False}, "done_dates": [], "amount": None, "category": "routine"},
    ),
    (
        {"today": "2026-10-11", "title": "운전면허 갱신", "text": "운전면허 11월 5일까지 갱신해야 함", "record_count": 0},
        {"source_quote": "운전면허 11월 5일까지 갱신해야 함", "rule": {"kind": "once", "every": None, "unit": None, "day_of_month": None, "weekdays": [], "month": None, "date": "2026-11-05", "holiday_shift": False}, "done_dates": [], "amount": None, "category": "renewal"},
    ),
    (
        {"today": "2027-01-05", "title": "안경 렌즈", "text": "안경 렌즈는 1년마다 바꿈. 12월 20일에 바꿨음", "record_count": 0},
        {"source_quote": "안경 렌즈는 1년마다 바꿈", "rule": {"kind": "interval", "every": 1, "unit": "year", "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": ["2026-12-20"], "amount": None, "category": "health"},
    ),
    (
        {"today": "2026-10-11", "title": "분갈이", "text": "화초 분갈이는 6개월마다. 어제 했음", "record_count": 0},
        {"source_quote": "화초 분갈이는 6개월마다", "rule": {"kind": "interval", "every": 6, "unit": "month", "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": ["2026-10-10"], "amount": None, "category": "routine"},
    ),
    (
        {"today": "2026-10-11", "title": "피부과", "text": "피부과 다녀온 날 기록", "record_count": 3},
        {"source_quote": "피부과 다녀온 날 기록", "rule": {"kind": "learned", "every": None, "unit": None, "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": [], "amount": None, "category": "health"},
    ),
    (
        {"today": "2026-10-11", "title": "대청소", "text": "언젠가 대청소 해야 함", "record_count": 0},
        {"source_quote": "", "rule": {"kind": "none", "every": None, "unit": None, "day_of_month": None, "weekdays": [], "month": None, "date": None, "holiday_shift": False}, "done_dates": [], "amount": None, "category": "other"},
    ),
]


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def user_payload(inp: SectionInput) -> dict[str, Any]:
    return {
        "today": inp.today.isoformat(),
        "title": inp.heading,
        "text": inp.text,
        "record_count": len(inp.history_dates),
    }


def build_messages(inp: SectionInput) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for example_in, example_out in EXAMPLES:
        messages.append({"role": "user", "content": _dumps(example_in)})
        messages.append({"role": "assistant", "content": _dumps(example_out)})
    messages.append({"role": "user", "content": _dumps(user_payload(inp))})
    return messages
