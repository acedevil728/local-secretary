import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { CalendarData, Occurrence } from "../api/types";
import { parts, monthGrid, toDays, WD } from "../lib/dates";
import { useQuery } from "../lib/hooks";
import { pcStyle, useApp } from "../state";

/** 월간 달력. 전체 보기는 사람 색 점, 개인 보기는 항목 이름 + 허용 구간 띠. 날짜를 누르면 그날 상세. */
export function Calendar({ people, compact }: { people: string[]; compact: boolean }) {
  const app = useApp();
  const [month, setMonth] = useState(() => {
    const p = parts(app.today);
    return { y: p.y, m: p.m };
  });
  useEffect(() => {
    const p = parts(app.today);
    setMonth({ y: p.y, m: p.m });
  }, [app.today]);

  const cells = useMemo(() => monthGrid(month.y, month.m), [month]);
  const from = cells[0];
  const to = cells[cells.length - 1];
  const key = `${people.join(",")}:${from}:${to}`;
  const { data } = useQuery(key, () => api.get<CalendarData>("/calendar", { from, to, people: people.join(",") }), app.version);

  const byDay = useMemo(() => {
    const occ = new Map<string, Occurrence[]>();
    for (const o of data?.occurrences ?? []) {
      const list = occ.get(o.effective_date) ?? [];
      list.push(o);
      occ.set(o.effective_date, list);
    }
    const done = new Map<string, NonNullable<typeof data>["events"]>();
    for (const e of data?.events ?? []) {
      const list = done.get(e.date) ?? [];
      list.push(e);
      done.set(e.date, list);
    }
    const win = new Set<string>();
    if (!compact) {
      for (const o of data?.occurrences ?? []) {
        if (o.window_days <= 0 || o.status === "snoozed") continue;
        for (let d = toDays(o.window_start); d <= toDays(o.window_end); d++) win.add(String(d));
      }
    }
    const hol = new Map((data?.holidays ?? []).map((h) => [h.date, h.name]));
    return { occ, done, win, hol };
  }, [data, compact]);

  const shift = (k: number) =>
    setMonth(({ y, m }) => {
      const t = new Date(Date.UTC(y, m + k, 1));
      return { y: t.getUTCFullYear(), m: t.getUTCMonth() };
    });

  return (
    <>
      <div className="sec-h">
        <h2>
          {month.y}년 {month.m + 1}월
        </h2>
        <span className="req">F7</span>
        <span className="sp cal-nav">
          <button onClick={() => shift(-1)} aria-label="이전 달">
            ‹
          </button>
          <button
            onClick={() => {
              const p = parts(app.today);
              setMonth({ y: p.y, m: p.m });
            }}
          >
            오늘
          </button>
          <button onClick={() => shift(1)} aria-label="다음 달">
            ›
          </button>
        </span>
      </div>
      <div className="cal-wrap">
        <div className="cal">
          {[...WD].map((w, i) => (
            <div key={w} className={`wd${i === 0 ? " sun" : i === 6 ? " sat" : ""}`}>
              {w}
            </div>
          ))}
          {cells.map((d) => {
            const p = parts(d);
            const here = byDay.occ.get(d) ?? [];
            const done = byDay.done.get(d) ?? [];
            const holiday = byDay.hol.get(d);
            const cls = ["cell"];
            if (p.m !== month.m) cls.push("out");
            if (d === app.today) cls.push("today");
            if (byDay.win.has(String(toDays(d)))) cls.push("win");
            if (app.pickedDay === d) cls.push("picked");
            const num = ["num"];
            if (p.w === 0) num.push("sun");
            if (p.w === 6) num.push("sat");
            if (holiday) num.push("hol");
            const label = `${p.m + 1}월 ${p.d}일${holiday ? ` ${holiday}` : ""}, 할 일 ${here.length}건, 한 일 ${done.length}건`;
            return (
              <button key={d} className={cls.join(" ")} onClick={() => app.openDay(d)} aria-label={label} title={holiday}>
                <span className={num.join(" ")}>{p.d}</span>
                {compact ? (
                  <span className="dots">
                    {people.map((pid) => {
                      const n = here.filter((o) => o.assignees.includes(pid)).length;
                      const dn = done.filter((e) => e.assignees.includes(pid)).length;
                      return (
                        <span key={pid} style={{ display: "contents" }}>
                          {n > 0 && (
                            <span className="d" style={pcStyle(app.color(pid))}>
                              <i />
                              {n > 1 ? n : ""}
                            </span>
                          )}
                          {dn > 0 && (
                            <span className="d done" style={pcStyle(app.color(pid))}>
                              <i />
                            </span>
                          )}
                        </span>
                      );
                    })}
                  </span>
                ) : (
                  <Chips here={here} done={done} />
                )}
              </button>
            );
          })}
        </div>
      </div>
      {compact ? (
        <div className="legend">
          {people.map((pid) => (
            <span key={pid} style={pcStyle(app.color(pid))}>
              <i className="dot" />
              {app.name(pid)}
            </span>
          ))}
          <span>
            <i className="dot" style={{ background: "transparent", border: "1.5px solid var(--muted)" }} />
            완료 기록
          </span>
          <span>날짜를 누르면 그날 할 일·한 일</span>
        </div>
      ) : (
        <div className="legend">
          <span>
            <i className="sw" style={{ background: "var(--accent-soft)", borderLeft: "3px solid var(--accent)" }} />
            예정 (기준일)
          </span>
          <span>
            <i className="sw" style={{ background: "var(--win)", border: "1px solid var(--line)" }} />
            허용 구간 (기준일 ± n일)
          </span>
          <span>
            <i className="sw" style={{ background: "var(--crit-soft)", borderLeft: "3px solid var(--crit)" }} />
            연체
          </span>
          <span>
            <i className="sw" style={{ border: "1px solid var(--line)" }} />
            <s>완료·건너뜀 기록</s>
          </span>
          <span>날짜를 누르면 그날 할 일·한 일</span>
        </div>
      )}
    </>
  );
}

function Chips({ here, done }: { here: Occurrence[]; done: CalendarData["events"] }) {
  const chips = [
    ...here.map((o) => (
      <span key={`o${o.id}`} className={`chip ${o.importance}${o.status === "overdue" ? " overdue" : ""}`}>
        {o.title}
      </span>
    )),
    ...done.map((e) => (
      <span key={`e${e.id}`} className="chip done">
        {e.title}
      </span>
    )),
  ];
  return (
    <span className="chips">
      {chips.slice(0, 3)}
      {chips.length > 3 && <span className="more">+{chips.length - 3}</span>}
    </span>
  );
}
