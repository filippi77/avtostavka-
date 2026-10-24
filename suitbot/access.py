"""Проверка подписки на канал (REQUIRED_CHANNEL)."""

import logging
import time

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Config

log = logging.getLogger(__name__)

SUBSCRIBED = {"creator", "administrator", "member"}
CACHE_SECONDS = 600


class SubscriptionChecker:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._ok_until: dict[int, float] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.required_channel)

    @property
    def channel_url(self) -> str:
        if self.cfg.required_channel_url:
            return self.cfg.required_channel_url
        return f"https://t.me/{self.cfg.required_channel.lstrip('@')}"

    async def is_subscribed(self, bot: Bot, user_id: int) -> bool:
        if not self.enabled or self._ok_until.get(user_id, 0) > time.time():
            return True
        channel = self.cfg.required_channel
        chat_id = int(channel) if channel.lstrip("-").isdigit() else channel
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except Exception:
            # Чаще всего бот не админ канала. Не блокируем игроков из-за настройки.
            log.warning("cannot check subscription to %s", channel, exc_info=True)
            return True
        ok = member.status in SUBSCRIBED or (member.status == "restricted" and getattr(member, "is_member", False))
        if ok:
            # Положительный ответ кешируем; отрицательный — нет, чтобы после подписки сразу пускало.
            self._ok_until[user_id] = time.time() + CACHE_SECONDS
        return ok

    def prompt(self) -> tuple[str, InlineKeyboardMarkup]:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 Подписаться на канал", url=self.channel_url)],
            [InlineKeyboardButton(text="✅ Я подписался", callback_data="sub:check")],
        ])
        return "Чтобы играть, подпишитесь на канал со статистикой — там выходят все игры.", kb

    def alert(self) -> str:
        return f"Чтобы играть, подпишитесь на канал {self.cfg.required_channel} и нажмите ещё раз."
