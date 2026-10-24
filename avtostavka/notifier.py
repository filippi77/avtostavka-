"""Уведомления в Telegram (необязательно)."""

from __future__ import annotations

import json
import logging
import urllib.request

log = logging.getLogger(__name__)


class Notifier:
    def send(self, text: str) -> None:
        log.info(text)


class TelegramNotifier(Notifier):
    def __init__(self, token: str, chat_id: str, timeout: float = 10.0):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id
        self.timeout = timeout

    def send(self, text: str) -> None:
        super().send(text)
        body = json.dumps({"chat_id": self.chat_id, "text": text}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=self.timeout).close()
        except Exception as exc:  # уведомление не должно ломать торговлю
            log.warning("Telegram: не удалось отправить сообщение: %s", exc)
