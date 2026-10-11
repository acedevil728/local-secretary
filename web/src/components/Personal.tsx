import { api } from "../api/client";
import type { Agenda, Finance, Review } from "../api/types";
import { won } from "../lib/format";
import { useQuery } from "../lib/hooks";
import { pcStyle, useApp, type Tab } from "../state";
import { AgendaRow } from "./AgendaRow";
import { Calendar } from "./Calendar";
import { FinancePanel } from "./FinancePanel";
import { NoteView } from "./NoteView";
import { ReviewCard } from "./ReviewCard";

/** 개인 보기: 선택한 1명을 크게. 일정 탭과 노트 탭. */
export function Personal({ onTab }: { onTab(t: Tab): void }) {
  const app = useApp();
  const pid = app.pid;
  const month = app.today.slice(0, 7);
  const agenda = useQuery(`agenda:${pid}:${app.days}`, () => api.get<Agenda>("/agenda", { people: pid, days: app.days }), app.version);
  const fin = useQuery(`fin:${pid}:${month}`, () => api.get<Finance>("/finance/summary", { people: pid, month }), app.version);
  const reviews = useQuery(`rv:${pid}`, () => api.get<Review[]>("/reviews", { people: pid }), app.version);
  const me = agenda.data?.people[0];
  const c = me?.counts;
  const mon = Number(month.slice(5));

  return (
    <>
      <section className="phead" style={pcStyle(app.color(pid))}>
        <h1>
          <span className="dot" />
          {app.name(pid)}
        </h1>
        <div className="seg" role="group" aria-label="개인 보기 탭">
          <button aria-pressed={app.tab === "schedule"} onClick={() => onTab("schedule")}>
            일정
          </button>
          <button aria-pressed={app.tab === "note"} onClick={() => onTab("note")}>
            노트
          </button>
        </div>
        {c && (
          <span className="counts">
            {c.overdue ? <span className="pill crit">연체 {c.overdue}</span> : <span className="pill">연체 없음</span>}
            <span className="pill warn">오늘 {c.today}</span>
            <span className="pill">7일 내 {c.week}</span>
            {c.reviews > 0 && <span className="pill acc">확인 필요 {c.reviews}</span>}
            <span className="pill">
              {mon}월 납부 예정 <span className="mono">{won(fin.data?.people[0]?.due) || "0원"}</span>
            </span>
          </span>
        )}
        <span className="req">F8</span>
      </section>

      {app.tab === "note" ? (
        <NoteView pid={pid} />
      ) : (
        <div className="split pv">
          <section className="panel">
            <Calendar people={[pid]} compact={false} />
          </section>
          <div className="stack">
            <section className="panel">
              <div className="sec-h">
                <h2>다음 {app.days}일 할 일</h2>
                <span className="req">F7</span>
                <span className="sp muted" style={{ fontSize: 12 }}>
                  {me?.occurrences.length ?? 0}건
                </span>
              </div>
              <ul className="list">
                {me?.occurrences.length ? (
                  me.occurrences.map((o) => <AgendaRow key={o.id} o={o} viewer={pid} />)
                ) : (
                  <li className="empty">다음 {app.days}일 동안 할 일이 없어요.</li>
                )}
              </ul>
            </section>
            {!!reviews.data?.length && (
              <section className="panel">
                <div className="sec-h">
                  <h2>확인 필요</h2>
                  <span className="req">F6</span>
                  <span className="sp muted" style={{ fontSize: 12 }}>
                    LLM이 확신하지 못한 항목
                  </span>
                </div>
                {reviews.data.map((r) => (
                  <ReviewCard key={r.id} r={r} />
                ))}
              </section>
            )}
            {fin.data && <FinancePanel fin={fin.data} />}
          </div>
        </div>
      )}
    </>
  );
}
