"""알림 채널. 사람마다 `people.json`의 `notify` 목록으로 고른다.

    "notify": [{"type": "app"}, {"type": "ntfy", "topic": "jihun-7f3a"}, {"type": "telegram", "chat_id": "123"}]

ntfy는 tailnet 안의 자체 서버(NTFY_URL)를 권장한다. 텔레그램·이메일은 내용이 집 밖으로 나간다.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Protocol

import httpx

from ..core.bus import EventBus
from ..core.config import Settings

log = logging.getLogger(__name__)


class Channel(Protocol):
    type: str

    def send(self, person: dict[str, Any], cfg: dict[str, Any], title: str, body: str, priority: str) -> None: ...


class AppChannel:
    """앱 안 알림. 열려 있는 화면에 SSE로 띄운다(기록은 notification_log)."""

    type = "app"

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus

    def send(self, person, cfg, title, body, priority) -> None:
        self.bus.publish("notification", person_id=person["id"], title=title, body=body, priority=priority)


class NtfyChannel:
    type = "ntfy"

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def send(self, person, cfg, title, body, priority) -> None:
        r = httpx.post(
            self.base_url,
            json={
                "topic": cfg["topic"],
                "title": title,
                "message": body,
                "priority": 4 if priority == "high" else 3,
                "tags": ["calendar"],
            },
            timeout=10,
        )
        r.raise_for_status()


class TelegramChannel:
    type = "telegram"

    def __init__(self, token: str) -> None:
        self.token = token

    def send(self, person, cfg, title, body, priority) -> None:
        r = httpx.post(
            f"https://api.telegram.org/bot{self.token}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": f"{title}\n{body}"},
            timeout=10,
        )
        r.raise_for_status()


class EmailChannel:
    type = "email"

    def __init__(self, s: Settings) -> None:
        self.s = s

    def send(self, person, cfg, title, body, priority) -> None:
        msg = EmailMessage()
        msg["Subject"] = title
        msg["From"] = self.s.smtp_from or self.s.smtp_user or "local-secretary@localhost"
        msg["To"] = cfg["to"]
        msg.set_content(body)
        with smtplib.SMTP(self.s.smtp_host or "localhost", self.s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password or "")
            smtp.send_message(msg)


def build_channels(settings: Settings, bus: EventBus) -> dict[str, Channel]:
    channels: dict[str, Channel] = {"app": AppChannel(bus)}
    if settings.ntfy_url:
        channels["ntfy"] = NtfyChannel(settings.ntfy_url)
    if settings.telegram_bot_token:
        channels["telegram"] = TelegramChannel(settings.telegram_bot_token)
    if settings.smtp_host:
        channels["email"] = EmailChannel(settings)
    return channels
