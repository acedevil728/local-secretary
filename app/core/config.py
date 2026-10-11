"""설정 로딩.

우선순위(뒤가 이긴다): 코드 기본값 < `config/<APP_ENV>.env` < `.env.local` < OS 환경 변수 < 호출 인자(overrides)

- `config/<env>.env`: git에 올리는 프로필(dev/prod/ci). 동작 방식만 둔다. **주소·포트·비밀은 두지 않는다.**
- `.env.local`: 이 기기의 값(주소, 포트, Ollama 노드, 토큰, 비밀번호). git에 올리지 않는다. 예시는 `.env.example`.
- `APP_ENV`는 OS 환경 변수 → `.env.local` → `dev` 순으로 정한다.
- `ci` 프로필은 `.env.local`을 읽지 않는다(개발자 PC의 값이 테스트에 섞이지 않게).

경로는 프로젝트 루트 기준 상대 경로를 허용한다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _path(value: str | None, default: str, root: Path = ROOT) -> Path:
    p = Path(value or default)
    return p if p.is_absolute() else root / p


LOCAL_ENV_FILE = ".env.local"


@dataclass(frozen=True)
class Settings:
    env: str
    data_dir: Path
    data_seed: Path | None
    timezone: str
    host: str  # 백엔드(FastAPI) 주소
    port: int
    web_host: str  # 화면 개발 서버(Vite) 주소. start 스크립트와 web/vite.config.ts가 같은 값을 쓴다
    web_port: int

    # LLM
    llm_mode: str  # ollama | fixture | rule | replay | record
    llm_endpoints: tuple[str, ...]
    llm_model: str
    llm_timeout: float
    llm_num_ctx: int
    llm_keep_alive: str
    fixtures_dir: Path
    cassettes_dir: Path
    confidence_threshold: float

    # 스케줄
    horizon_days: int
    clock_fixed: str | None  # 테스트·CI 전용. 운영·개발은 OS 시계(설정 시간대)를 쓴다.

    # 실행
    jobs_enabled: bool
    morning_time: str
    llm_retry_seconds: int
    watch_notes: bool
    git_enabled: bool
    auth_required: bool
    web_dist: Path

    # 알림 채널
    ntfy_url: str | None
    telegram_bot_token: str | None
    smtp_host: str | None
    smtp_port: int
    smtp_user: str | None
    smtp_password: str | None
    smtp_from: str | None

    def with_overrides(self, **kwargs) -> "Settings":
        return replace(self, **kwargs)


def load_settings(
    env: str | None = None,
    overrides: dict[str, str] | None = None,
    root: Path = ROOT,
) -> Settings:
    environ = {k: v for k, v in os.environ.items() if k.isupper()}
    local = _read_env_file(root / LOCAL_ENV_FILE)
    env = env or environ.get("APP_ENV") or local.get("APP_ENV") or "dev"
    values = _read_env_file(root / "config" / f"{env}.env")
    if env != "ci":
        values.update(local)
    values.update(environ)
    if overrides:
        values.update(overrides)
    g = values.get

    endpoints = tuple(e.strip().rstrip("/") for e in (g("LLM_ENDPOINTS") or "").split(",") if e.strip())
    seed = g("DATA_SEED")
    return Settings(
        env=env,
        data_dir=_path(g("DATA_DIR"), "data", root),
        data_seed=_path(seed, seed, root) if seed else None,
        timezone=g("TIMEZONE") or "Asia/Seoul",
        host=g("HOST") or "127.0.0.1",
        port=int(g("PORT") or 8000),
        web_host=g("WEB_HOST") or "127.0.0.1",
        web_port=int(g("WEB_PORT") or 5173),
        llm_mode=(g("LLM_MODE") or "ollama").lower(),
        llm_endpoints=endpoints or ("http://127.0.0.1:11434",),
        llm_model=g("LLM_MODEL") or "qwen2.5:7b-instruct",
        llm_timeout=float(g("LLM_TIMEOUT") or 120),
        llm_num_ctx=int(g("LLM_NUM_CTX") or 4096),
        llm_keep_alive=g("LLM_KEEP_ALIVE") or "30m",
        fixtures_dir=_path(g("FIXTURES_DIR"), "tests/fixtures/extraction", root),
        cassettes_dir=_path(g("CASSETTES_DIR"), "tests/cassettes", root),
        confidence_threshold=float(g("CONFIDENCE_THRESHOLD") or 0.75),
        horizon_days=int(g("HORIZON_DAYS") or 90),
        clock_fixed=g("CLOCK_FIXED") or None,
        jobs_enabled=_bool(g("JOBS_ENABLED"), True),
        morning_time=g("MORNING_TIME") or "07:30",
        llm_retry_seconds=int(g("LLM_RETRY_SECONDS") or 60),
        watch_notes=_bool(g("WATCH_NOTES"), True),
        git_enabled=_bool(g("GIT_ENABLED"), True),
        auth_required=_bool(g("AUTH_REQUIRED"), True),
        web_dist=_path(g("WEB_DIST"), "web/dist", root),
        ntfy_url=g("NTFY_URL") or None,
        telegram_bot_token=g("TELEGRAM_BOT_TOKEN") or None,
        smtp_host=g("SMTP_HOST") or None,
        smtp_port=int(g("SMTP_PORT") or 587),
        smtp_user=g("SMTP_USER") or None,
        smtp_password=g("SMTP_PASSWORD") or None,
        smtp_from=g("SMTP_FROM") or None,
    )
