"""SQLite 접근.

DB는 노트에서 다시 만들 수 있는 파생 인덱스다. 노트에 없는 값은 사용자가 대시보드에서
바꾼 것(미루기, 날짜 변경, 중요도)과 분석 캐시·확인 필요 대기열·알림 기록뿐이다.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS person (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  color TEXT,
  color_dark TEXT,
  timezone TEXT,
  notify_channels TEXT NOT NULL DEFAULT '[]',
  sort INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS document (
  id INTEGER PRIMARY KEY,
  person_id TEXT NOT NULL UNIQUE REFERENCES person(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  content_hash TEXT,
  parsed_at TEXT
);

-- '## 제목' 단위. LLM 호출과 캐시의 단위.
CREATE TABLE IF NOT EXISTS section (
  id INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES document(id) ON DELETE CASCADE,
  heading TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL DEFAULT '',
  hash TEXT NOT NULL,
  analyzed_hash TEXT,
  ignored_hash TEXT,
  parse_status TEXT NOT NULL DEFAULT 'pending',
  assignees TEXT NOT NULL DEFAULT '[]',
  first_seen TEXT NOT NULL,
  UNIQUE (document_id, heading)
);

CREATE TABLE IF NOT EXISTS tracking_item (
  id INTEGER PRIMARY KEY,
  section_id INTEGER NOT NULL UNIQUE REFERENCES section(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  category TEXT NOT NULL,
  rule_json TEXT NOT NULL,
  importance TEXT NOT NULL,
  lead_days INTEGER NOT NULL,
  window_days INTEGER NOT NULL,
  amount INTEGER,
  assignees TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'active',
  confidence REAL,
  source_quote TEXT,
  prompt_version TEXT,
  model TEXT,
  user_overrides TEXT NOT NULL DEFAULT '{}',
  next_override TEXT,
  updated_at TEXT
);

-- 실제로 한 일. 노트 이력 줄과 1:1 (노트를 다시 읽을 때마다 통째로 다시 만든다).
CREATE TABLE IF NOT EXISTS event (
  id INTEGER PRIMARY KEY,
  section_id INTEGER NOT NULL REFERENCES section(id) ON DELETE CASCADE,
  occurred_on TEXT NOT NULL,
  status TEXT NOT NULL,
  status_text TEXT NOT NULL,
  source TEXT NOT NULL,
  amount INTEGER,
  memo TEXT,
  line TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS event_section ON event(section_id, occurred_on);

-- 앞으로 할 일(아직 끝나지 않은 회차). 끝난 회차는 event로 남는다.
CREATE TABLE IF NOT EXISTS occurrence (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES tracking_item(id) ON DELETE CASCADE,
  raw_date TEXT NOT NULL,
  due_date TEXT NOT NULL,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  state TEXT NOT NULL DEFAULT 'pending',
  override_date TEXT,
  snoozed_until TEXT,
  UNIQUE (item_id, raw_date)
);
CREATE INDEX IF NOT EXISTS occurrence_due ON occurrence(due_date);

CREATE TABLE IF NOT EXISTS review_task (
  id INTEGER PRIMARY KEY,
  person_id TEXT NOT NULL,
  section_id INTEGER REFERENCES section(id) ON DELETE CASCADE,
  item_id INTEGER REFERENCES tracking_item(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  reason TEXT NOT NULL,
  quote TEXT,
  before_json TEXT,
  proposed_json TEXT,
  confidence REAL,
  fingerprint TEXT,
  state TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL,
  resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS notification_log (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL,
  person_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  channel TEXT NOT NULL,
  title TEXT,
  body TEXT,
  sent_at TEXT NOT NULL,
  UNIQUE (key, person_id, kind, channel)
);

CREATE TABLE IF NOT EXISTS extraction_cache (
  key TEXT PRIMARY KEY,
  result_json TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


class Database:
    """스레드마다 연결 하나. 쓰기는 프로세스 안에서 잠금으로 줄 세운다."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._write_lock = threading.RLock()
        with self._write_lock:
            self._conn().executescript(SCHEMA)  # executescript는 스스로 커밋하므로 tx() 밖에서

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA busy_timeout = 5000")
            self._local.conn = conn
            self._local.depth = 0
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """쓰기 트랜잭션. 중첩되면 바깥 트랜잭션에 합쳐진다."""
        conn = self._conn()
        with self._write_lock:
            if self._local.depth == 0:
                conn.execute("BEGIN IMMEDIATE")
            self._local.depth += 1
            try:
                yield conn
            except BaseException:
                self._local.depth -= 1
                if self._local.depth == 0:
                    conn.execute("ROLLBACK")
                raise
            else:
                self._local.depth -= 1
                if self._local.depth == 0:
                    conn.execute("COMMIT")

    def read(self) -> sqlite3.Connection:
        return self._conn()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None


def loads(value: str | None, default: Any = None) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
