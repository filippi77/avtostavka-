"""Недельный турнир на бесплатных фишках.

Каждый понедельник в 00:00 (по TOURNAMENT_TZ) начинается новый турнир: всем
участникам выдаётся одинаковое количество турнирных фишек. Их нельзя купить,
поэтому места в турнире не зависят от покупок за Stars. В конце недели бот
объявляет первые места, а владельцу присылает список победителей — призы
он отправляет сам.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot

from .config import Config
from .db import DB

log = logging.getLogger(__name__)

MEDALS = ("🥇", "🥈", "🥉")


def week_bounds(now: float, tz: str) -> tuple[int, int]:
    """Начало текущей недели (понедельник 00:00) и начало следующей, в unix-времени."""
    local = datetime.fromtimestamp(now, ZoneInfo(tz))
    start = (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=7)
    return int(start.timestamp()), int(end.timestamp())


def is_eligible(cfg: Config, entry: aiosqlite.Row, tournament: aiosqlite.Row) -> bool:
    joined_bot_early = entry["user_created_at"] <= tournament["ends_at"] - cfg.tournament_min_days_in_bot * 86400
    return entry["bets_count"] >= cfg.tournament_min_bets and joined_bot_early


def winners(cfg: Config, standings: list[aiosqlite.Row], tournament: aiosqlite.Row) -> list[aiosqlite.Row]:
    eligible = [e for e in standings if is_eligible(cfg, e, tournament)]
    return eligible[: len(cfg.tournament_prizes)]


def format_ends(cfg: Config, ts: int) -> str:
    # Конец — понедельник 00:00; показываем как "воскресенье 23:59", так понятнее.
    return datetime.fromtimestamp(ts - 60, ZoneInfo(cfg.tournament_tz)).strftime("%d.%m %H:%M")


def prizes_text(cfg: Config) -> str:
    return "\n".join(f"{MEDALS[i] if i < 3 else f'{i + 1}.'} {escape(p)}" for i, p in enumerate(cfg.tournament_prizes))


def rules_text(cfg: Config) -> str:
    return (
        f"Каждому {cfg.tournament_start_chips} турнирных фишек, ставка до {cfg.tournament_max_bet}. "
        f"Ставки: <code>/tbet 209 ♥ 50</code>. Турнирные фишки нельзя купить.\n"
        f"Для приза: минимум {cfg.tournament_min_bets} ставок за неделю "
        f"и быть в боте не меньше {cfg.tournament_min_days_in_bot} дн."
    )


def start_text(cfg: Config, tournament: aiosqlite.Row) -> str:
    return (
        f"🏆 <b>Турнир недели начался!</b> До {format_ends(cfg, tournament['ends_at'])}.\n\n"
        f"{rules_text(cfg)}\n\n<b>Призы:</b>\n{prizes_text(cfg)}"
    )


def results_text(cfg: Config, top: list[aiosqlite.Row]) -> str:
    if not top:
        return "🏁 <b>Турнир недели окончен.</b> В этот раз никто не выполнил условия для приза."
    lines = ["🏁 <b>Турнир недели окончен!</b>\n"]
    for i, e in enumerate(top):
        lines.append(f"{MEDALS[i] if i < 3 else f'{i + 1}.'} {escape(e['name'])} — {e['balance']} · {escape(cfg.tournament_prizes[i])}")
    lines.append("\nПризы отправит администратор в личные сообщения. Новый турнир уже начался!")
    return "\n".join(lines)


def admin_report(cfg: Config, top: list[aiosqlite.Row]) -> str:
    if not top:
        return "Турнир окончен, победителей нет."
    lines = ["🏁 Турнир окончен. Отправьте призы:\n"]
    for i, e in enumerate(top):
        who = f"@{e['username']}" if e["username"] else f'<a href="tg://user?id={e["user_id"]}">{escape(e["name"])}</a>'
        lines.append(f"{i + 1}. {who} (id {e['user_id']}) — {e['balance']} фишек → {escape(cfg.tournament_prizes[i])}")
    return "\n".join(lines)


async def broadcast(bot: Bot, chats: set[int] | list[int], text: str) -> None:
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text)
        except Exception:
            log.exception("failed to send to %s", chat_id)


async def finish(cfg: Config, db: DB, bot: Bot, tournament: aiosqlite.Row) -> None:
    chats = cfg.tournament_chats or set(await db.tournament_chats(tournament["id"]))
    if not await db.finish_tournament(tournament["id"]):
        return
    top = winners(cfg, await db.standings(tournament["id"]), tournament)
    await broadcast(bot, chats, results_text(cfg, top))
    await broadcast(bot, cfg.admins, admin_report(cfg, top))


async def tick(cfg: Config, db: DB, bot: Bot, now: float | None = None) -> None:
    now = time.time() if now is None else now
    current = await db.active_tournament()
    if current and now >= current["ends_at"]:
        await finish(cfg, db, bot, current)
        current = None
    if current is None:
        _, end = week_bounds(now, cfg.tournament_tz)
        tournament_id = await db.create_tournament(int(now), end)
        await broadcast(bot, cfg.tournament_chats, start_text(cfg, await db.get_tournament(tournament_id)))


async def loop(cfg: Config, db: DB, bot: Bot) -> None:
    while True:
        try:
            await tick(cfg, db, bot)
        except Exception:
            log.exception("tournament tick failed")
        await asyncio.sleep(60)
