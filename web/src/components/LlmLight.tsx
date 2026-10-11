import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { LLMStatus } from "../api/types";
import { useQuery } from "../lib/hooks";
import { useApp } from "../state";

/** 상단 바의 LLM 불. 초록 = 연결됨, 빨강 = 연결 안 됨, 회색 = 확인 전. 누르면 노드별 상태와 '지금 확인'. */
export function LlmLight() {
  const app = useApp();
  const { data, reload } = useQuery("llm", () => api.get<LLMStatus>("/llm"), app.version);
  const st = data ?? app.meta.llm;
  const [open, setOpen] = useState(false);
  const [checking, setChecking] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const state = st.available === true ? "on" : st.available === false ? "off" : "unknown";
  const label = state === "on" ? "LLM 연결됨" : state === "off" ? "LLM 연결 안 됨" : "LLM 확인 중";
  const mock = st.mode !== "ollama";

  const check = async () => {
    setChecking(true);
    try {
      const r = await api.post<LLMStatus>("/llm/check");
      app.toast(r.available ? "LLM 연결됨 · 밀린 분석을 이어서 해요" : "LLM에 연결하지 못했어요");
      reload();
      app.refresh();
    } catch (e) {
      app.toast(e instanceof Error ? e.message : "확인하지 못했어요");
    } finally {
      setChecking(false);
    }
  };

  const checkedAt = st.checked_at
    ? new Date(st.checked_at).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })
    : "아직";

  return (
    <div className="llm" ref={box}>
      <button className="llm-btn" aria-expanded={open} aria-label={`${label}, 분석 대기 ${st.pending}개`} onClick={() => setOpen(!open)}>
        <i className={`light ${state}`} />
        <span>LLM</span>
        {st.pending > 0 && <span className="pill">대기 {st.pending}</span>}
      </button>
      {open && (
        <div className="pop" role="dialog" aria-label="LLM 상태">
          <div className="pop-h">
            <i className={`light ${state}`} />
            <b>{label}</b>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
            {mock
              ? `개발용 mock 모드(${st.mode})예요. 실제 LLM을 부르지 않아요.`
              : "로컬 LLM(Ollama)이 연결되어 있을 때만 바뀐 노트를 분석해요. 꺼져 있으면 분석만 기다리고, 일정·완료 기록·알림은 그대로 돼요. 1분마다 자동으로 다시 확인해요."}
          </p>
          {st.nodes.length > 0 && (
            <ul className="nodes">
              {st.nodes.map((n, i) => (
                <li key={`${n.url}-${i}`}>
                  <i className={`light ${n.reachable && n.has_model ? "on" : "off"}`} />
                  <span className="mono" style={{ overflowWrap: "anywhere" }}>
                    {n.url ?? "로컬"}
                  </span>
                  <span className="muted">{n.model}</span>
                  {n.error && <span className="err">{n.error}</span>}
                </li>
              ))}
            </ul>
          )}
          <dl className="dl" style={{ gridTemplateColumns: "96px 1fr" }}>
            <dt>분석 대기</dt>
            <dd>{st.pending}개 섹션</dd>
            <dt>마지막 확인</dt>
            <dd>{checkedAt}</dd>
          </dl>
          <button className="btn pri" disabled={checking || !app.online} onClick={check}>
            {checking ? "확인 중…" : "지금 확인"}
          </button>
        </div>
      )}
    </div>
  );
}
