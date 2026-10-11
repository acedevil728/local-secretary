import { api } from "../api/client";
import type { Agenda, Finance } from "../api/types";
import { won } from "../lib/format";
import { useQuery } from "../lib/hooks";
import { pcStyle, useApp } from "../state";
import { AgendaRow } from "./AgendaRow";
import { Calendar } from "./Calendar";

/** 전체 보기: 여러 명을 한 화면에. 태블릿 가로 화면이나 거실 모니터에 띄워 두는 기준. */
export function Overview() {
  const app = useApp();
  const ids = app.people.map((p) => p.id);
  const month = app.today.slice(0, 7);
  const agenda = useQuery(`agenda:${ids}:${app.days}`, () => api.get<Agenda>("/agenda", { people: ids.join(","), days: app.days }), app.version);
  const fin = useQuery(`fin:${ids}:${month}`, () => api.get<Finance>("/finance/summary", { people: ids.join(","), month }), app.version);
  const mon = Number(month.slice(5));

  return (
    <>
      <section>
        <div className="sec-h">
          <h2>한눈에 보기</h2>
          <span className="req">F8 · F10</span>
        </div>
        <div className="strip">
          {(agenda.data?.people ?? []).map((p) => {
            const c = p.counts;
            return (
              <button key={p.person_id} className="pcard" style={pcStyle(app.color(p.person_id))} onClick={() => app.goPerson(p.person_id, "schedule")}>
                <span className="pname">
                  <span className="dot" />
                  {app.name(p.person_id)}
                </span>
                <span className="counts">
                  {c.overdue > 0 && <span className="pill crit">연체 {c.overdue}</span>}
                  {c.today > 0 && <span className="pill warn">오늘 {c.today}</span>}
                  <span className="pill">
                    다음 {app.days}일 {c.total}건
                  </span>
                  {c.reviews > 0 && <span className="pill acc">확인 필요 {c.reviews}</span>}
                </span>
              </button>
            );
          })}
          {fin.data && (
            <div className="pcard money" style={pcStyle("var(--accent)")}>
              <span className="muted" style={{ fontSize: 12 }}>
                {mon}월 납부 예정 (전체)
              </span>
              <span className="big mono">{won(fin.data.total_due) || "0원"}</span>
              <span className="counts">
                <span className="pill">완료 {won(fin.data.total_paid) || "0원"}</span>
                {fin.data.people
                  .filter((p) => p.due > 0)
                  .map((p) => (
                    <span key={p.person_id} className="pill" style={pcStyle(app.color(p.person_id))}>
                      <span className="dot" style={{ width: 7, height: 7 }} /> {app.name(p.person_id)} {won(p.due)}
                    </span>
                  ))}
              </span>
            </div>
          )}
        </div>
      </section>
      <div className="split ov">
        <section className="panel">
          <Calendar people={ids} compact />
        </section>
        <section>
          <div className="sec-h">
            <h2>사람별 다음 {app.days}일</h2>
            <span className="req">F7</span>
            <span className="sp muted" style={{ fontSize: 12 }}>
              연체 → 우선순위(중요도 × 긴급도)
            </span>
          </div>
          <div className="cols">
            {(agenda.data?.people ?? []).map((p) => {
              const top = p.occurrences.slice(0, 5);
              return (
                <div key={p.person_id} className="col" style={pcStyle(app.color(p.person_id))}>
                  <h3>
                    <span className="dot" />
                    {app.name(p.person_id)}
                    <span className="muted" style={{ fontWeight: 400, fontSize: 12, marginLeft: "auto" }}>
                      {p.occurrences.length}건 중 {top.length}
                    </span>
                  </h3>
                  <ul className="list">
                    {top.length ? (
                      top.map((o) => <AgendaRow key={o.id} o={o} compact viewer={p.person_id} />)
                    ) : (
                      <li className="empty">다음 {app.days}일 동안 할 일이 없어요.</li>
                    )}
                  </ul>
                  {p.occurrences.length > top.length && (
                    <button className="btn sm" style={{ marginTop: 6 }} onClick={() => app.goPerson(p.person_id, "schedule")}>
                      전체 {p.occurrences.length}건 보기
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </section>
      </div>
    </>
  );
}
