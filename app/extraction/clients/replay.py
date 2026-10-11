"""ReplayClient: 실제 Ollama 응답을 파일로 녹화해 두고 그대로 재생한다(회귀 테스트).

`LLM_MODE=record`로 한 번 돌려 cassettes를 만들고, 이후 `LLM_MODE=replay`로 재생한다.
프롬프트나 모델이 바뀌면 다시 녹화한다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..prompt import PROMPT_VERSION
from ..schema import LLMResponse, SectionInput
from .base import BadLLMOutput, LLMClient, local_probe
from .ollama import parse_result


class CassetteMissing(BadLLMOutput):
    pass


def cassette_key(section: SectionInput) -> str:
    payload = json.dumps({"v": PROMPT_VERSION, **section.cache_payload()}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class ReplayClient:
    name = "replay"

    def __init__(self, directory: Path, record_with: LLMClient | None = None) -> None:
        self.directory = directory
        self.record_with = record_with

    def health(self) -> bool:
        return self.record_with.health() if self.record_with else True

    def model_ids(self) -> list[str]:
        return self.record_with.model_ids() if self.record_with else ["replay"]

    def active_endpoint(self) -> str | None:
        return self.record_with.active_endpoint() if self.record_with else None

    def probe(self) -> list[dict]:
        return self.record_with.probe() if self.record_with else local_probe("replay")

    def extract(self, section: SectionInput) -> LLMResponse:
        path = self.directory / f"{cassette_key(section)}.json"
        if self.record_with is not None:
            resp = self.record_with.extract(section)
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "prompt_version": PROMPT_VERSION,
                        "model": resp.model,
                        "section": section.cache_payload(),
                        "content": resp.raw if resp.raw is not None else resp.result.model_dump_json(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return resp
        if not path.exists():
            raise CassetteMissing(f"녹화가 없어요: {path.name} ({section.heading})")
        data = json.loads(path.read_text(encoding="utf-8"))
        return LLMResponse(result=parse_result(data["content"]), model=data.get("model", "replay"), raw=data["content"])
