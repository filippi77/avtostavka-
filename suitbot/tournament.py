"""Турнир на бесплатных фишках.

Админ запускает турнир из панели /admin на выбранное число дней. Всем
участникам выдаётся одинаковое количество турнирных фишек. Их нельзя купить,
поэтому места не зависят от покупок за Stars. Побеждает тот, у кого к концу
турнира больше всего турнирных фишек. Бот объявляет первые места в чате,
а владельцу присылает список победителей — призы он отправляет сам.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone, tzinfo
from html import escape
from zoneinfo import ZoneInfo

import aiosqlite
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .config import Config
from .db import DB
from .i18n import t

log = logging.getLogger(__name__)

MEDALS = ("🥇", "🥈", "🥉")

# На серверах без базы часовых поясов (нет пакета tzdata) ZoneInfo падает.
# Тогда берём постоянное смещение: в Москве нет перехода на летнее время.
_FALLBACK_OFFSETS = {"Europe/Moscow": 3, "Europe/Kyiv": 2, "Europe/Kiev": 2, "Europe/Minsk": 3, "Asia/Tashkent": 5}


def zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name)
    except Exception:
        log.warning("time zone %s not found, using a fixed UTC offset", name)
        return timezone(timedelta(hours=_FALLBACK_OFFSETS.get(name, 0)))


def week_bounds(now: float, tz: str) -> tuple[int, int]:
    """Начало текущей недели (понедельник 00:00) и начало следующей, в unix-времени."""
    local = datetime.fromtimestamp(now, zone(tz))
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
    local = datetime.fromtimestamp(ts, zone(cfg.tournament_tz))
    if local.hour == 0 and local.minute == 0:
        # Полночь показываем как 23:59 предыдущего дня, так понятнее.
        local -= timedelta(minutes=1)
    return local.strftime("%d.%m %H:%M")


def place_mark(i: int) -> str:
    return MEDALS[i] if i < len(MEDALS) else f"{i + 1}."


def prizes_text(cfg: Config) -> str:
    return "\n".join(f"{place_mark(i)} {escape(p)}" for i, p in enumerate(cfg.tournament_prizes))


def rules_text(cfg: Config) -> str:
    rules = t("tour_rules", chips=cfg.tournament_start_chips, max_bet=cfg.tournament_max_bet,
              min_bets=cfg.tournament_min_bets)
    if cfg.tournament_min_days_in_bot:
        rules += t("tour_rules_days", days=cfg.tournament_min_days_in_bot)
    return rules + "."


def start_text(cfg: Config, tournament: aiosqlite.Row) -> str:
    return t("tour_start", ends=format_ends(cfg, tournament["ends_at"]), rules=rules_text(cfg), prizes=prizes_text(cfg))


def results_text(cfg: Config, top: list[aiosqlite.Row]) -> str:
    if not top:
        return t("tour_over_none")
    lines = [t("tour_over")]
    for i, e in enumerate(top):
        lines.append(f"{place_mark(i)} {escape(e['name'])} — {e['balance']} · {escape(cfg.tournament_prizes[i])}")
    lines.append(t("tour_over_footer"))
    return "\n".join(lines)


def admin_report(cfg: Config, top: list[aiosqlite.Row]) -> str:
    if not top:
        return "🏁 Турнир окончен, победителей нет."
    lines = ["🏁 Турнир окончен. Отправьте призы:\n"]
    for i, e in enumerate(top):
        who = f"@{e['username']}" if e["username"] else f'<a href="tg://user?id={e["user_id"]}">{escape(e["name"])}</a>'
        lines.append(f"{i + 1}. {who} (id {e['user_id']}) — {e['balance']} фишек → {escape(cfg.tournament_prizes[i])}")
    return "\n".join(lines)


async def join_keyboard(bot: Bot) -> InlineKeyboardMarkup:
    me = await bot.me()
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("btn_join"), url=f"https://t.me/{me.username}?start=join")
    ]])


async def announce_chats(cfg: Config, db: DB, tournament_id: int | None = None) -> set[int]:
    chats = set(cfg.tournament_chats)
    main_chat = await db.get_state("main_chat")
    if main_chat:
        chats.add(int(main_chat))
    if tournament_id is not None:
        chats.update(await db.tournament_chats(tournament_id))
    return chats


async def broadcast(bot: Bot, chats: set[int] | list[int], text: str, reply_markup=None) -> None:
    for chat_id in chats:
        try:
            await bot.send_message(chat_id, text, reply_markup=reply_markup)
        except Exception:
            log.exception("failed to send to %s", chat_id)


async def start(cfg: Config, db: DB, bot: Bot, ends_at: int) -> aiosqlite.Row | None:
    """Запускает турнир до ends_at. Возвращает None, если турнир уже идёт."""
    if await db.active_tournament():
        return None
    tournament = await db.get_tournament(await db.create_tournament(int(time.time()), ends_at))
    await broadcast(bot, await announce_chats(cfg, db), start_text(cfg, tournament), await join_keyboard(bot))
    return tournament


async def finish(cfg: Config, db: DB, bot: Bot, tournament: aiosqlite.Row) -> None:
    chats = await announce_chats(cfg, db, tournament["id"])
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
    if current is None and cfg.tournament_auto:
        _, end = week_bounds(now, cfg.tournament_tz)
        await start(cfg, db, bot, end)


async def loop(cfg: Config, db: DB, bot: Bot) -> None:
    while True:
        try:
            await tick(cfg, db, bot)
        except Exception:
            log.exception("tournament tick failed")
        await asyncio.sleep(30)
