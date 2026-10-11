import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Occurrence } from "../api/types";
import { addDays, md } from "../lib/dates";
import { useApp, type ActionKind } from "../state";

interface ActionResult {
  line: string;
  next: Occurrence | null;
}

/** 완료 · 미루기 · 날짜 변경 · 건너뛰기. 규칙을 바꾸는지가 핵심이라 문구로 분명히 알린다. */
export function ActionModal({ kind, occ, presetDate, onClose }: { kind: ActionKind; occ: Occurrence; presetDate?: string; onClose(): void }) {
  const app = useApp();
  const [date, setDate] = useState(presetDate ?? (kind === "move" ? occ.effective_date : app.today));
  const [amount, setAmount] = useState(occ.amount != null ? String(occ.amount) : "");
  const [memo, setMemo] = useState("");
  const [shift, setShift] = useState(false);
  const [busy, setBusy] = useState(false);
  const first = useRef<HTMLElement | null>(null);
  useEffect(() => first.current?.focus(), []);

  const nextMsg = (r: ActionResult) => (r.next ? `다음 일정 ${md(r.next.effective_date)}` : "더 남은 일정 없음");
  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    try {
      await fn();
      app.refresh();
      onClose();
    } catch (e) {
      app.toast(e instanceof Error ? e.message : "처리하지 못했어요");
      setBusy(false);
    }
  };

  const complete = () =>
    run(async () => {
      if (!date) return;
      const r = await api.post<ActionResult>(`/occurrences/${occ.id}/complete`, {
        date,
        amount: amount === "" ? null : Number(amount),
        memo: memo.trim() || null,
      });
      app.toast(`${occ.title} 완료 기록 · ${nextMsg(r)}`);
    });
  const snooze = (n: number) =>
    run(async () => {
      const until = addDays(app.today, n);
      await api.post(`/occurrences/${occ.id}/snooze`, { until });
      app.toast(`${occ.title} 알림을 ${md(until)}까지 미뤘어요`);
    });
  const move = () =>
    run(async () => {
      await api.post(`/occurrences/${occ.id}/reschedule`, { date, shift_future: shift });
      app.toast(shift ? `${occ.title} 기준을 ${md(date)}로 옮겼어요. 이후 회차도 따라 움직여요` : `${occ.title} 이번 회차만 ${md(date)}로 바꿨어요`);
    });
  const skip = () =>
    run(async () => {
      const r = await api.post<ActionResult>(`/occurrences/${occ.id}/skip`);
      app.toast(`${occ.title} ${md(occ.effective_date)} 회차 건너뜀 · ${nextMsg(r)}`);
    });

  const intervalLike = occ.rule_type === "interval" || occ.rule_type === "learned";
  const disabled = busy || !app.online;

  return (
    <>
      <button className="mscrim" aria-label="닫기" onClick={onClose} />
      <div className="modal" role="dialog" aria-modal="true">
        {kind === "complete" && (
          <>
            <h3>{occ.title} 완료</h3>
            <label>
              완료한 날
              <input ref={(el) => (first.current = el)} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            {occ.amount != null && (
              <label>
                금액 (원)
                <input type="number" inputMode="numeric" step={10} value={amount} onChange={(e) => setAmount(e.target.value)} />
              </label>
            )}
            <label>
              메모 (선택)
              <input type="text" placeholder="예: 미용실 바꿈" value={memo} maxLength={200} onChange={(e) => setMemo(e.target.value)} />
            </label>
            <p className="muted" style={{ margin: 0, fontSize: 12 }}>
              노트의 이력 아래에 한 줄이 추가되고 다음 일정이 다시 계산돼요.
            </p>
            <div className="row-b">
              <button className="btn" onClick={onClose}>
                취소
              </button>
              <button className="btn pri" disabled={disabled || !date} onClick={complete}>
                완료 기록
              </button>
            </div>
          </>
        )}
        {kind === "snooze" && (
          <>
            <h3>{occ.title} 미루기</h3>
            <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
              알림만 늦추고 규칙과 기준일은 그대로예요.
            </p>
            <div className="opts">
              <button ref={(el) => (first.current = el)} className="btn" disabled={disabled} onClick={() => snooze(1)}>
                내일까지
              </button>
              <button className="btn" disabled={disabled} onClick={() => snooze(3)}>
                3일
              </button>
              <button className="btn" disabled={disabled} onClick={() => snooze(7)}>
                1주
              </button>
            </div>
            <div className="row-b">
              <button className="btn" onClick={onClose}>
                취소
              </button>
            </div>
          </>
        )}
        {kind === "move" && (
          <>
            <h3>{occ.title} 날짜 변경</h3>
            <label>
              새 날짜
              <input ref={(el) => (first.current = el)} type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="chk">
              <input type="checkbox" checked={shift} disabled={!intervalLike} onChange={(e) => setShift(e.target.checked)} />
              <span>
                이후 일정도 이 날짜 기준으로 계산
                {!intervalLike && (
                  <>
                    <br />
                    <span className="muted" style={{ fontSize: 11.5 }}>
                      달력 고정형 규칙은 이번 회차만 바뀌어요.
                    </span>
                  </>
                )}
              </span>
            </label>
            <div className="row-b">
              <button className="btn" onClick={onClose}>
                취소
              </button>
              <button className="btn pri" disabled={disabled || !date} onClick={move}>
                변경
              </button>
            </div>
          </>
        )}
        {kind === "skip" && (
          <>
            <h3>{occ.title} 건너뛰기</h3>
            <p style={{ margin: 0, fontSize: 13 }}>
              {md(occ.effective_date)} 회차를 건너뛰고 다음 회차를 만들어요. 노트 이력에 "건너뜀"으로 남아요.
            </p>
            <div className="row-b">
              <button className="btn" onClick={onClose}>
                취소
              </button>
              <button ref={(el) => (first.current = el)} className="btn pri" disabled={disabled} onClick={skip}>
                건너뛰기
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
