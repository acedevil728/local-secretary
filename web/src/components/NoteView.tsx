import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { ConflictBody, NoteAnalysis, NoteDoc, NoteSave, SectionCard } from "../api/types";
import { md } from "../lib/dates";
import { CAT, IMP, pct, ruleCode, ruleText, won } from "../lib/format";
import { useQuery } from "../lib/hooks";
import { classifyLines, sectionAt, sectionTemplate, splitNote } from "../lib/note";
import { store } from "../lib/storage";
import { useApp } from "../state";

/** 저장 전 초안. base = 이 초안이 출발한 노트의 해시(서버가 3-way 병합에 쓴다). */
interface Draft {
  text: string;
  base: string;
}

const drafts = new Map<string, Draft>();
const draftKey = (pid: string) => `pa.draft:${pid}`;

function loadDraft(pid: string): Draft | null {
  return drafts.get(pid) ?? store.getJSON<Draft>(draftKey(pid));
}

/** 노트 탭: 왼쪽 편집기, 오른쪽 섹션별 분석 결과 (F2 · F3 · F6) */
export function NoteView({ pid }: { pid: string }) {
  const app = useApp();
  const [doc, setDoc] = useState<NoteDoc | null>(null);
  const [draft, setDraftState] = useState<Draft | null>(() => loadDraft(pid));
  const [conflict, setConflict] = useState<ConflictBody | null>(null);
  const [saving, setSaving] = useState(false);
  const [cur, setCur] = useState<string | null>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  const pre = useRef<HTMLPreElement>(null);
  const analysis = useQuery(`analysis:${pid}`, () => api.get<NoteAnalysis>(`/people/${pid}/notes/analysis`), app.version);

  const setDraft = useCallback(
    (d: Draft | null) => {
      setDraftState(d);
      if (d) {
        drafts.set(pid, d);
        store.setJSON(draftKey(pid), d);
      } else {
        drafts.delete(pid);
        store.remove(draftKey(pid));
      }
    },
    [pid],
  );

  useEffect(() => {
    setDraftState(loadDraft(pid));
    setConflict(null);
  }, [pid]);

  const loadDoc = useCallback(async () => {
    try {
      setDoc(await api.get<NoteDoc>(`/people/${pid}/notes`));
    } catch {
      /* 오프라인이면 마지막 것 유지 */
    }
  }, [pid]);
  useEffect(() => {
    void loadDoc();
  }, [loadDoc, app.version]);

  const text = draft?.text ?? doc?.content ?? "";
  const dirty = draft != null && draft.text !== doc?.content;

  const jumpTo = useCallback((heading: string, select = false) => {
    const el = ta.current;
    if (!el) return;
    const idx = el.value.indexOf(`## ${heading}`);
    if (idx < 0) return;
    el.focus({ preventScroll: true });
    const s = idx + 3;
    el.setSelectionRange(s, select ? s + heading.length : s);
    const lh = parseFloat(getComputedStyle(el).lineHeight) || 22;
    const line = el.value.slice(0, idx).split("\n").length - 1;
    el.scrollTop = Math.max(0, line * lh - 24);
    if (pre.current) pre.current.scrollTop = el.scrollTop;
    el.scrollIntoView({ block: "nearest" });
    setCur(heading);
  }, []);

  // 다른 화면(확인 필요 카드, 항목 상세)에서 "노트에서 고치기"로 들어왔을 때
  const jumpN = app.noteJump?.pid === pid ? app.noteJump : null;
  useEffect(() => {
    if (jumpN && doc) {
      const t = window.setTimeout(() => jumpTo(jumpN.heading), 30);
      return () => window.clearTimeout(t);
    }
  }, [jumpN, doc, jumpTo]);

  const onChange = (value: string) => {
    if (!doc) return;
    if (value === doc.content) setDraft(null);
    else setDraft({ text: value, base: draft?.base ?? doc.hash });
  };

  const save = async (force = false) => {
    if (!doc) return;
    if (!draft) {
      app.toast("바뀐 내용이 없어요");
      return;
    }
    setSaving(true);
    try {
      const base = force && conflict ? conflict.current_hash : draft.base;
      const r = await api.put<NoteSave>(`/people/${pid}/notes`, { content: draft.text, base_hash: base });
      setDraft(null);
      setConflict(null);
      setDoc({ ...doc, content: r.content ?? draft.text, hash: r.hash });
      app.toast(r.merged ? "저장했어요 · 그사이 대시보드에서 추가된 이력 줄도 합쳤어요" : "저장했어요 · 바뀐 섹션을 분석해요");
      analysis.reload();
      app.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) setConflict(e.body as ConflictBody);
      else app.toast(e instanceof Error ? e.message : "저장하지 못했어요");
    } finally {
      setSaving(false);
    }
  };

  const reparse = async () => {
    try {
      const r = await api.post<{ queued: number }>(`/people/${pid}/notes/reparse`);
      app.toast(`${r.queued}개 섹션을 다시 분석해요`);
      analysis.reload();
    } catch (e) {
      app.toast(e instanceof Error ? e.message : "다시 분석하지 못했어요");
    }
  };

  const onCaret = () => {
    const el = ta.current;
    if (el) setCur(sectionAt(el.value, el.selectionStart));
  };

  const highlighted = useMemo(
    () =>
      classifyLines(text).map((l, i) => (
        <span key={i} className={`l-${l.kind}`}>
          {l.text}
          {"\n"}
        </span>
      )),
    [text],
  );

  return (
    <div className="split nv">
      <section className="panel">
        <div className="sec-h">
          <h2>노트 원문</h2>
          <span className="req">F2</span>
          {dirty && <span className="dirty">저장 안 됨</span>}
          <span className="sp acts">
            <button
              className="btn"
              disabled={!doc}
              onClick={() => {
                const t = sectionTemplate(text);
                setDraft({ text: t.text, base: draft?.base ?? doc!.hash });
                window.setTimeout(() => jumpTo(t.heading, true), 30);
              }}
            >
              항목 추가
            </button>
            {dirty && (
              <button className="btn" onClick={() => setDraft(null)}>
                되돌리기
              </button>
            )}
            <button className="btn pri" disabled={saving || !app.online || !dirty} onClick={() => save()}>
              저장
            </button>
          </span>
        </div>
        {conflict && (
          <div className="banner err" style={{ marginBottom: 10 }}>
            <span>{conflict.detail}</span>
            <button
              className="btn sm"
              onClick={() => {
                setDraft(null);
                setConflict(null);
                void loadDoc();
              }}
            >
              최신 노트 불러오기 (내 변경 버리기)
            </button>
            <button className="btn sm" onClick={() => save(true)}>
              내 내용으로 덮어쓰기
            </button>
          </div>
        )}
        <label htmlFor="note-ed" className="muted" style={{ fontSize: 12, display: "block", marginBottom: 6 }}>
          {doc?.path ?? `people/${pid}/notes.md`}
        </label>
        <div className="ed">
          <pre ref={pre} aria-hidden="true">
            {highlighted}{" "}
          </pre>
          <textarea
            id="note-ed"
            ref={ta}
            spellCheck={false}
            value={text}
            disabled={!doc}
            onChange={(e) => onChange(e.target.value)}
            onScroll={(e) => {
              if (pre.current) pre.current.scrollTop = e.currentTarget.scrollTop;
            }}
            onKeyUp={onCaret}
            onClick={onCaret}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
                e.preventDefault();
                void save();
              }
            }}
          />
        </div>
        <div className="hint">
          <span>
            <code>## 제목</code> 하나가 추적 항목 하나예요. 제목 아래에 하는 일을 평소 말투로 적어요.
          </span>
          <span>
            <code>&lt;!-- history --&gt;</code> 아래 <code>- 날짜 상태 금액</code> 줄(회색)은 앱이 관리해요. 직접 고쳐도 되고, 저장하면
            LLM 없이 바로 반영돼요.
          </span>
          <span>
            공동 담당은 본문에 <code>(공동: 이름)</code> 한 줄을 넣어요. 저장은 Ctrl/⌘ + S.
          </span>
        </div>
      </section>
      <section className="panel">
        <div className="sec-h">
          <h2>분석 결과</h2>
          <span className="req">F3 · F6</span>
          <span className="sp acts">
            <button className="btn sm" disabled={!app.online} onClick={reparse} title="모델이나 프롬프트를 바꾼 뒤 전체를 다시 분석해요">
              다시 분석
            </button>
          </span>
        </div>
        <p className="muted" style={{ fontSize: 12, margin: "0 0 8px" }}>
          카드를 누르면 해당 섹션으로 이동해요.
          {analysis.data?.llm.available === false && " LLM 서버가 응답하지 않아 분석은 기다리는 중이에요."}
        </p>
        <Cards
          text={text}
          saved={doc?.content ?? ""}
          dirty={draft != null}
          cards={analysis.data?.sections ?? []}
          cur={cur}
          llmMode={app.meta.llm.mode}
          onJump={(h) => jumpTo(h)}
        />
      </section>
    </div>
  );
}

