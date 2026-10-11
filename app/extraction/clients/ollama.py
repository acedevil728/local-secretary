"""OllamaClient: 실제 HTTP 호출. 설정된 노드를 순서대로 확인해 응답하는 곳을 쓴다.

`LLM_ENDPOINTS=http://mac-mini:11434|qwen2.5:14b-instruct,http://windows-pc:11434|qwen2.5:7b-instruct`
처럼 노드마다 모델을 따로 줄 수 있다. 모델을 안 적으면 `LLM_MODEL`을 쓴다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from ...core.config import Settings
from ..prompt import build_messages
from ..schema import ExtractionResult, LLMOutput, LLMResponse, SectionInput, ollama_format_schema
from .base import BadLLMOutput, LLMUnavailable

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Node:
    url: str
    model: str


def parse_endpoints(endpoints: tuple[str, ...] | list[str], default_model: str) -> list[Node]:
    nodes = []
    for raw in endpoints:
        url, _, model = raw.partition("|")
        nodes.append(Node(url.strip().rstrip("/"), (model or default_model).strip()))
    return nodes


class OllamaClient:
    name = "ollama"

    def __init__(
        self,
        nodes: list[Node],
        timeout: float = 120.0,
        health_timeout: float = 3.0,
        http: httpx.Client | None = None,
        num_ctx: int = 4096,
        keep_alive: str = "30m",
    ) -> None:
        self.nodes = nodes
        self.timeout = timeout
        self.health_timeout = health_timeout
        self.num_ctx = num_ctx  # 프롬프트(시스템+예시 ≈ 2천 토큰)가 잘리지 않게 명시한다
        self.keep_alive = keep_alive  # 모델과 프롬프트 캐시를 메모리에 남겨 두는 시간
        self._http = http or httpx.Client()
        self._active: Node | None = None

    @classmethod
    def from_settings(cls, s: Settings) -> "OllamaClient":
        return cls(
            parse_endpoints(s.llm_endpoints, s.llm_model),
            timeout=s.llm_timeout,
            num_ctx=s.llm_num_ctx,
            keep_alive=s.llm_keep_alive,
        )

    def model_ids(self) -> list[str]:
        return [f"ollama:{n.model}" for n in self.nodes]

    def active_endpoint(self) -> str | None:
        return self._active.url if self._active else None

    def _probe_node(self, node: Node) -> dict:
        """헬스체크(/api/tags). 노드가 응답하고 모델을 갖고 있어야 쓴다."""
        info = {"url": node.url, "model": node.model, "reachable": False, "has_model": False, "error": None}
        try:
            r = self._http.get(f"{node.url}/api/tags", timeout=self.health_timeout)
            r.raise_for_status()
            models = r.json().get("models", [])
        except (httpx.HTTPError, ValueError) as exc:
            log.info("LLM 노드 %s 응답 없음: %s", node.url, exc)
            info["error"] = "응답 없음"
            return info
        names = {m.get("name") for m in models} | {m.get("model") for m in models}
        info["reachable"] = True
        info["has_model"] = node.model in names or f"{node.model}:latest" in names
        if not info["has_model"]:
            log.warning("LLM 노드 %s에 모델 %s가 없음", node.url, node.model)
            info["error"] = f"모델 {node.model}이(가) 설치되어 있지 않아요 (ollama pull {node.model})"
        return info

    def _alive(self, node: Node) -> bool:
        info = self._probe_node(node)
        return bool(info["reachable"] and info["has_model"])

    def probe(self) -> list[dict]:
        out = [self._probe_node(n) for n in self.nodes]
        ok = next((n for n, i in zip(self.nodes, out) if i["reachable"] and i["has_model"]), None)
        self._active = ok
        return out

    def health(self) -> bool:
        for node in self.nodes:
            if self._alive(node):
                self._active = node
                return True
        self._active = None
        return False

    def extract(self, section: SectionInput) -> LLMResponse:
        last_error: Exception | None = None
        for node in self.nodes:
            if not self._alive(node):
                continue
            self._active = node
            try:
                r = self._http.post(
                    f"{node.url}/api/chat",
                    json={
                        "model": node.model,
                        "messages": build_messages(section),
                        "format": ollama_format_schema(),
                        "stream": False,
                        "keep_alive": self.keep_alive,
                        "options": {"temperature": 0, "num_ctx": self.num_ctx, "num_predict": 512},
                    },
                    timeout=self.timeout,
                )
                r.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                log.warning("LLM 노드 %s 호출 실패, 다음 노드로: %s", node.url, exc)
                last_error = exc
                continue
            try:
                content = r.json()["message"]["content"]
            except (ValueError, KeyError, TypeError) as exc:
                raise BadLLMOutput(f"Ollama 응답 형식이 이상해요: {exc}") from exc
            return LLMResponse(result=parse_result(content), model=f"ollama:{node.model}", raw=content)
        self._active = None
        raise LLMUnavailable(f"응답하는 LLM 노드가 없어요 ({last_error or '헬스체크 실패'})")


def parse_result(content: str) -> ExtractionResult:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise BadLLMOutput(f"JSON이 아니에요: {exc}") from exc
    try:
        if isinstance(data, dict) and "items" not in data and "rule" in data:
            rule = data.get("rule")
            if "done_dates" in data or (isinstance(rule, dict) and "kind" in rule):
                return LLMOutput.model_validate(data).to_result()  # v2 (지금 프롬프트)
            data = {"items": [data]}  # v1 항목 하나만 낸 경우
        return ExtractionResult.model_validate(data)
    except ValidationError as exc:
        raise BadLLMOutput(f"스키마에 맞지 않아요: {exc.errors()[0].get('msg')}") from exc
