"""노트 파일 저장소. UTF-8 + LF 고정, 원자적 쓰기, 쓸 때마다 git 커밋."""

from __future__ import annotations

import datetime as dt
import logging
import os
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from pathlib import Path

from .format import content_hash, normalize_newlines

log = logging.getLogger(__name__)


class GitRepo:
    """노트 폴더의 git 저장소. git이 없으면 조용히 꺼진다."""

    def __init__(self, root: Path, enabled: bool = True) -> None:
        self.root = root
        self.enabled = enabled and shutil.which("git") is not None
        if enabled and not self.enabled:
            log.warning("git을 찾지 못해 노트 커밋을 끕니다")
        self._lock = threading.Lock()

    def _git(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.root), "-c", "core.autocrlf=false", "-c", "core.quotepath=false", *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def ensure(self) -> None:
        if not self.enabled:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            self._git("init", "-q")
            self._git("config", "user.name", "local-secretary")
            self._git("config", "user.email", "local-secretary@localhost")
            attrs = self.root / ".gitattributes"
            if not attrs.exists():
                attrs.write_bytes(b"* text=auto eol=lf\n")
            ignore = self.root / ".gitignore"
            if not ignore.exists():
                ignore.write_bytes(b"app.db*\ntokens.json\n")
            self.commit("노트 저장소 시작")

    def commit(self, message: str) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._git("add", "-A")
            res = self._git("commit", "-q", "-m", message)
            if res.returncode not in (0, 1):
                log.warning("git commit 실패: %s", res.stderr.strip())


class NoteRepository:
    def __init__(self, data_dir: Path, git: GitRepo | None = None) -> None:
        self.data_dir = data_dir
        self.git = git
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._versions: OrderedDict[str, str] = OrderedDict()  # 해시 → 원문 (3-way 병합의 base)
        self._versions_guard = threading.Lock()

    def rel_path(self, person_id: str) -> str:
        return f"people/{person_id}/notes.md"

    def path_for(self, person_id: str) -> Path:
        return self.data_dir / "people" / person_id / "notes.md"

    def person_for_path(self, path: Path) -> str | None:
        try:
            rel = path.resolve().relative_to((self.data_dir / "people").resolve())
        except ValueError:
            return None
        parts = rel.parts
        if len(parts) == 2 and parts[1] == "notes.md" and not parts[0].startswith("_"):
            return parts[0]
        return None

    def archive(self, person_id: str) -> str | None:
        """사람을 지울 때 노트 폴더를 people/_archive/<id>-<시각>/ 으로 옮긴다. 지우지 않는다."""
        src = self.data_dir / "people" / person_id
        if not src.exists():
            return None
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.data_dir / "people" / "_archive" / f"{person_id}-{stamp}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dest))
        return dest.relative_to(self.data_dir).as_posix()

    def lock(self, person_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(person_id, threading.RLock())

    def exists(self, person_id: str) -> bool:
        return self.path_for(person_id).exists()

    def read(self, person_id: str) -> tuple[str, str]:
        path = self.path_for(person_id)
        if not path.exists():
            return "", content_hash("")
        text = normalize_newlines(path.read_bytes().decode("utf-8"))
        h = content_hash(text)
        self.remember(h, text)
        return text, h

    def write(self, person_id: str, text: str, message: str) -> str:
        text = normalize_newlines(text)
        if text and not text.endswith("\n"):
            text += "\n"
        path = self.path_for(person_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(text.encode("utf-8"))
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: 다른 프로그램이 잠깐 잡고 있을 때
                if attempt == 4:
                    tmp.unlink(missing_ok=True)
                    raise
                time.sleep(0.1 * (attempt + 1))
        h = content_hash(text)
        self.remember(h, text)
        if self.git:
            self.git.commit(message)
        return h

    def remember(self, h: str, text: str) -> None:
        with self._versions_guard:
            self._versions[h] = text
            self._versions.move_to_end(h)
            while len(self._versions) > 64:
                self._versions.popitem(last=False)

    def recall(self, h: str) -> str | None:
        with self._versions_guard:
            return self._versions.get(h)
