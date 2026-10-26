"""Поощрение активных: «Актив недели» и внезапные раздачи.

Актив недели — очки за действия в чате: сообщение от ACTIVITY_MIN_WORDS слов
(не чаще раза в ACTIVITY_MSG_COOLDOWN секунд, чтобы спам не окупался), ответ
другому участнику, ставка, дуэль. Неделя — с понедельника по воскресенье
(TOURNAMENT_TZ). В конце недели бот объявляет топ в чате, а админам присылает
список победителей — звёзды отправляет владелец.

Раздачи — несколько раз в день в случайное время бот пишет в чат «первые N
нажавших получают фишки». Админ может устроить раздачу вручную, в том числе
«звёздную»: первый нажавший получает звёзды от владельца.
"""

import asyncio
import logging
import random
import time
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import tournament as tour
from .access import SubscriptionChecker
from .config import Config
from .db import DB
from .i18n import t, variants

log = logging.getLogger(__name__)

POINTS_MESSAGE = 1
POINTS_REPLY = 1  # сверху за ответ другому участнику
POINTS_BET = 1
POINTS_DUEL = 3


def week_of(cfg: Config, now: float | None = None) -> int:
    return tour.week_bounds(time.time() if now is None else now, cfg.tournament_tz)[0]


async def activity_on(cfg: Config, db: DB) -> bool:
    return await db.get_state("activity_enabled", "1" if cfg.activity_enabled else "0") == "1"


async def drops_on(cfg: Config, db: DB) -> bool:
    return await db.get_state("drops_enabled", "1" if cfg.drops_enabled else "0") == "1"


async def add(cfg: Config, db: DB, user_id: int, points: int) -> None:
    """Очки за ставку, дуэль и т.п."""
    if await activity_on(cfg, db):
        await db.add_activity(week_of(cfg), user_id, points)


# --- актив недели -------------------------------------------------------------

def _who(row) -> str:
    return f"@{row['username']}" if row["username"] else f'<a href="tg://user?id={row["user_id"]}">{escape(row["name"])}</a>'


async def board_text(cfg: Config, db: DB, user_id: int) -> str:
    week = week_of(cfg)
    ends = tour.format_ends(cfg, week + 7 * 86400)
    lines = [t("active_title", ends=ends), t("active_rules", words=cfg.activity_min_words,
                                             min=cfg.activity_min_points), ""]
    top = await db.activity_top(week)
    prizes = cfg.activity_prizes
    if top:
        for i, row in enumerate(top):
            prize = f" · {escape(prizes[i])}" if i < len(prizes) else ""
            lines.append(f"{tour.place_mark(i)} {escape(row['name'])} — {row['points']}{prize}")
    else:
        lines.append(t("active_empty"))
    points, place = await db.activity_of(week, user_id)
    lines.append("\n" + (t("active_me", place=place, points=points) if place else t("active_me_none")))
    return "\n".join(lines)


async def finish_week(cfg: Config, db: DB, bot: Bot, week: int) -> None:
    top = [r for r in await db.activity_top(week, len(cfg.activity_prizes)) if r["points"] >= cfg.activity_min_points]
    if top:
        lines = [t("active_over")]
        lines += [f"{tour.place_mark(i)} {escape(r['name'])} — {r['points']} · {escape(cfg.activity_prizes[i])}"
                  for i, r in enumerate(top)]
        lines.append(t("active_over_footer"))
        chat_text = "\n".join(lines)
        admin_text = "🔥 Актив недели окончен. Отправьте призы:\n\n" + "\n".join(
            f"{i + 1}. {_who(r)} (id {r['user_id']}) — {r['points']} очков → {escape(cfg.activity_prizes[i])}"
            for i, r in enumerate(top)
        )
    else:
        chat_text = t("active_over_none", min=cfg.activity_min_points)
        admin_text = "🔥 Актив недели окончен: никто не набрал минимум очков."
    await tour.broadcast(bot, await tour.announce_chats(cfg, db), chat_text)
    await tour.broadcast(bot, cfg.admins, admin_text)


# --- раздачи ------------------------------------------------------------------

def next_drop_at(cfg: Config, now: float) -> int:
    """Случайное время следующей раздачи в окне DROP_HOURS (по TOURNAMENT_TZ)."""
    start_h, end_h = cfg.drop_hours
    window = max(end_h - start_h, 1) * 3600
    interval = window / max(cfg.drops_per_day, 1)
    at = now + random.uniform(0.5, 1.5) * interval
    local = datetime.fromtimestamp(at, tour.zone(cfg.tournament_tz))
    if not start_h <= local.hour < end_h:
        # За пределами окна — переносим на начало следующего окна плюс случайный сдвиг.
        day_start = local.replace(hour=start_h, minute=0, second=0, microsecond=0)
        if local.hour >= end_h:
            day_start = datetime.fromtimestamp(day_start.timestamp() + 86400, day_start.tzinfo)
        at = day_start.timestamp() + random.uniform(0, interval)
    return int(at)


def drop_text(drop, winners) -> str:
    if drop["amount"]:
        text = t("drop_post", n=drop["winners_max"], amount=drop["amount"])
    else:
        text = t("drop_post_stars", prize=escape(drop["stars_prize"] or ""))
    if winners:
        text += "\n\n" + t("drop_winners", names=", ".join(escape(w["name"]) for w in winners))
    if drop["closed"]:
        text += "\n" + t("drop_over")
    return text


