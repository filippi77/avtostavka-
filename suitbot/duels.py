"""Дуэли: двое угадывают масть в картах игрока в нескольких играх подряд.

Вызов — ответом на сообщение соперника: /duel 500 (без ответа — открытый вызов,
принять может любой). Когда вызов принят, у обоих списывается ставка. Под
сообщением дуэли появляются кнопки мастей на ближайшую игру; выбор соперника
скрыт, пока в канале не появился пост этой игры. Кто угадал больше, забирает
обе ставки, при ничьей ставки возвращаются. Бот себе ничего не берёт.
"""

import asyncio
import logging
import time
from html import escape

import aiosqlite
from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from .access import SubscriptionChecker
from .config import Config
from .db import DB
from . import activity, i18n
from .i18n import t
from .parser import SUITS, suit_emoji

log = logging.getLogger(__name__)



async def enabled(cfg: Config, db: DB) -> bool:
    return await db.get_state("duels_enabled", "1" if cfg.duels_enabled else "0") == "1"


def games_label(n: int) -> str:
    if i18n.LANG == "uz":
        return f"{n} ta o'yin"
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} игра"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} игры"
    return f"{n} игр"


def _options(cfg: Config) -> list[str]:
    """Что выбирают в дуэли: масть игрока (баккара) или победителя серии (пенальти)."""
    return ["1", "2"] if cfg.game == "penalty" else list(SUITS)


def _label(cfg: Config, pick: str) -> str:
    return t("duel_p", side=pick) if cfg.game == "penalty" else suit_emoji(pick)


def _name(name: str | None, n: int = 14) -> str:
    name = name or "?"
    return escape(name if len(name) <= n else name[: n - 1] + "…")


def _games(duel: aiosqlite.Row) -> range:
    return range(duel["start_game"], duel["start_game"] + duel["games_total"])


async def _seen(db: DB, duel: aiosqlite.Row, game: int) -> bool:
    return await db.game_seen_since(game, duel["started_at"])


async def current_game(db: DB, duel: aiosqlite.Row) -> int | None:
    """Ближайшая игра дуэли, пост которой ещё не появился, — на неё выбирают масть."""
    for game in _games(duel):
        if not await _seen(db, duel, game):
            return game
    return None


def _scores(duel: aiosqlite.Row, picks: list[aiosqlite.Row]) -> tuple[int, int]:
    hits = {(p["user_id"], p["game"]) for p in picks if p["hit"]}
    return (
        sum(1 for uid, _ in hits if uid == duel["challenger_id"]),
        sum(1 for uid, _ in hits if uid == duel["opponent_id"]),
    )


async def render(cfg: Config, db: DB, duel: aiosqlite.Row) -> tuple[str, InlineKeyboardMarkup | None]:
    c, o = _name(duel["challenger_name"]), _name(duel["opponent_name"]) if duel["opponent_id"] else None
    stake = duel["stake"]
    if duel["status"] in ("pending", "declined", "expired"):
        text = t("duel_challenge", c=c, o=o or t("duel_anyone"), stake=stake, games=games_label(duel["games_total"]))
        if duel["status"] == "pending":
            text += t("duel_pending", minutes=cfg.duel_accept_minutes, c=c)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=("✅ " if n == duel["games_total"] else "") + games_label(n),
                        callback_data=f"duel:len:{duel['id']}:{n}",
                    )
                    for n in cfg.duel_game_options
                ],
                [
                    # Число игр в данных кнопки: если его сменили в последний момент, принятие не пройдёт.
                    InlineKeyboardButton(text=t("duel_btn_accept"), callback_data=f"duel:acc:{duel['id']}:{duel['games_total']}"),
                    InlineKeyboardButton(text=t("duel_btn_decline"), callback_data=f"duel:dec:{duel['id']}"),
                ],
            ])
            return text, kb
        return text + (t("duel_declined") if duel["status"] == "declined" else t("duel_expired")), None

    picks = await db.duel_picks(duel["id"])
    by_game = {(p["user_id"], p["game"]): p for p in picks}
    settled = await db.duel_settled_games(duel["id"])
    sc, so = _scores(duel, picks)
    lines = [t("duel_board", c=c, o=o, stake=stake, sc=sc, so=so)]

    def shown(uid: int, game: int, with_hit: bool) -> str:
        pick = by_game.get((uid, game))
        if not pick:
            return "—" + (" ❌" if with_hit else "")
        return _label(cfg, pick["suit"]) + ((" ✅" if pick["hit"] else " ❌") if with_hit else "")

    current = await current_game(db, duel) if duel["status"] == "active" else None
    for game in _games(duel):
        cid, oid = duel["challenger_id"], duel["opponent_id"]
        if game in settled:
            lines.append(f"#N{game}: {c} {shown(cid, game, True)} · {o} {shown(oid, game, True)}")
        elif await _seen(db, duel, game):
            lines.append(t("duel_live", game=game, c=c, cp=shown(cid, game, False), o=o, op=shown(oid, game, False)))
        elif game == current:
            mark = lambda uid: t("duel_picked") if (uid, game) in by_game else t("duel_thinking")  # noqa: E731
            lines.append(f"<b>#N{game}:</b> {c} {mark(cid)} · {o} {mark(oid)}")
    left = duel["games_total"] - len(settled)

    if duel["status"] == "finished":
        if duel["winner_id"] is None:
            lines.append(t("duel_draw", sc=sc, so=so))
        else:
            winner = c if duel["winner_id"] == duel["challenger_id"] else o
            lines.append(t("duel_won", winner=winner, a=max(sc, so), b=min(sc, so), pot=stake * 2))
        return "\n".join(lines), None

    lines.append(t("duel_left", left=left))
    kb = None
    if current is not None:
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=_label(cfg, s), callback_data=f"duel:p:{duel['id']}:{current}:{s}")
            for s in _options(cfg)
        ]])
    return "\n".join(lines), kb