function Cards(props: {
  text: string;
  saved: string;
  dirty: boolean;
  cards: SectionCard[];
  cur: string | null;
  llmMode: string;
  onJump(h: string): void;
}) {
  const { memo, sections } = splitNote(props.text);
  const saved = new Map(splitNote(props.saved).sections.map((s) => [s.heading, s.body]));
  const byHeading = new Map(props.cards.map((c) => [c.heading, c]));
  const seen = new Set<string>();
  const reader = props.llmMode === "ollama" ? "로컬 LLM이" : "규칙 추출기(mock)가";

  const card = (key: string, heading: string, pill: React.ReactNode, sub?: React.ReactNode, extra?: React.ReactNode) => (
    <button key={key} className={`ncard${props.cur === heading ? " cur" : ""}`} onClick={() => props.onJump(heading)}>
      <span className="top">
        <b>{heading}</b>
        {pill}
      </span>
      {sub && <span className="sub">{sub}</span>}
      {extra}
    </button>
  );

  const out: React.ReactNode[] = [];
  if (memo) {
    out.push(
      <div key="memo" className="ncard">
        <span className="top">
          <b>제목 없는 메모</b>
          <span className="pill">추적 항목 아님</span>
        </span>
        <span className="sub">{memo.slice(0, 80)}</span>
      </div>,
    );
  }
  sections.forEach((s, i) => {
    const key = `${i}-${s.heading}`;
    if (seen.has(s.heading)) {
      out.push(card(key, s.heading, <span className="pill crit">제목 겹침</span>, "같은 제목의 섹션은 첫 번째만 추적해요. 제목을 바꿔 주세요."));
      return;
    }
    seen.add(s.heading);
    if (props.dirty && saved.get(s.heading) !== s.body) {
      out.push(card(key, s.heading, <span className="dirty">저장 안 됨</span>, "저장하면 이 섹션을 다시 분석해요."));
      return;
    }
    const c = byHeading.get(s.heading);
    if (!c) {
      out.push(card(key, s.heading, <span className="pill">대기</span>));
      return;
    }
    if (c.status === "pending" || c.status === "analyzing") {
      out.push(card(key, s.heading, <span className="pill busy">분석 중…</span>, `${reader} 규칙을 읽고 있어요.`));
      return;
    }
    if (c.status === "waiting_llm") {
      out.push(card(key, s.heading, <span className="pill warn">LLM 대기</span>, "LLM 서버가 켜지면 이어서 분석해요. 일정과 완료 기록은 그대로 돼요."));
      return;
    }
    if (c.review) {
      const r = c.review;
      out.push(
        card(
          key,
          s.heading,
          <span className="pill warn">확인 필요</span>,
          r.reason,
          <span className="sub">
            제안: {r.proposed?.rule ? ruleText(r.proposed.rule) : "(규칙 없음)"}
            {r.confidence != null && (
              <>
                {" "}
                · 신뢰도 <span className="mono">{pct(r.confidence)}</span>
              </>
            )}
          </span>,
        ),
      );
      return;
    }
    if (c.status === "ignored") {
      out.push(card(key, s.heading, <span className="pill">추적 안 함</span>, "제안을 무시한 섹션이에요. 문장을 고쳐 저장하면 다시 분석해요."));
      return;
    }
    if (c.status === "failed") {
      out.push(card(key, s.heading, <span className="pill crit">분석 실패</span>, "잠시 뒤 '다시 분석'을 눌러 주세요."));
      return;
    }
    if (c.item) {
      const it = c.item;
      out.push(
        card(
          key,
          s.heading,
          <span className="pill good">반영됨</span>,
          <>
            {ruleText(it.rule, it.learned_gap_days)} <span className="req">{ruleCode(it.rule)}</span>
          </>,
          <span className="sub">
            다음 <span className="mono">{it.next_date ? md(it.next_date) : "없음"}</span> · {CAT[it.category]} · 중요도 {IMP[it.importance]}
            {it.amount != null && (
              <>
                {" "}
                · <span className="mono">{won(it.amount)}</span>
              </>
            )}{" "}
            · 이력 {it.history_count}건{it.confidence != null && ` · 신뢰도 ${pct(it.confidence)}`}
          </span>,
        ),
      );
      return;
    }
    out.push(card(key, s.heading, <span className="pill">대기</span>));
  });
  if (!out.length) return <p className="empty">아직 섹션이 없어요. "항목 추가"로 시작해 보세요.</p>;
  return <div className="ncards">{out}</div>;
}
