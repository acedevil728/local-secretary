import { useState } from "react";
import { setToken } from "../api/client";

/** 기기 토큰 입력. 서버에서 `python -m app token create <기기이름>`으로 만든다. */
export function TokenGate({ onDone }: { onDone(): void }) {
  const [value, setValue] = useState("");
  return (
    <main>
      <form
        className="panel gate"
        onSubmit={(e) => {
          e.preventDefault();
          if (!value.trim()) return;
          setToken(value);
          onDone();
        }}
      >
        <h2 style={{ margin: 0, fontSize: 18 }}>이 기기 등록</h2>
        <p className="muted" style={{ margin: 0, fontSize: 13 }}>
          서버에서 <code>python -m app token create 거실태블릿</code>으로 만든 토큰을 붙여 넣어 주세요. 토큰은 이 기기에만
          저장돼요.
        </p>
        <label className="muted" style={{ display: "grid", gap: 4, fontSize: 12.5 }}>
          기기 토큰
          <input type="password" autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} />
        </label>
        <button className="btn pri" type="submit">
          연결
        </button>
      </form>
    </main>
  );
}
