"""RuleMock: 정규식 기반 간이 추출기(프로토타입과 같은 방식).

노트북 개발과 UI 시연용이다. 아무 문장이나 그럴듯하게 처리하지만 정확도는 보장하지 않는다.
"""

from __future__ import annotations

import datetime as dt
import re

from ...scheduling.rules import monthly_rrule, weekly_rrule, yearly_rrule
from ..schema import ExtractedItem, ExtractionResult, LLMResponse, LLMRule, SectionInput
from .base import local_probe

WD = "월화수목금토일"  # Python weekday() 순서
UNIT = {"주": "week", "개월": "month", "달": "month", "일": "day", "년": "year"}

DATE_RE = re.compile(
    r"(?:(?P<y>\d{4})\s*년\s*)?(?P<m>\d{1,2})\s*월\s*(?P<d>\d{1,2})\s*일"
    r"|(?P<iy>\d{4})-(?P<im>\d{1,2})-(?P<id>\d{1,2})"
    r"|(?<![\d/])(?P<sm>\d{1,2})/(?P<sd>\d{1,2})(?![\d/])"
)
RELATIVE = (("그저께", -2), ("그제", -2), ("어제", -1))
SEASON_END = {"봄": (5, 31), "여름": (8, 31), "가을": (10, 31), "겨울": (12, 31)}
DEADLINE_RE = re.compile(r"만료|만기|까지|마감|제출|갱신")


def _sentences(text: str) -> list[str]:
    out = []
    for part in re.split(r"\n|(?<=[.!?])\s+", text):
        s = part.strip().rstrip(".").strip()
        if s:
            out.append(s)
    return out


def _quote(text: str, fragment: str | None) -> str:
    sents = _sentences(text)
    if fragment:
        for s in sents:
            if fragment in s:
                return s
    return sents[0] if sents else ""


def _adjust(q: str) -> str:
    if re.search(r"주말이어도|그날\s*이체|당일", q):
        return "none"
    if re.search(r"휴일|영업일|자동\s*이체|자동\s*결제|출금|빠져\s*나", q):
        return "next_business_day"
    return "none"


def _dates(q: str, today: dt.date) -> list[tuple[dt.date, bool]]:
    """(날짜, 연도가 적혀 있었는지) 목록."""
    out = []
    for m in DATE_RE.finditer(q):
        try:
            if m.group("m"):
                y = int(m.group("y")) if m.group("y") else today.year
                d = dt.date(y, int(m.group("m")), int(m.group("d")))
                out.append((d, bool(m.group("y"))))
            elif m.group("iy"):
                out.append((dt.date(int(m.group("iy")), int(m.group("im")), int(m.group("id"))), True))
            else:
                out.append((dt.date(today.year, int(m.group("sm")), int(m.group("sd"))), False))
        except ValueError:
            continue
    return out


def _amount(q: str) -> int | None:
    if m := re.search(r"(\d+)\s*~\s*(\d+)\s*만\s*원", q):
        return int((int(m.group(1)) + int(m.group(2))) / 2 * 10000)
    if m := re.search(r"(\d+)\s*만\s*(?:(\d)\s*천\s*)?원", q):
        return int(m.group(1)) * 10000 + int(m.group(2) or 0) * 1000
    if m := re.search(r"(\d+)\s*천\s*원", q):
        return int(m.group(1)) * 1000
    if m := re.search(r"(\d[\d,]{3,})\s*원", q):
        return int(m.group(1).replace(",", ""))
    return None


def _category(s: str) -> str:
    if re.search(r"대출|이자|상환", s):
        return "loan"
    if re.search(r"적금|저축|예금", s):
        return "saving"
    if re.search(r"요금|관리비|가스|전기|수도|공과금|보험료|통신비|월세", s):
        return "bill"
    if re.search(r"만료|만기|갱신|여권|면허", s):
        return "renewal"
    if re.search(r"병원|치과|약|렌즈|검진|건강|스케일링|접종", s):
        return "health"
    return "routine"


