"""노트 형식.

```
# 지훈의 노트              ← 제목 없는 메모(추적 항목 아님)
이번 달은 지출 줄이기.

## 머리 자르기              ← 섹션 = 추적 항목 하나
나는 5주에 1번 머리를 잘라.  ← 사람의 영역 (앱은 고치지 않는다)
(공동: 수아)                ← 선택. 공동 담당자
<!-- history -->
- 2026-10-10 완료           ← 앱의 영역: - YYYY-MM-DD 상태 [금액] [메모] [(대시보드)]
```

파서는 줄 단위로 원문을 그대로 보관해서, 고치지 않은 부분은 글자 하나 바뀌지 않게 다시 쓴다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field

HISTORY_MARKER = "<!-- history -->"
HEADING_RE = re.compile(r"^## +(.+?)\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HISTORY_RE = re.compile(r"^- (\d{4}-\d{2}-\d{2})\s+(\S+)(?:\s+(.*?))?\s*$")
HISTORY_START_RE = re.compile(r"^- \d{4}-\d{2}-\d{2}(\s|$)")
SHARED_RE = re.compile(r"^\(\s*공동\s*[:：]\s*(.+?)\s*\)\s*$")
AMOUNT_RE = re.compile(r"^([\d,]+)\s*원")
DASHBOARD_TAG = "(대시보드)"

SKIP_WORDS = {"건너뜀", "건너뛰기", "스킵", "skip", "skipped"}


def normalize_newlines(text: str) -> str:
    """BOM 제거, CRLF/CR → LF. 노트 줄바꿈은 LF로 통일한다."""
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n").replace("\r", "\n")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class HistoryLine:
    date: dt.date
    status: str = "done"  # done | skipped
    status_text: str = "완료"
    amount: int | None = None
    memo: str | None = None
    source: str = "note"  # note | dashboard

    @staticmethod
    def parse(line: str) -> "HistoryLine | None":
        m = HISTORY_RE.match(line.strip())
        if not m:
            return None
        try:
            date = dt.date.fromisoformat(m.group(1))
        except ValueError:
            return None
        word = m.group(2)
        rest = (m.group(3) or "").strip()
        source = "note"
        if DASHBOARD_TAG in rest:
            source = "dashboard"
            rest = rest.replace(DASHBOARD_TAG, "").strip()
        amount = None
        a = AMOUNT_RE.match(rest)
        if a:
            amount = int(a.group(1).replace(",", ""))
            rest = rest[a.end():].strip()
        status = "skipped" if word.lower() in SKIP_WORDS else "done"
        return HistoryLine(date, status, word, amount, rest or None, source)

    def render(self) -> str:
        word = self.status_text or ("건너뜀" if self.status == "skipped" else "완료")
        parts = [f"- {self.date.isoformat()} {word}"]
        if self.amount is not None:
            parts.append(f"{self.amount:,}원")
        if self.memo:
            parts.append(" ".join(self.memo.split()))
        if self.source == "dashboard":
            parts.append(DASHBOARD_TAG)
        return " ".join(parts)


def _strip_blank_edges(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


@dataclass
class Section:
    heading: str
    heading_line: str
    human_lines: list[str] = field(default_factory=list)
    marker_line: str | None = None
    history_lines: list[str] = field(default_factory=list)
    tail_lines: list[str] = field(default_factory=list)

    @property
    def has_marker(self) -> bool:
        return self.marker_line is not None

    @property
    def human_text(self) -> str:
        """사람의 영역(정규화). 공동 줄 포함."""
        return "\n".join(l.rstrip() for l in _strip_blank_edges(self.human_lines))

    @property
    def llm_text(self) -> str:
        """LLM에 넘기는 원문. 공동 줄은 코드가 읽으므로 뺀다."""
        lines = [l.rstrip() for l in _strip_blank_edges(self.human_lines) if not SHARED_RE.match(l.strip())]
        return "\n".join(_strip_blank_edges(lines))

    @property
    def analysis_hash(self) -> str:
        return content_hash(self.heading + "\n" + self.llm_text)

    @property
    def shared_names(self) -> list[str]:
        for line in self.human_lines:
            m = SHARED_RE.match(line.strip())
            if m:
                return [n.strip() for n in re.split(r"[·,、/ ]+", m.group(1)) if n.strip()]
        return []

    @property
    def history(self) -> list[HistoryLine]:
        out = []
        for line in self.history_lines:
            h = HistoryLine.parse(line)
            if h is not None:
                out.append(h)
        return out

    def lines(self) -> list[str]:
        out = [self.heading_line, *self.human_lines]
        if self.marker_line is not None:
            out.append(self.marker_line)
        out.extend(self.history_lines)
        out.extend(self.tail_lines)
        return out


@dataclass
class Note:
    preamble_lines: list[str]
    sections: list[Section]

    def render(self) -> str:
        lines = list(self.preamble_lines)
        for s in self.sections:
            lines.extend(s.lines())
        return "\n".join(lines)

    def find(self, heading: str) -> Section | None:
        for s in self.sections:
            if s.heading == heading:
                return s
        return None

    @property
    def memo(self) -> str:
        """제목 없는 메모. '# 제목' 줄은 뺀다."""
        lines = [l.strip() for l in self.preamble_lines if l.strip() and not l.lstrip().startswith("# ")]
        return " ".join(lines)

    def duplicate_headings(self) -> set[str]:
        seen: set[str] = set()
        dup: set[str] = set()
        for s in self.sections:
            (dup if s.heading in seen else seen).add(s.heading)
        return dup


def _split_body(heading: str, heading_line: str, body: list[str]) -> Section:
    sec = Section(heading=heading, heading_line=heading_line)
    idx = next((i for i, l in enumerate(body) if l.strip() == HISTORY_MARKER), None)
    if idx is None:
        sec.human_lines = body
        return sec
    sec.human_lines = body[:idx]
    sec.marker_line = body[idx]
    after = body[idx + 1:]
    # 이력 블록 = 마커 바로 뒤의 '- 날짜' 줄들(사이 빈 줄 허용). 그 뒤는 사람이 덧붙인 꼬리로 보관한다.
    last = -1
    for i, line in enumerate(after):
        if HISTORY_START_RE.match(line.strip()):
            last = i
        elif line.strip():
            break
    sec.history_lines = after[: last + 1]
    sec.tail_lines = after[last + 1:]
    return sec


def parse_note(text: str) -> Note:
    lines = normalize_newlines(text).split("\n")
    preamble: list[str] = []
    sections: list[Section] = []
    cur_heading: tuple[str, str] | None = None
    body: list[str] = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
        m = None if in_fence else HEADING_RE.match(line)
        if m:
            if cur_heading is None:
                preamble = body
            else:
                sections.append(_split_body(cur_heading[0], cur_heading[1], body))
            cur_heading = (m.group(1).strip(), line)
            body = []
        else:
            body.append(line)
    if cur_heading is None:
        preamble = body
    else:
        sections.append(_split_body(cur_heading[0], cur_heading[1], body))
    return Note(preamble, sections)


class SectionNotFound(LookupError):
    pass


def insert_history(text: str, heading: str, entry: HistoryLine) -> str:
    """해당 섹션의 이력 블록에 한 줄을 날짜 순서대로 넣는다. 사람의 영역은 건드리지 않는다."""
    note = parse_note(text)
    sec = note.find(heading)
    if sec is None:
        raise SectionNotFound(heading)
    if not sec.has_marker:
        # 마지막 내용 줄 바로 뒤에 마커를 넣고, 원래 있던 빈 줄은 꼬리로 보낸다.
        end = len(sec.human_lines)
        while end > 0 and not sec.human_lines[end - 1].strip():
            end -= 1
        trailing = sec.human_lines[end:]
        sec.human_lines = sec.human_lines[:end]
        sec.marker_line = HISTORY_MARKER
        sec.history_lines = []
        sec.tail_lines = trailing + sec.tail_lines
        if not sec.tail_lines:
            sec.tail_lines = [""]
    # 날짜가 같거나 이른 마지막 줄 뒤에 넣는다. 그런 줄이 없으면 첫 이력 줄 앞.
    parsed = [HistoryLine.parse(l) for l in sec.history_lines]
    dated = [i for i, h in enumerate(parsed) if h is not None]
    earlier = [i for i in dated if parsed[i].date <= entry.date]  # type: ignore[union-attr]
    if earlier:
        pos = earlier[-1] + 1
    elif dated:
        pos = dated[0]
    else:
        pos = len(sec.history_lines)
    sec.history_lines.insert(pos, entry.render())
    return note.render()


def new_section_template(heading: str) -> str:
    return f"## {heading}\n무엇을 언제 하는지 적어 주세요. 예: 3주마다 / 매달 25일 / 11월 30일까지\n{HISTORY_MARKER}\n"
