// 편집기 안의 노트를 섹션으로 나눈다(저장 전 '바뀐 섹션' 표시와 커서 위치 추적용).
// 정식 파서는 서버(app/notes/format.py)에 있다. 여기는 화면 표시용 근사치다.

export const HISTORY_MARKER = "<!-- history -->";

export interface ClientSection {
  heading: string;
  body: string; // 제목 줄 다음부터 다음 제목 전까지 (정규화)
}

export function splitNote(text: string): { memo: string; sections: ClientSection[] } {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const sections: ClientSection[] = [];
  const memo: string[] = [];
  let cur: { heading: string; body: string[] } | null = null;
  let fence = false;
  for (const line of lines) {
    if (/^\s*(```|~~~)/.test(line)) fence = !fence;
    const m = !fence && line.match(/^## +(.+?)\s*$/);
    if (m) {
      if (cur) sections.push({ heading: cur.heading, body: norm(cur.body) });
      cur = { heading: m[1].trim(), body: [] };
    } else if (cur) cur.body.push(line);
    else memo.push(line);
  }
  if (cur) sections.push({ heading: cur.heading, body: norm(cur.body) });
  return {
    memo: memo.filter((l) => l.trim() && !l.trimStart().startsWith("# ")).join(" "),
    sections,
  };
}

function norm(lines: string[]): string {
  return lines
    .map((l) => l.trimEnd())
    .join("\n")
    .trim();
}

export function sectionAt(text: string, caret: number): string | null {
  const before = text.slice(0, caret).split("\n");
  for (let i = before.length - 1; i >= 0; i--) {
    const m = before[i].match(/^## +(.+?)\s*$/);
    if (m) return m[1].trim();
  }
  return null;
}

export function sectionTemplate(existing: string): { text: string; heading: string } {
  let n = 1;
  let heading = "새 항목";
  while (existing.includes(`## ${heading}\n`) || existing.endsWith(`## ${heading}`)) heading = `새 항목 ${++n}`;
  const base = existing.replace(/\s*$/, "\n");
  return {
    heading,
    text: `${base}\n## ${heading}\n무엇을 언제 하는지 적어 주세요. 예: 3주마다 / 매달 25일 / 11월 30일까지\n${HISTORY_MARKER}\n`,
  };
}

/** 편집기 뒤에 깔리는 강조 레이어용 줄 분류 */
export type LineKind = "title" | "heading" | "marker" | "history" | "app" | "text";

export function classifyLines(text: string): { kind: LineKind; text: string }[] {
  let inHistory = false;
  return text.split("\n").map((line) => {
    if (/^## /.test(line)) {
      inHistory = false;
      return { kind: "heading", text: line };
    }
    if (/^# /.test(line)) return { kind: "title", text: line };
    if (line.trim() === HISTORY_MARKER) {
      inHistory = true;
      return { kind: "marker", text: line };
    }
    if (inHistory && /^- \d{4}-\d{2}-\d{2}/.test(line.trim())) {
      return { kind: line.includes("(대시보드)") ? "app" : "history", text: line };
    }
    if (line.trim()) inHistory = false;
    return { kind: "text", text: line };
  });
}