def extract_rule_based(inp: SectionInput) -> ExtractedItem:
    q = inp.text
    today = inp.today
    base_day = inp.saved_at.date() if inp.saved_at else today
    rule: LLMRule | None = None
    conf = 0.3
    frag: str | None = None
    amb: list[str] = []

    if m := re.search(r"매\s*(?:달|월)\s*(?:(말일)|(\d{1,2})\s*일)", q):
        day = -1 if m.group(1) else int(m.group(2))
        rule = LLMRule(type="calendar", rrule=monthly_rrule(day), adjust=_adjust(q))
        conf, frag = 0.88, m.group(0)
    elif m := re.search(r"격주\s*([월화수목금토일])\s*요일", q):
        rule = LLMRule(type="calendar", rrule=weekly_rrule([WD.index(m.group(1))], interval=2), adjust="none")
        conf, frag = 0.62, m.group(0)
        amb.append("격주가 어느 주부터인지 확인해 주세요.")
    elif m := re.search(r"매주\s*([월화수목금토일](?:\s*[·,、/]?\s*[월화수목금토일])*)\s*요일", q):
        days = [WD.index(c) for c in m.group(1) if c in WD]
        rule = LLMRule(type="calendar", rrule=weekly_rrule(days), adjust="none")
        conf, frag = 0.8, m.group(0)
    elif m := re.search(r"매년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", q):
        rule = LLMRule(type="calendar", rrule=yearly_rrule(int(m.group(1)), int(m.group(2))), adjust="none")
        conf, frag = 0.85, m.group(0)
    elif m := re.search(r"매년\s*(\d{1,2})\s*월", q):
        rule = LLMRule(type="calendar", rrule=yearly_rrule(int(m.group(1)), 1), adjust="none")
        conf, frag = 0.6, m.group(0)
        amb.append("날짜가 없어 그달 1일로 잡았어요.")
    elif m := re.search(r"(\d+)\s*(주|개월|달|일|년)\s*(?:에\s*(?:1|한)\s*번|마다|간격|주기)", q):
        rule = LLMRule(type="interval", every=int(m.group(1)), unit=UNIT[m.group(2)], anchor="last_event")
        conf, frag = 0.9, m.group(0)
    elif m := re.search(r"(\d+)\s*(주|개월|달|일)\s*용", q):
        rule = LLMRule(type="interval", every=int(m.group(1)), unit=UNIT[m.group(2)], anchor="last_event")
        conf, frag = 0.8, m.group(0)
    elif m := re.search(r"매일", q):
        rule = LLMRule(type="interval", every=1, unit="day", anchor="last_event")
        conf, frag = 0.85, m.group(0)
    elif m := re.search(r"([월화수목금토일])\s*[·,]\s*([월화수목금토일])", q):
        days = [WD.index(m.group(1)), WD.index(m.group(2))]
        rule = LLMRule(type="calendar", rrule=weekly_rrule(days), adjust="none")
        conf, frag = 0.58, m.group(0)
        amb.append("주 2회 요일 규칙으로 읽었어요.")

    dates = _dates(q, today)
    events: list[dt.date] = []
    if rule is not None and rule.type == "interval":
        for d, explicit_year in dates:
            if d > today and not explicit_year:
                d = d.replace(year=d.year - 1)
            if d <= today:
                events.append(d)
        for word, off in RELATIVE:
            if word in q:
                events.append(base_day + dt.timedelta(days=off))
                break

    if rule is None and dates:
        d, _ = dates[0]
        rule = LLMRule(type="once", date=d.isoformat())
        conf = 0.85 if DEADLINE_RE.search(q) else 0.72
        m = DATE_RE.search(q)
        frag = m.group(0) if m else None

    if rule is None and (s := re.search(r"(봄|여름|가을|겨울)", q)) and re.search(r"매년|쯤|무렵", q):
        month, day = SEASON_END[s.group(1)]
        d = dt.date(today.year, month, day)
        if d < today:
            d = d.replace(year=d.year + 1)
        rule = LLMRule(type="once", date=d.isoformat())
        conf, frag = 0.41, s.group(0)
        amb.append(f'"{s.group(1)}쯤"을 날짜로 특정하지 못했어요. {month}월 {day}일까지 1회로 잡을까요?')

    if rule is None and (len(inp.history_dates) >= 2 or re.search(r"기록|다녀온 날|할 때마다", q)):
        rule = LLMRule(type="learned")
        conf = 0.8 if len(inp.history_dates) >= 2 else 0.6
        if len(inp.history_dates) < 2:
            amb.append("주기가 적혀 있지 않아요. 기록이 2건 이상 쌓이면 간격을 배워요.")

    category = _category(inp.heading + " " + q)
    unit = rule.unit if rule is not None and rule.type == "interval" else None
    if rule is None:
        lead, window = 3, 0
    elif rule.type == "learned":
        lead, window = 7, 7
    elif rule.type == "once":
        lead, window = (14 if category == "renewal" else 7), 0
    else:
        lead = 7 if unit in ("month", "year") else 3
        window = {"week": 3, "month": 7, "day": 1, "year": 14}.get(unit or "", 0)

    return ExtractedItem(
        title=inp.heading,
        category=category,
        rule=rule,
        events_in_text=[d.isoformat() for d in sorted(set(events))],
        amount=_amount(q),
        importance="high" if category in ("bill", "loan", "saving") else "normal",
        lead_days=lead,
        window_days=window,
        source_quote=_quote(q, frag) if rule is not None else "",
        confidence=conf,
        ambiguities=amb,
    )


class RuleMock:
    name = "rule"

    def health(self) -> bool:
        return True

    def model_ids(self) -> list[str]:
        return ["rule-mock"]

    def active_endpoint(self) -> str | None:
        return None

    def probe(self) -> list[dict]:
        return local_probe("rule-mock")

    def extract(self, section: SectionInput) -> LLMResponse:
        return LLMResponse(result=ExtractionResult(items=[extract_rule_based(section)]), model="rule-mock")
