from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.context import AppContext, build_context
from app.core.clock import FixedClock
from app.core.config import ROOT, load_settings
from app.main import create_app


@pytest.fixture
def make_ctx(tmp_path: Path):
    made: list[AppContext] = []

    def _make(
        *,
        llm_mode: str = "rule",
        seed: bool = True,
        client=None,
        today: str = "2026-10-10",
        people: list[dict] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> AppContext:
        data = tmp_path / f"data{len(made)}"
        if people is not None:
            data.mkdir(parents=True)
            (data / "people.json").write_text(json.dumps({"people": people}, ensure_ascii=False), encoding="utf-8")
        o = {
            "DATA_DIR": str(data),
            "DATA_SEED": str(ROOT / "data-sample") if seed and people is None else "",
            "LLM_MODE": llm_mode,
            "GIT_ENABLED": "false",
            "AUTH_REQUIRED": "false",
            "JOBS_ENABLED": "false",
            "WATCH_NOTES": "false",
            "WEB_DIST": str(tmp_path / "no-web"),
        }
        o.update(overrides or {})
        s = load_settings("ci", overrides=o)
        ctx = build_context(s, clock=FixedClock(f"{today}T09:00", s.timezone), client=client, threads=False)
        ctx.start()
        ctx.extraction.run_pending()
        made.append(ctx)
        return ctx

    yield _make
    for c in made:
        c.stop()
        c.db.close()


@pytest.fixture
def api(make_ctx):
    """(ctx, TestClient) 쌍을 만든다. 작업 스레드 없이 돌므로 분석은 ctx.extraction.run_pending()으로 진행한다."""
    clients: list[TestClient] = []

    def _api(**kwargs):
        ctx = make_ctx(**kwargs)
        client = TestClient(create_app(ctx=ctx))
        client.__enter__()
        clients.append(client)
        return ctx, client

    yield _api
    for c in clients:
        c.__exit__(None, None, None)


KIM = [{"id": "kim", "name": "김", "color": "#3866d1"}]
