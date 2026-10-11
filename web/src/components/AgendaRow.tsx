import type { Occurrence } from "../api/types";
import { md } from "../lib/dates";
import { CAT, dLabel, IMP, won } from "../lib/format";
import { useApp } from "../state";

/** 할 일 한 줄. compact(전체 보기)는 완료 체크만, 개인 보기는 동작 네 가지. */
export function AgendaRow({ o, compact = false, viewer }: { o: Occurrence; compact?: boolean; viewer?: string }) {
  const app = useApp();
  const shared =
    o.assignees.length > 1 ? <span className="shared">공동 {o.assignees.map(app.name).join("·")}</span> : null;
  const off = !app.online;
  return (
    <li className={`row ${o.status}`}>
      <span className="when">
        <span className="dt mono">{md(o.effective_date)}</span>
        <span className="dd">{dLabel(o)}</span>
      </span>
      <span className="what">
        <button className="t" onClick={() => app.openItem(o.item_id, viewer ?? o.owner_id)}>
          {o.title}
        </button>
        <span className="meta">
          <span className={`imp ${o.importance}`}>{IMP[o.importance]}</span>
          <span>{CAT[o.category]}</span>
          {o.amount != null && <span className="mono">{won(o.amount)}</span>}
          {o.moved && <span>날짜 변경됨</span>}
          {!compact && o.window_days > 0 && <span>±{o.window_days}일</span>}
          {shared}
        </span>
      </span>
      <span className="acts">
        {compact ? (
          <button className="btn icon" disabled={off} onClick={() => app.act("complete", o)} aria-label={`${o.title} 완료`}>
            ✓
          </button>
        ) : (
          <>
            <button className="btn pri" disabled={off} onClick={() => app.act("complete", o)}>
              완료
            </button>
            <button className="btn" disabled={off} onClick={() => app.act("snooze", o)}>
              미루기
            </button>
            <button className="btn" disabled={off} onClick={() => app.act("move", o)}>
              날짜 변경
            </button>
            <button className="btn" disabled={off} onClick={() => app.act("skip", o)}>
              건너뛰기
            </button>
          </>
        )}
      </span>
    </li>
  );
}
