import { api } from "../api/client";
import type { DayData } from "../api/types";
import { diffDays, longDate, md } from "../lib/dates";
import { won } from "../lib/format";
import { useQuery } from "../lib/hooks";
import { pcStyle, useApp } from "../state";
import { AgendaRow } from "./AgendaRow";

/** 날짜 상세: 해야 할 일 / 허용 구간에 걸친 일 / 한 일. 전체 보기에서는 사람별로 묶는다. */
export function DayDrawer({ date, onClose }: { date: string; onClose(): void }) {
  const app = useApp();
  const people = app.view === "overview" ? app.people.map((p) => p.id) : [app.pid];
  const { data } = useQuery(`day:${date}:${people}`, () => api.get<DayData>("/day", { date, people: people.join(",") }), app.version);
  const past = date < app.today;
  const k = diffDays(date, app.today);
  const rel = k === 0 ? "오늘" : k < 0 ? `${-k}일 전` : `${k}일 후`;
  const groups = (data?.people ?? []).filter((g) => g.due.length || g.near.length || g.done.length);

  return (
    <>
      <button className="scrim" aria-label="닫기" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-label={longDate(date)}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <h2>{longDate(date)}</h2>
          <button className="close" onClick={onClose} style={{ marginLeft: "auto" }}>
            닫기
          </button>
        </div>
        <div className="counts">
          <span className="pill">{rel}</span>
          {data?.holiday && <span className="pill crit">{data.holiday}</span>}
          {app.view === "overview" ? (
            <span className="pill">전체 보기 · 사람별</span>
          ) : (
            <span className="pill" style={pcStyle(app.color(app.pid))}>
              {app.name(app.pid)}
            </span>
          )}
          <span className="req">F7</span>
        </div>
        {data && !groups.length && <p className="empty">이날은 할 일도, 남은 기록도 없어요.</p>}
        {groups.map((g) => {
          const body = (
            <>
              {g.due.length > 0 && (
                <div className="grp">
                  <h3>해야 할 일 · 이날이 기준일</h3>
                  <ul className="list">
                    {g.due.map((o) =>
                      past ? (
                        <li key={o.id} className="drow">
                          <button className="t" onClick={() => app.openItem(o.item_id, g.person_id)}>
                            {o.title}
                          </button>
                          <span className={`pill${o.status === "overdue" ? " crit" : ""}`}>
                            {o.status === "overdue" ? "연체" : o.status === "snoozed" ? "미룸" : "허용 중"}
                          </span>
                          {o.amount != null && <span className="mono muted">{won(o.amount)}</span>}
                          <button className="btn sm" disabled={!app.online} onClick={() => app.act("complete", o, date)}>
                            이날 완료로 기록
                          </button>
                        </li>
                      ) : (
                        <AgendaRow key={o.id} o={o} viewer={g.person_id} />
                      ),
                    )}
                  </ul>
                </div>
              )}
              {g.near.length > 0 && (
                <div className="grp">
                  <h3>허용 구간에 걸친 일</h3>
                  {g.near.map((o) => (
                    <div key={o.id} className="drow">
                      <button className="t" onClick={() => app.openItem(o.item_id, g.person_id)}>
                        {o.title}
                      </button>
                      <span className="muted">
                        기준일 <span className="mono">{md(o.effective_date)}</span> · ±{o.window_days}일 구간 안
                      </span>
                      {date <= app.today && (
                        <button className="btn sm" disabled={!app.online} onClick={() => app.act("complete", o, date)}>
                          이날 완료로 기록
                        </button>
                      )}
                    </div>
                  ))}
                </div>
              )}
              {g.done.length > 0 && (
                <div className="grp">
                  <h3>한 일 · 기록</h3>
                  {g.done.map((e) => (
                    <div key={e.id} className="drow">
                      <span className="ok">{e.status === "done" ? "✓" : "↷"}</span>
                      {e.item_id ? (
                        <button className="t" onClick={() => app.openItem(e.item_id!, g.person_id)}>
                          {e.title}
                        </button>
                      ) : (
                        <b>{e.title}</b>
                      )}
                      <span className="muted">{e.status_text}</span>
                      {e.amount != null && <span className="mono muted">{won(e.amount)}</span>}
                      <span className="muted">
                        {e.source === "dashboard" ? "대시보드" : "노트"}
                        {e.memo ? ` · ${e.memo}` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          );
          return people.length > 1 ? (
            <div key={g.person_id} className="pgrp" style={pcStyle(app.color(g.person_id))}>
              <b>
                <span className="dot" />
                {app.name(g.person_id)}
              </b>
              {body}
            </div>
          ) : (
            <div key={g.person_id} style={{ display: "grid", gap: 16 }}>
              {body}
            </div>
          );
        })}
      </aside>
    </>
  );
}
