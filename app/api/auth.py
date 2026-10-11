"""기기별 API 토큰. 쿠키가 아니라 `Authorization: Bearer <토큰>` 헤더로 받는다(웹·앱 공통).

1차 경계는 Tailscale 접속이고, 이건 2차 확인이다. 토큰 원문은 저장하지 않고 SHA-256만 둔다.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, status


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def create(self, name: str) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            rows = [r for r in self._load() if r["name"] != name]
            rows.append({"name": name, "sha256": _digest(token), "created": dt.datetime.now().isoformat(timespec="seconds")})
            self._save(rows)
        return token

    def revoke(self, name: str) -> bool:
        with self._lock:
            rows = self._load()
            kept = [r for r in rows if r["name"] != name]
            self._save(kept)
            return len(kept) != len(rows)

    def list(self) -> list[dict[str, Any]]:
        return [{"name": r["name"], "created": r.get("created")} for r in self._load()]

    def verify(self, token: str) -> str | None:
        d = _digest(token)
        for r in self._load():
            if hmac.compare_digest(r["sha256"], d):
                return r["name"]
        return None


def require_auth(request: Request) -> str | None:
    ctx = request.app.state.ctx
    if not ctx.settings.auth_required:
        return None
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "기기 토큰이 필요해요", headers={"WWW-Authenticate": "Bearer"})
    name = TokenStore(ctx.settings.data_dir / "tokens.json").verify(token.strip())
    if name is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "알 수 없는 토큰이에요", headers={"WWW-Authenticate": "Bearer"})
    return name