def drop_keyboard(drop) -> InlineKeyboardMarkup | None:
    if drop["closed"]:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=t("drop_btn"), callback_data=f"drop:{drop['id']}")
    ]])


async def post_drop(cfg: Config, db: DB, bot: Bot, stars: bool = False) -> str:
    main_chat = await db.get_state("main_chat")
    if not main_chat:
        return "Чат ещё не выбран."
    if stars:
        drop_id = await db.create_drop(int(main_chat), 0, 1, cfg.drop_stars_prize)
    else:
        drop_id = await db.create_drop(int(main_chat), cfg.drop_amount, cfg.drop_winners)
    drop = await db.get_drop(drop_id)
    msg = await bot.send_message(int(main_chat), drop_text(drop, []), reply_markup=drop_keyboard(drop))
    await db.set_drop_message(drop_id, msg.message_id)
    return "Раздача отправлена в чат."


async def refresh_drop(db: DB, bot: Bot, drop_id: int) -> None:
    drop = await db.get_drop(drop_id)
    if not drop or not drop["message_id"]:
        return
    try:
        await bot.edit_message_text(
            text=drop_text(drop, await db.drop_winners(drop_id)), chat_id=drop["chat_id"],
            message_id=drop["message_id"], reply_markup=drop_keyboard(drop),
        )
    except Exception as e:  # "message is not modified" и т.п.
        log.debug("drop edit skipped: %s", e)


async def loop(cfg: Config, db: DB, bot: Bot) -> None:
    while True:
        try:
            now = time.time()
            # итоги недели
            week = week_of(cfg, now)
            saved = await db.get_state("activity_week")
            if saved is None:
                await db.set_state("activity_week", str(week))
            elif int(saved) != week:
                await db.set_state("activity_week", str(week))
                if await activity_on(cfg, db):
                    await finish_week(cfg, db, bot, int(saved))
            # раздачи
            planned = await db.get_state("drop_next")
            if not planned:
                await db.set_state("drop_next", str(next_drop_at(cfg, now)))
            elif now >= int(planned):
                await db.set_state("drop_next", str(next_drop_at(cfg, now)))
                if await drops_on(cfg, db):
                    await post_drop(cfg, db, bot)
            for drop in await db.open_drops_older_than(int(now) - cfg.drop_minutes * 60):
                if await db.close_drop(drop["id"]):
                    await refresh_drop(db, bot, drop["id"])
        except Exception:
            log.exception("activity loop failed")
        await asyncio.sleep(15)


# --- обработчики --------------------------------------------------------------

def build_router(cfg: Config, db: DB, ensure_user, subs: SubscriptionChecker) -> Router:
    router = Router()

    @router.message(Command("active"))
    @router.message(F.text.in_(variants("btn_active")))
    async def cmd_active(message: Message) -> None:
        await ensure_user(message.from_user)
        await message.reply(await board_text(cfg, db, message.from_user.id))

    @router.callback_query(F.data.startswith("drop:"))
    async def on_claim(query: CallbackQuery, bot: Bot) -> None:
        drop_id = int(query.data.split(":")[1])
        user = await ensure_user(query.from_user)
        if not await subs.is_subscribed(bot, user["id"]):
            await query.answer(subs.alert(), show_alert=True)
            return
        result = await db.claim_drop(drop_id, user["id"])
        drop = await db.get_drop(drop_id)
        if result == "again":
            await query.answer(t("drop_again"), show_alert=True)
            return
        if result == "late":
            await query.answer(t("drop_late"), show_alert=True)
            return
        if drop["amount"]:
            balance = (await db.get_user(user["id"]))["balance"]
            await query.answer(t("drop_ok", amount=drop["amount"], balance=balance), show_alert=True)
        else:
            await query.answer(t("drop_ok_stars", prize=drop["stars_prize"]), show_alert=True)
            who = f"@{user['username']}" if user["username"] else f'<a href="tg://user?id={user["id"]}">{escape(user["name"])}</a>'
            await tour.broadcast(bot, cfg.admins,
                                 f"⭐ Звёздная раздача: первым успел {who} (id {user['id']}). Приз к отправке: {escape(drop['stars_prize'])}.")
        await refresh_drop(db, bot, drop_id)

    # Последним: обычные сообщения в чате — очки активности. Команды и посты
    # канала сюда не доходят, их забирают обработчики выше.
    @router.message(
        F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.text, F.from_user, ~F.sender_chat,
        ~F.text.startswith("/"),
    )
    async def on_chat_message(message: Message) -> None:
        if message.from_user.is_bot or not await activity_on(cfg, db):
            return
        main_chat = await db.get_state("main_chat")
        if main_chat and int(main_chat) != message.chat.id:
            return
        if len(message.text.split()) < cfg.activity_min_words:
            return
        reply = message.reply_to_message
        replied_to_other = bool(reply and reply.from_user and not reply.from_user.is_bot
                                and reply.from_user.id != message.from_user.id)
        points = POINTS_MESSAGE + (POINTS_REPLY if replied_to_other else 0)
        await ensure_user(message.from_user)
        await db.add_activity(week_of(cfg), message.from_user.id, points, message_cooldown=cfg.activity_msg_cooldown)

    return router
