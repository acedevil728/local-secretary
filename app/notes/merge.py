"""노트 3-way 병합.

편집기가 노트를 연 뒤(base) 대시보드가 이력 줄을 추가했다면(theirs), 편집기 저장본(ours)에
그 이력 줄만 합친다. 사람의 영역이 양쪽에서 다르게 바뀌었을 때만 충돌로 본다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .format import HISTORY_MARKER, HistoryLine, Note, Section, parse_note


@dataclass
class MergeResult:
    text: str
    conflicts: list[str]


def _pick(base: list[str], ours: list[str], theirs: list[str], label: str, conflicts: list[str]) -> list[str]:
    if ours == theirs or theirs == base:
        return ours
    if ours == base:
        return theirs
    conflicts.append(label)
    return ours


def _merge_history(base: list[str], ours: list[str], theirs: list[str]) -> list[str]:
    b = [l.strip() for l in base if l.strip()]
    o = [l.strip() for l in ours if l.strip()]
    t = [l.strip() for l in theirs if l.strip()]
    removed_by_theirs = {l for l in b if l not in t}
    merged = [l for l in o if l not in removed_by_theirs]
    merged += [l for l in t if l not in b and l not in merged]

    def key(line: str):
        h = HistoryLine.parse(line)
        return h.date.toordinal() if h else 0

    return sorted(merged, key=key)


def merge3(base_text: str, ours_text: str, theirs_text: str) -> MergeResult:
    base, ours, theirs = parse_note(base_text), parse_note(ours_text), parse_note(theirs_text)
    conflicts: list[str] = []
    preamble = _pick(base.preamble_lines, ours.preamble_lines, theirs.preamble_lines, "맨 위 메모", conflicts)

    out: list[Section] = []
    for o in ours.sections:
        b = base.find(o.heading)
        t = theirs.find(o.heading)
        if t is None:
            if b is not None and b.lines() == o.lines():
                continue  # 다른 쪽에서 지웠고 이쪽은 손대지 않음 → 지운다
            out.append(o)
            continue
        empty = Section(heading=o.heading, heading_line=o.heading_line)
        b = b or empty
        human = _pick(b.human_lines, o.human_lines, t.human_lines, f"'{o.heading}' 본문", conflicts)
        history = _merge_history(b.history_lines, o.history_lines, t.history_lines)
        tail = _pick(b.tail_lines, o.tail_lines, t.tail_lines, f"'{o.heading}' 이력 아래", conflicts)
        marker = o.marker_line or t.marker_line or (HISTORY_MARKER if history else None)
        out.append(Section(o.heading, o.heading_line, human, marker, history, tail))

    for t in theirs.sections:
        if ours.find(t.heading) is None and base.find(t.heading) is None:
            out.append(t)  # 다른 쪽(외부 편집기)에서 새로 만든 섹션

    text = Note(preamble, out).render()
    if not text.endswith("\n"):
        text += "\n"
    return MergeResult(text, conflicts)
