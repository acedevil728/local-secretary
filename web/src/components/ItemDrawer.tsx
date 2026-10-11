import { api } from "../api/client";
import type { Importance, ItemDetail } from "../api/types";
import { md } from "../lib/dates";
import { CAT, IMP, ruleCode, ruleText, won } from "../lib/format";
import { classifyLines } from "../lib/note";
import { useQuery } from "../lib/hooks";
import { pcStyle, useApp } from "../state";

/** 오른쪽 패널: 규칙, 이력 타임라인, 원문 문장, 노트 미리보기, 노트 열기 */
export function ItemDrawer({ id, onClose }: { id: number; onClose(): void }) {
  const app = useApp();
  const { data: it, reload } = useQuery(`item:${id}`, () => api.get<ItemDetail>(`/items/${id}`), app.version);

  const setImportance = async (importance: Importance) => {
    try {
      await api.patch(`/items/${id}`, { importance });
      app.toast(`${it?.title} 중요도: ${IMP[importance]}`);
      reload();
      app.refresh();
    } catch (e) {
      app.toast(e instanceof Error ? e.message : "바꾸지 못했어요");
    }
  };

  return (
    <>
      <button className="scrim" aria-label="닫기" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={it ? `${it.title} 상세` : "항목 상세"}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2>{it?.title ?? "불러오는 중…"}</h2>
          <button className="close" onClick={onClose} style={{ marginLeft: "auto" }}>
            닫기
          </button>
        </div>
        {it && (
          <>
            <dl className="dl">
              <dt>담당</dt>
              <dd>
                {it.assignees.map((a) => (
                  <span key={a} style={{ ...pcStyle(app.color(a)), display: "inline-flex", alignItems: "center", gap: 5, marginRight: 10 }}>
                    <span className="dot" />
                    {app.name(a)}
                  </span>
                ))}
              </dd>
              <dt>분류</dt>
              <dd>{CAT[it.category]}</dd>
              <dt>규칙</dt>
              <dd>
                {ruleText(it.rule, it.learned_gap_days)} <span className="req">{ruleCode(it.rule)}</span>
              </dd>
              <dt>중요도</dt>
              <dd>
                <select value={it.importance} disabled={!app.online} onChange={(e) => setImportance(e.target.value as Importance)}>
                  {(Object.keys(IMP) as Importance[]).map((k) => (
                    <option key={k} value={k}>
                      {IMP[k]}
                    </option>
                  ))}
                </select>
              </dd>
              <dt>알림</dt>
              <dd>
                기준일 {it.lead_days}일 전{it.window_days ? ` · 허용 ±${it.window_days}일` : ""}
              </dd>
              {it.amount != null && (
                <>
                  <dt>금액</dt>
                  <dd className="mono">{won(it.amount)}</dd>
                </>
              )}
              <dt>다음 일정</dt>
              <dd className="mono">{it.next.length ? it.next.map((o) => md(o.effective_date)).join(" → ") : "없음 (완료됨)"}</dd>
            </dl>
            <div>
              <div className="sec-h">
                <h2 style={{ fontSize: 13 }}>근거 문장</h2>
                <span className="req">추적 가능성</span>
              </div>
              <div className="quote">{it.source_quote || "(없음)"}</div>
            </div>
            <div>
              <div className="sec-h">
                <h2 style={{ fontSize: 13 }}>이력</h2>
              </div>
              {it.history.length ? (
                <ul className="hist">
                  {it.history.map((h) => (
                    <li key={h.id}>
                      <span className="mono">{h.date}</span>
                      <span>{h.status_text}</span>
                      {h.amount != null && <span className="mono muted">{won(h.amount)}</span>}
                      {h.memo && <span className="muted">{h.memo}</span>}
                      <span className="muted">{h.source === "dashboard" ? "대시보드" : "노트"}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="empty">아직 기록이 없어요.</p>
              )}
            </div>
            {it.note_excerpt && (
              <div>
                <div className="sec-h">
                  <h2 style={{ fontSize: 13 }}>노트 미리보기</h2>
                  <span className="req">F4</span>
                  <span className="sp muted" style={{ fontSize: 11.5 }}>
                    강조 = 대시보드에서 앱이 추가한 줄
                  </span>
                </div>
                <pre className="note">
                  {classifyLines(it.note_excerpt).map((l, i) => (
                    <span key={i} className={l.kind === "app" ? "app" : l.kind === "marker" ? "cm" : l.kind === "history" ? "history" : ""}>
                      {l.text}
                      {"\n"}
                    </span>
                  ))}
                </pre>
                <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>
                  {it.note_path}
                </div>
              </div>
            )}
            <button className="btn" onClick={() => app.gotoNote(it.owner_id, it.heading)}>
              노트 열기
            </button>
          </>
        )}
      </aside>
    </>
  );
}
