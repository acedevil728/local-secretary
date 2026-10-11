"""외부 편집기(Obsidian 등)로 고친 노트를 감지한다. 저장 직후의 연속 이벤트는 0.5초 묶는다."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .indexer import NoteIndexer
from .repo import NoteRepository

log = logging.getLogger(__name__)


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "NoteWatcher") -> None:
        self.watcher = watcher

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        for p in (getattr(event, "dest_path", None), event.src_path):
            if p:
                pid = self.watcher.notes.person_for_path(Path(str(p)))
                if pid:
                    self.watcher.schedule(pid)


class NoteWatcher:
    def __init__(self, notes: NoteRepository, indexer: NoteIndexer, delay: float = 0.5) -> None:
        self.notes = notes
        self.indexer = indexer
        self.delay = delay
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()
        self._observer: Observer | None = None

    def schedule(self, person_id: str) -> None:
        with self._lock:
            t = self._timers.pop(person_id, None)
            if t:
                t.cancel()
            t = threading.Timer(self.delay, self._fire, args=(person_id,))
            t.daemon = True
            self._timers[person_id] = t
            t.start()

    def _fire(self, person_id: str) -> None:
        with self._lock:
            self._timers.pop(person_id, None)
        try:
            self.indexer.sync_person(person_id)
        except Exception:
            log.exception("노트 다시 읽기 실패: %s", person_id)

    def start(self) -> None:
        root = self.notes.data_dir / "people"
        root.mkdir(parents=True, exist_ok=True)
        self._observer = Observer()
        self._observer.schedule(_Handler(self), str(root), recursive=True)
        self._observer.daemon = True
        self._observer.start()

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._observer = None
        with self._lock:
            for t in self._timers.values():
                t.cancel()
            self._timers.clear()
