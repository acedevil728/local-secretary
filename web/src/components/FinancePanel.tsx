import type { Finance } from "../api/types";
import { md } from "../lib/dates";
import { won } from "../lib/format";
import { useApp } from "../state";

/** 공과금·상환 목록과 금액, 지난달 대비 (F10) */
export function FinancePanel({ fin }: { fin: Finance }) {
  const app = useApp();
  const mon = Number(fin.month.slice(5));
  const prevMon = Number(fin.previous.month.slice(5));
  const thisTotal = fin.total_due + fin.total_paid;
  const prevTotal = fin.previous.total_due + fin.previous.total_paid;
  const delta = thisTotal - prevTotal;
  return (
    <section className="panel">
      <div className="sec-h">
        <h2>{mon}월 납부</h2>
        <span className="req">F10</span>
        {prevTotal > 0 && (
          <span className="sp muted" style={{ fontSize: 12 }}>
            {prevMon}월 {won(prevTotal)} 대비 {delta >= 0 ? "+" : "−"}
            {won(Math.abs(delta))}
          </span>
        )}
      </div>
      {fin.rows.length ? (
        <table className="fin">
          <thead>
            <tr>
              <th>날짜</th>
              <th>항목</th>
              <th>상태</th>
              <th className="n">금액</th>
            </tr>
          </thead>
          <tbody>
            {fin.rows.map((r, i) => (
              <tr key={`${r.item_id}-${r.date}-${i}`}>
                <td className="mono">{md(r.date)}</td>
                <td>
                  <button className="t" style={{ border: 0, background: "none", padding: 0, textAlign: "left" }} onClick={() => app.openItem(r.item_id)}>
                    {r.title}
                  </button>
                  {r.assignees.length > 1 && <span className="shared"> 공동</span>}
                </td>
                <td>{r.paid ? <span className="paid">납부</span> : <span className="unpaid">예정</span>}</td>
                <td className="n mono">{won(r.amount)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={3}>남은 금액</td>
              <td className="n mono">{won(fin.total_due) || "0원"}</td>
            </tr>
          </tfoot>
        </table>
      ) : (
        <p className="empty">이번 달 금액이 있는 항목이 없어요.</p>
      )}
    </section>
  );
}