async def refresh(cfg: Config, db: DB, bot: Bot, duel_id: int) -> None:
    duel = await db.get_duel(duel_id)
    if not duel or not duel["message_id"]:
        return
    text, kb = await render(cfg, db, duel)
    try:
        await bot.edit_message_text(text=text, chat_id=duel["chat_id"], message_id=duel["message_id"], reply_markup=kb)
    except Exception as e:  # "message is not modified" и т.п.
        log.debug("duel edit skipped: %s", e)


async def _finish(cfg: Config, db: DB, bot: Bot, duel: aiosqlite.Row) -> None:
    sc, so = _scores(duel, await db.duel_picks(duel["id"]))
    winner = None if sc == so else (duel["challenger_id"] if sc > so else duel["opponent_id"])
    if not await db.finish_duel(duel["id"], winner):
        return
    await refresh(cfg, db, bot, duel["id"])
    if winner is None:
        text = t("duel_result_draw", c=_name(duel["challenger_name"]), o=_name(duel["opponent_name"]), sc=sc, so=so)
    else:
        name = duel["challenger_name"] if winner == duel["challenger_id"] else duel["opponent_name"]
        text = t("duel_result_won", name=_name(name), a=max(sc, so), b=min(sc, so), pot=duel["stake"] * 2)
    try:
        await bot.send_message(duel["chat_id"], text, reply_to_message_id=duel["message_id"])
    except Exception:
        log.exception("failed to announce duel result")


async def on_game_started(cfg: Config, db: DB, bot: Bot, number: int) -> None:
    """Пост игры появился: выбор на неё закрыт — раскрываем масти и переходим к следующей."""
    for duel in await db.active_duels():
        if number in _games(duel):
            await refresh(cfg, db, bot, duel["id"])


async def on_game_result(cfg: Config, db: DB, bot: Bot, number: int, winning_picks: set[str]) -> None:
    """Итог игры: угадавшими считаются выбравшие что-то из winning_picks
    (масти в картах игрока в баккаре, победитель серии в пенальти)."""
    for duel in await db.active_duels():
        if number not in _games(duel):
            continue
        if await db.settle_duel_game(duel["id"], number, winning_picks):
            if len(await db.duel_settled_games(duel["id"])) >= duel["games_total"]:
                await _finish(cfg, db, bot, duel)
            else:
                await refresh(cfg, db, bot, duel["id"])


async def loop(cfg: Config, db: DB, bot: Bot) -> None:
    while True:
        try:
            now = time.time()
            for duel in await db.stale_pending_duels(int(now) - cfg.duel_accept_minutes * 60):
                if await db.set_duel_status(duel["id"], "expired", only_from="pending"):
                    await refresh(cfg, db, bot, duel["id"])
            for duel in await db.active_duels():
                if duel["started_at"] and now > duel["started_at"] + cfg.duel_max_hours * 3600:
                    await _finish(cfg, db, bot, duel)
        except Exception:
            log.exception("duel loop failed")
        await asyncio.sleep(20)


