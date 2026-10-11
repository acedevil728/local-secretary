"""서버 푸시(SSE)용 이벤트 버스. 작업 스레드에서 발행하고 asyncio 구독자에게 전달한다."""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import contextmanager
from typing import Any, Iterator


class EventBus:
    def __init__(self) -> None:
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]] = set()
        self._lock = threading.Lock()

    def publish(self, type_: str, **data: Any) -> None:
        payload = json.dumps({"type": type_, **data}, ensure_ascii=False, default=str)
        with self._lock:
            subs = list(self._subs)
        for loop, queue in subs:
            try:
                loop.call_soon_threadsafe(self._offer, queue, payload)
            except RuntimeError:  # 루프가 이미 닫힘
                with self._lock:
                    self._subs.discard((loop, queue))

    @staticmethod
    def _offer(queue: asyncio.Queue[str], payload: str) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:
            pass  # 느린 구독자는 놓친다. 화면은 재연결할 때 전체를 다시 읽는다.

    @contextmanager
    def listen(self) -> Iterator[asyncio.Queue[str]]:
        """실행 중인 이벤트 루프에서 부른다. 나가면 구독이 풀린다."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        entry = (loop, queue)
        with self._lock:
            self._subs.add(entry)
        try:
            yield queue
        finally:
            with self._lock:
                self._subs.discard(entry)
