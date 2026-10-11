import { useState } from "react";
import { api } from "../api/client";
import type { Review } from "../api/types";
import { pct, ruleText } from "../lib/format";
import { useApp } from "../state";

/** 확인 필요 카드: 변경 전/후 비교, 승인 · 노트에서 고치기 · 무시 */
export function ReviewCard({ r }: { r: Review }) {
  const app = useApp();
  const [busy, setBusy] = useState(false);
  const resolve = async (action: "approve" | "dismiss") => {
    setBusy(true);
    try {
      await api.post(`/reviews/${r.id}/resolve`, { action });
      app.toast(
        action === "approve"
          ? `${r.section_heading ?? "항목"} 반영했어요`
          : r.item_id
            ? "제안을 무시했어요. 기존 규칙을 유지해요"
            : "제안을 무시했어요. 이 섹션은 추적하지 않아요",
      );
      app.refresh();
    } catch (e) {
      app.toast(e instanceof Error ? e.message : "처리하지 못했어요");
    } finally {
      setBusy(false);
    }
  };
  const before = r.kind === "new_item" || (!r.item_id && r.kind !== "write_failed") ? "(새 항목)" : ruleText(r.before?.rule ?? null);
  const after = r.proposed?.rule ? ruleText(r.proposed.rule) : "(규칙 없음)";
  return (
    <div className="rv">
      {r.quote && <q>{r.quote}</q>}
      <span style={{ fontSize: 12.5 }}>{r.reason}</span>
      {r.kind !== "write_failed" && (
        <div className="cmp">
          <b>변경 전</b>
          <span>{before}</span>
          <b>제안</b>
          <span>{after}</span>
          {r.confidence != null && (
            <>
              <b>신뢰도</b>
              <span className="mono">{pct(r.confidence)}</span>
            </>
          )}
        </div>
      )}
      <div className="acts" style={{ justifyContent: "flex-start" }}>
        {r.can_approve && (
          <button className="btn pri" disabled={busy || !app.online} onClick={() => resolve("approve")}>
            승인
          </button>
        )}
        {r.section_heading && (
          <button className="btn" onClick={() => app.gotoNote(r.person_id, r.section_heading ?? undefined)}>
            노트에서 고치기
          </button>
        )}
        <button className="btn" disabled={busy || !app.online} onClick={() => resolve("dismiss")}>
          무시
        </button>
      </div>
    </div>
  );
}