def build_router(cfg: Config, db: DB, ensure_user, subs: SubscriptionChecker) -> Router:
    router = Router()

    @router.message(Command("duel"))
    async def cmd_duel(message: Message, command: CommandObject, bot: Bot) -> None:
        if not await enabled(cfg, db):
            await message.reply(t("duel_off"))
            return
        if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await message.reply(t("duel_in_chat") + t("duel_how"))
            return
        user = await ensure_user(message.from_user)
        if not await subs.is_subscribed(bot, user["id"]):
            text, kb = subs.prompt()
            await message.reply(text, reply_markup=kb)
            return
        args = (command.args or "").split()
        if not args or not all(a.isdigit() for a in args) or len(args) > 2:
            await message.reply(t("duel_how"))
            return
        stake = int(args[0])
        games = int(args[1]) if len(args) == 2 else cfg.duel_games
        if games not in cfg.duel_game_options:
            await message.reply(t("duel_games_allowed", options=", ".join(map(str, cfg.duel_game_options))))
            return
        if not cfg.duel_min_stake <= stake <= cfg.duel_max_stake:
            await message.reply(t("duel_stake_limits", min=cfg.duel_min_stake, max=cfg.duel_max_stake))
            return
        if user["balance"] < stake:
            await message.reply(t("duel_no_chips", balance=user["balance"]))
            return
        if await db.user_busy_in_duel(user["id"]):
            await message.reply(t("duel_busy_self"))
            return

        opponent = None
        target = message.reply_to_message.from_user if message.reply_to_message else None
        if target and not target.is_bot and target.id != user["id"]:
            opponent = await ensure_user(target)
            if await db.user_busy_in_duel(opponent["id"]):
                await message.reply(t("duel_busy_other", name=_name(opponent["name"])))
                return

        duel_id = await db.create_duel(
            message.chat.id, user["id"], opponent["id"] if opponent else None, stake, games
        )
        text, kb = await render(cfg, db, await db.get_duel(duel_id))
        sent = await message.answer(text, reply_markup=kb)
        await db.set_duel_message(duel_id, sent.message_id)

    @router.callback_query(F.data == "duel:help")
    async def on_help(query: CallbackQuery) -> None:
        await query.answer(t("duel_help_alert"), show_alert=True)

    @router.callback_query(F.data.startswith("duel:len:"))
    async def on_length(query: CallbackQuery, bot: Bot) -> None:
        _, _, duel_id, games = query.data.split(":")
        duel = await db.get_duel(int(duel_id))
        if not duel or duel["status"] != "pending":
            await query.answer(t("duel_stale"), show_alert=True)
            return
        if query.from_user.id != duel["challenger_id"]:
            await query.answer(t("duel_len_owner"), show_alert=True)
            return
        if int(games) in cfg.duel_game_options and await db.set_duel_games(duel["id"], int(games)):
            await query.answer(t("duel_len_set", games=games_label(int(games))))
            await refresh(cfg, db, bot, duel["id"])
        else:
            await query.answer()

    @router.callback_query(F.data.startswith("duel:acc:"))
    async def on_accept(query: CallbackQuery, bot: Bot) -> None:
        parts = query.data.split(":")
        duel = await db.get_duel(int(parts[2]))
        if not duel or duel["status"] != "pending":
            await query.answer(t("duel_stale"), show_alert=True)
            return
        if len(parts) > 3 and int(parts[3]) != duel["games_total"]:
            await query.answer(t("duel_changed", games=games_label(duel["games_total"])), show_alert=True)
            await refresh(cfg, db, bot, duel["id"])
            return
        if not await enabled(cfg, db):
            await query.answer(t("duel_off"), show_alert=True)
            return
        user = await ensure_user(query.from_user)
        if user["id"] == duel["challenger_id"]:
            await query.answer(t("duel_own"), show_alert=True)
            return
        if duel["opponent_id"] and user["id"] != duel["opponent_id"]:
            await query.answer(t("duel_not_you"), show_alert=True)
            return
        if not await subs.is_subscribed(bot, user["id"]):
            await query.answer(subs.alert(), show_alert=True)
            return
        if not duel["opponent_id"] and await db.user_busy_in_duel(user["id"]):
            await query.answer(t("duel_busy_alert"), show_alert=True)
            return
        last = await db.last_game()
        if last is None:
            await query.answer(t("duel_wait_post"), show_alert=True)
            return
        if not await db.accept_duel(duel["id"], user["id"], last + 1):
            await query.answer(t("duel_no_funds", stake=duel["stake"]), show_alert=True)
            return
        for uid in (duel["challenger_id"], user["id"]):
            await activity.add(cfg, db, uid, activity.POINTS_DUEL)
        await query.answer(t("duel_started"))
        await refresh(cfg, db, bot, duel["id"])

    @router.callback_query(F.data.startswith("duel:dec:"))
    async def on_decline(query: CallbackQuery, bot: Bot) -> None:
        duel = await db.get_duel(int(query.data.split(":")[2]))
        if not duel or duel["status"] != "pending":
            await query.answer()
            return
        if query.from_user.id not in (duel["challenger_id"], duel["opponent_id"]):
            await query.answer(t("duel_decline_who"), show_alert=True)
            return
        await db.set_duel_status(duel["id"], "declined", only_from="pending")
        await query.answer(t("duel_cancelled"))
        await refresh(cfg, db, bot, duel["id"])

    @router.callback_query(F.data.startswith("duel:p:"))
    async def on_pick(query: CallbackQuery, bot: Bot) -> None:
        _, _, duel_id, game, suit = query.data.split(":", 4)
        duel = await db.get_duel(int(duel_id))
        if not duel or duel["status"] != "active":
            await query.answer(t("duel_over"), show_alert=True)
            return
        if query.from_user.id not in (duel["challenger_id"], duel["opponent_id"]):
            await query.answer(t("duel_foreign"), show_alert=True)
            return
        if await _seen(db, duel, int(game)):
            await query.answer(t("duel_pick_late", game=game), show_alert=True)
            await refresh(cfg, db, bot, duel["id"])
            return
        await db.set_duel_pick(duel["id"], int(game), query.from_user.id, suit)
        await query.answer(t("duel_pick_ok", suit=_label(cfg, suit), game=game))
        await refresh(cfg, db, bot, duel["id"])

    return router
