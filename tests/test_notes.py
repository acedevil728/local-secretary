import datetime as dt
from pathlib import Path

import pytest

from app.core.config import ROOT
from app.notes.format import (
    HistoryLine,
    SectionNotFound,
    content_hash,
    insert_history,
    normalize_newlines,
    parse_note,
)
from app.notes.merge import merge3
from app.notes.repo import NoteRepository

D = dt.date.fromisoformat

SAMPLE = """# 김의 노트
이번 달 지출 줄이기

## 머리 자르기
나는 5주에 1번 머리를 잘라.
<!-- history -->
- 2026-10-10 완료

## 전기요금
매달 25일 자동이체. 보통 4~6만원.
(공동: 수아)
<!-- history -->
- 2026-09-25 완료 52,300원
- 2026-10-26 완료 48,000원 카드 바꿈 (대시보드)
"""


def test_round_trip_is_identity():
    texts = [SAMPLE, SAMPLE.rstrip("\n"), "", "제목 없는 메모만\n"]
    texts += [p.read_text(encoding="utf-8") for p in (ROOT / "data-sample" / "people").glob("*/notes.md")]
    for t in texts:
        assert parse_note(t).render() == t


def test_sections_and_memo():
    note = parse_note(SAMPLE)
    assert [s.heading for s in note.sections] == ["머리 자르기", "전기요금"]
    assert note.memo == "이번 달 지출 줄이기"
    elec = note.find("전기요금")
    assert elec.shared_names == ["수아"]
    assert "(공동" not in elec.llm_text and "(공동" in elec.human_text


def test_history_lines():
    h = parse_note(SAMPLE).find("전기요금").history
    assert h[0] == HistoryLine(D("2026-09-25"), "done", "완료", 52300, None, "note")
    assert h[1].source == "dashboard" and h[1].memo == "카드 바꿈" and h[1].amount == 48000
    assert HistoryLine.parse("- 2026-10-01 건너뜀").status == "skipped"
    assert HistoryLine.parse("- 언젠가 완료") is None
    assert h[1].render() == "- 2026-10-26 완료 48,000원 카드 바꿈 (대시보드)"


def test_insert_history_only_touches_history_block():
    entry = HistoryLine(D("2026-11-13"), source="dashboard")
    out = insert_history(SAMPLE, "머리 자르기", entry)
    assert "- 2026-10-10 완료\n- 2026-11-13 완료 (대시보드)\n" in out
    before, after = parse_note(SAMPLE), parse_note(out)
    for b, a in zip(before.sections, after.sections):
        assert b.human_lines == a.human_lines
    assert out.replace("- 2026-11-13 완료 (대시보드)\n", "") == SAMPLE


def test_insert_history_keeps_date_order():
    out = insert_history(SAMPLE, "전기요금", HistoryLine(D("2026-08-25"), amount=51000))
    lines = [h.date for h in parse_note(out).find("전기요금").history]
    assert lines == sorted(lines)


def test_insert_history_adds_marker_when_missing():
    text = "## 화분\n4주마다 물주기\n\n## 다음\n내용\n"
    out = insert_history(text, "화분", HistoryLine(D("2026-10-03")))
    assert out == "## 화분\n4주마다 물주기\n<!-- history -->\n- 2026-10-03 완료\n\n## 다음\n내용\n"


def test_insert_history_missing_section():
    with pytest.raises(SectionNotFound):
        insert_history(SAMPLE, "없는 섹션", HistoryLine(D("2026-10-03")))


def test_heading_inside_code_fence_is_not_a_section():
    text = "## 진짜\n본문\n```\n## 가짜\n```\n"
    assert [s.heading for s in parse_note(text).sections] == ["진짜"]


def test_text_after_history_is_preserved_as_tail():
    text = "## 항목\n3주마다\n<!-- history -->\n- 2026-10-01 완료\n덧붙인 메모\n"
    sec = parse_note(text).sections[0]
    assert sec.tail_lines[0] == "덧붙인 메모"
    out = insert_history(text, "항목", HistoryLine(D("2026-10-22")))
    assert out == "## 항목\n3주마다\n<!-- history -->\n- 2026-10-01 완료\n- 2026-10-22 완료\n덧붙인 메모\n"


def test_analysis_hash_ignores_history_and_blank_lines():
    a = parse_note(SAMPLE).find("머리 자르기")
    b = parse_note(insert_history(SAMPLE, "머리 자르기", HistoryLine(D("2026-11-13")))).find("머리 자르기")
    assert a.analysis_hash == b.analysis_hash


def test_merge_keeps_dashboard_lines_and_human_edits():
    base = SAMPLE
    theirs = insert_history(base, "머리 자르기", HistoryLine(D("2026-11-13"), source="dashboard"))
    ours = base.replace("매달 25일 자동이체. 보통 4~6만원.", "매달 25일 자동이체. 보통 5만원.")
    res = merge3(base, ours, theirs)
    assert res.conflicts == []
    assert "보통 5만원" in res.text
    assert "- 2026-11-13 완료 (대시보드)" in res.text


def test_merge_conflict_when_both_edit_same_text():
    base = SAMPLE
    ours = base.replace("5주에 1번", "4주에 1번")
    theirs = base.replace("5주에 1번", "6주에 1번")
    res = merge3(base, ours, theirs)
    assert res.conflicts == ["'머리 자르기' 본문"]


def test_merge_respects_history_removed_by_editor():
    base = SAMPLE
    ours = base.replace("- 2026-09-25 완료 52,300원\n", "")
    theirs = insert_history(base, "머리 자르기", HistoryLine(D("2026-11-13")))
    res = merge3(base, ours, theirs)
    assert "2026-09-25" not in res.text and "2026-11-13" in res.text


def test_repo_writes_utf8_lf_and_reads_crlf_bom(tmp_path: Path):
    repo = NoteRepository(tmp_path)
    path = repo.path_for("kim")
    path.parent.mkdir(parents=True)
    path.write_bytes("﻿## 항목\r\n3주마다\r\n".encode("utf-8"))
    text, h = repo.read("kim")
    assert text == "## 항목\n3주마다\n" and h == content_hash(text)
    repo.write("kim", "## 항목\r\n4주마다", "test")
    assert path.read_bytes() == "## 항목\n4주마다\n".encode("utf-8")
    assert repo.recall(content_hash("## 항목\n4주마다\n")) is not None


def test_normalize_newlines():
    assert normalize_newlines("a\r\nb\rc") == "a\nb\nc"
