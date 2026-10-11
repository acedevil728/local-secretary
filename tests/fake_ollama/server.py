"""FakeOllamaServer: Ollama API(/api/tags, /api/chat)를 흉내 내는 작은 HTTP 서버.

지연, 잘못된 JSON, 모델 없음, 다운을 속성으로 주입한다. 답은 RuleMock으로 그럴듯하게 만든다.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.extraction.clients.rule import extract_rule_based
from app.extraction.schema import ExtractionResult, SectionInput


class FakeOllamaServer:
    def __init__(self, models: tuple[str, ...] = ("qwen2.5:7b-instruct",)) -> None:
        self.models = list(models)
        self.delay = 0.0
        self.bad_json = False
        self.http_error: int | None = None
        self.requests: list[dict] = []
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port = 0

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "FakeOllamaServer":
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _send(self, code: int, body: str) -> None:
                data = body.encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path == "/api/tags":
                    self._send(200, json.dumps({"models": [{"name": m, "model": m} for m in server.models]}))
                else:
                    self._send(404, "{}")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                req = json.loads(self.rfile.read(length) or b"{}")
                server.requests.append(req)
                if server.delay:
                    time.sleep(server.delay)
                if server.http_error:
                    self._send(server.http_error, json.dumps({"error": "boom"}))
                    return
                if self.path != "/api/chat":
                    self._send(404, "{}")
                    return
                if server.bad_json:
                    content = "{이건 JSON이 아님"
                else:
                    payload = json.loads(req["messages"][-1]["content"])  # 프롬프트 v2 입력
                    inp = SectionInput(
                        heading=payload["title"],
                        text=payload["text"],
                        today=payload["today"],
                        history_dates=["2000-01-01"] * int(payload.get("record_count") or 0),
                    )
                    content = ExtractionResult(items=[extract_rule_based(inp)]).model_dump_json()
                self._send(200, json.dumps({"model": req.get("model"), "message": {"role": "assistant", "content": content}, "done": True}))

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request, client_address) -> None:
                pass  # 타임아웃 테스트에서 클라이언트가 먼저 끊으면 나는 연결 오류는 무시

        self._httpd = QuietServer(("127.0.0.1", 0), Handler)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None

    def __enter__(self) -> "FakeOllamaServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def dead_url() -> str:
    """아무도 듣지 않는 주소(다운된 노드)."""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return f"http://127.0.0.1:{port}"
