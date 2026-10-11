// 서버 푸시(SSE). EventSource는 헤더를 못 넣으므로 fetch 스트림으로 읽는다.

import { authHeaders, connection } from "./client";
import type { StreamEvent } from "./types";

export function subscribe(onEvent: (e: StreamEvent) => void): () => void {
  let stopped = false;
  let ctrl: AbortController | null = null;

  async function loop() {
    while (!stopped) {
      ctrl = new AbortController();
      try {
        const res = await fetch("/api/v1/stream", { headers: authHeaders(), signal: ctrl.signal });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        connection.markOnline();
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += value;
          let i: number;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const chunk = buf.slice(0, i);
            buf = buf.slice(i + 2);
            const data = chunk
              .split("\n")
              .filter((l) => l.startsWith("data:"))
              .map((l) => l.slice(5).trimStart())
              .join("\n");
            if (!data) continue;
            try {
              onEvent(JSON.parse(data) as StreamEvent);
            } catch {
              /* 깨진 이벤트는 버린다 */
            }
          }
        }
      } catch {
        if (stopped) return;
        connection.markOffline();
      }
      await new Promise((r) => setTimeout(r, 3000));
    }
  }

  void loop();
  return () => {
    stopped = true;
    ctrl?.abort();
  };
}
