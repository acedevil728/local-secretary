"""설정 우선순위: 기본값 < config/<APP_ENV>.env < .env.local < OS 환경 변수 < overrides."""

from pathlib import Path

import pytest

from app.core.config import ROOT, load_settings

KEYS = ("APP_ENV", "HOST", "PORT", "WEB_HOST", "WEB_PORT", "LLM_ENDPOINTS", "LLM_MODEL", "DATA_DIR", "TELEGRAM_BOT_TOKEN")


@pytest.fixture
def root(tmp_path: Path, monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "dev.env").write_text("DATA_DIR=.dev-data\nPORT=1111\n", encoding="utf-8")
    (tmp_path / "config" / "prod.env").write_text("DATA_DIR=data\n", encoding="utf-8")
    (tmp_path / "config" / "ci.env").write_text("LLM_MODE=fixture\n", encoding="utf-8")
    return tmp_path


def test_defaults_without_local_file(root):
    s = load_settings(root=root)
    assert (s.env, s.host, s.web_host, s.web_port) == ("dev", "127.0.0.1", "127.0.0.1", 5173)
    assert s.port == 1111  # 프로필 값
    assert s.llm_endpoints == ("http://127.0.0.1:11434",)
    assert s.data_dir == root / ".dev-data"


def test_local_file_overrides_profile_and_env_overrides_local(root, monkeypatch):
    (root / ".env.local").write_text(
        "# 주석\nAPP_ENV=prod\nPORT=8100\nWEB_PORT=5273\n"
        "LLM_ENDPOINTS=http://100.64.0.10:11434|qwen2.5:14b-instruct, http://100.64.0.11:11434/\n",
        encoding="utf-8",
    )
    s = load_settings(root=root)
    assert s.env == "prod" and s.data_dir == root / "data"  # .env.local의 APP_ENV가 프로필을 고른다
    assert (s.port, s.web_port) == (8100, 5273)
    assert s.llm_endpoints == ("http://100.64.0.10:11434|qwen2.5:14b-instruct", "http://100.64.0.11:11434")

    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("APP_ENV", "dev")
    s = load_settings(root=root)
    assert (s.env, s.port, s.web_port) == ("dev", 9000, 5273)


def test_ci_profile_ignores_local_file(root):
    (root / ".env.local").write_text("PORT=8100\nTELEGRAM_BOT_TOKEN=secret\n", encoding="utf-8")
    s = load_settings("ci", root=root)
    assert s.port == 8000 and s.telegram_bot_token is None


def test_committed_files_hold_no_addresses_or_secrets():
    """git에 올라가는 프로필에는 주소·포트·비밀이 없어야 한다(그런 값은 .env.local)."""
    forbidden = ("HOST=", "PORT=", "LLM_ENDPOINTS=", "TOKEN=", "PASSWORD=", "NTFY_URL=", "SMTP_HOST=")
    for path in (ROOT / "config").glob("*.env"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("#"):
                continue
            assert not any(line.startswith(k) for k in forbidden), f"{path.name}: {line}"
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for line in example.splitlines():
        if line.startswith(("TELEGRAM_BOT_TOKEN=", "SMTP_PASSWORD=")):
            assert line.split("=", 1)[1] == "", "예시 파일에 실제 비밀이 있으면 안 된다"


def test_config_cli_prints_ports(monkeypatch, capsys):
    from app.cli import main

    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("PORT", "8123")
    monkeypatch.setenv("WEB_PORT", "5299")
    main(["config", "--ports"])
    out = capsys.readouterr().out.splitlines()
    assert out == ["APP_ENV=ci", "HOST=127.0.0.1", "PORT=8123", "WEB_HOST=127.0.0.1", "WEB_PORT=5299"]


def test_config_cli_masks_secrets(monkeypatch, capsys):
    from app.cli import main

    monkeypatch.setenv("APP_ENV", "ci")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    main(["config"])
    out = capsys.readouterr().out
    assert "123:abc" not in out and "****" in out
