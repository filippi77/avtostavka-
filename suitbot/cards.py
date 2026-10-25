"""Карточки игр: сообщение в чате с кнопками ставок на будущую игру.

Как только в канале появился пост игры N (неважно, идёт она или уже закончилась),
бот сразу выкладывает карточку на игру N+1 — если её номер делится на выбранную
в /admin частоту (каждая, раз в 5, раз в 10). Ставить можно, пока идёт игра N.
Как только появился пост игры N+1, кнопки с карточки убираются, поэтому
поставить во время самой игры нельзя. Сумму ставки и кошелёк игрок выбирает
кнопками один раз — бот запоминает выбор.
"""

import asyncio
import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import betting, duels, rating
from .access import SubscriptionChecker
from .config import Config
from .db import DB
from .i18n import t
from .parser import SUITS, suit_emoji

log = logging.getLogger(__name__)

STAKES = (10, 50, 100, 500)
CARD_FREQUENCIES = (1, 5, 10, 0)  # варианты в панели; 0 — выключено
RATING_COOLDOWN = 5  # секунд между нажатиями «Рейтинг» одним игроком


async def card_every(cfg: Config, db: DB) -> int:
    return int(await db.get_state("card_every", str(cfg.card_every)))


def frequency_label(every: int) -> str:
    return {0: "выключены", 1: "каждая игра"}.get(every, f"раз в {every} игр")


def card_text(cfg: Config, game: int, counts: dict[str, int], closed: bool, tournament_on: bool) -> str:
    picks = " · ".join(f"{suit_emoji(s)} {counts.get(s, 0)}" for s in SUITS)
    lines = [
        t("card_title", game=game, status=t("card_closed") if closed else t("card_open")),
        t("card_odds", suit=f"{cfg.payout_suit:g}", p=f"{cfg.payout_player:g}", t=f"{cfg.payout_tie:g}"),
        t("card_counts", picks=picks, P=counts.get("P", 0), B=counts.get("B", 0), T=counts.get("T", 0)),
    ]
    if not closed:
        lines.append(t("card_hint_tour") if tournament_on else t("card_hint"))
    return "\n".join(lines)


def card_keyboard(game: int, tournament_on: bool, bot_username: str | None, duels_on: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=suit_emoji(s), callback_data=f"b:{game}:suit:{s}") for s in SUITS],
        [
            InlineKeyboardButton(text=betting.side_name(code).capitalize(), callback_data=f"b:{game}:side:{code}")
            for code in betting.SIDES
        ],
        [InlineKeyboardButton(text=f"💰 {s}", callback_data=f"st:{s}") for s in STAKES],
    ]
    if tournament_on:
        rows.append([
            InlineKeyboardButton(text=t("card_btn_tour"), callback_data="w:tour"),
            InlineKeyboardButton(text=t("card_btn_main"), callback_data="w:main"),
        ])
    last_row = [InlineKeyboardButton(text=t("card_btn_rating"), callback_data="rate")]
    if duels_on:
        last_row.append(InlineKeyboardButton(text=t("card_btn_duel"), callback_data="duel:help"))
    if bot_username:
        last_row.append(InlineKeyboardButton(text=t("card_btn_cabinet"), url=f"https://t.me/{bot_username}?start=menu"))
    rows.append(last_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _since(cfg: Config) -> int:
    return int(time.time()) - cfg.bet_ttl_hours * 3600


async def _tournament_on(cfg: Config, db: DB) -> bool:
    return cfg.tournament_enabled and await db.active_tournament() is not None


async def maybe_post(cfg: Config, db: DB, bot: Bot, seen_game: int, chat_id: int) -> None:
    """Вызывается при первом посте игры seen_game — карточка на следующую игру."""
    every = await card_every(cfg, db)
    game = seen_game + 1
    if not every or game % every or await db.get_card(game, chat_id, _since(cfg)):
        return
    on = await _tournament_on(cfg, db)
    me = await bot.me()
    msg = await bot.send_message(chat_id, card_text(cfg, game, {}, False, on), reply_markup=card_keyboard(game, on, me.username, await duels.enabled(cfg, db)))
    await db.save_card(game, chat_id, msg.message_id)


async def refresh(cfg: Config, db: DB, bot: Bot, game: int, chat_id: int, closed: bool = False) -> None:
    card = await db.get_card(game, chat_id, _since(cfg))
    if not card or card["closed"]:
        return
    on = await _tournament_on(cfg, db)
    counts = await db.bet_counts(game, chat_id, _since(cfg))
    me = await bot.me()
    try:
        await bot.edit_message_text(
            text=card_text(cfg, game, counts, closed, on), chat_id=chat_id, message_id=card["message_id"],
            reply_markup=None if closed else card_keyboard(game, on, me.username, await duels.enabled(cfg, db)),
        )
    except Exception as e:  # "message is not modified" и т.п. — не страшно
        log.debug("card edit skipped: %s", e)
    if closed:
        await db.close_card(game, chat_id)


async def close_for_game(cfg: Config, db: DB, bot: Bot, game: int) -> None:
    for card in await db.open_cards_for_game(game, _since(cfg)):
        await refresh(cfg, db, bot, game, card["chat_id"], closed=True)


async def window_loop(cfg: Config, db: DB, bot: Bot) -> None:
    """Закрывает карточку по таймеру BET_WINDOW_SECONDS, не дожидаясь поста игры."""
    while cfg.bet_window_seconds:
        try:
            last = await db.last_game()
            seen = await db.game_seen_at(last) if last is not None else None
            if seen and time.time() > seen + cfg.bet_window_seconds:
                await close_for_game(cfg, db, bot, last + 1)
        except Exception:
            log.exception("card window loop failed")
        await asyncio.sleep(2)


async def confirm_enabled(cfg: Config, db: DB) -> bool:
    return await db.get_state("bet_confirm", "1" if cfg.bet_confirm else "0") == "1"


def build_router(cfg: Config, db: DB, ensure_user, subs: SubscriptionChecker) -> Router:
    router = Router()
    rating_pressed: dict[int, float] = {}
    # Ставка с карточки, ждущая второго нажатия: (игрок, чат, данные кнопки) -> до какого времени.
    pending: dict[tuple[int, int, str], float] = {}

    @router.callback_query(F.data == "rate")
    async def on_rating(query: CallbackQuery) -> None:
        # Рейтинг показывается всплывающим окном только нажавшему — в чат ничего не пишется.
        now = time.time()
        if now - rating_pressed.get(query.from_user.id, 0) < RATING_COOLDOWN:
            await query.answer()
            return
        rating_pressed[query.from_user.id] = now
        await ensure_user(query.from_user)
        await query.answer(await rating.popup_text(cfg, db, query.from_user.id), show_alert=True)

    @router.callback_query(F.data.startswith("st:"))
    async def on_stake(query: CallbackQuery) -> None:
        await ensure_user(query.from_user)
        stake = int(query.data.split(":")[1])
        await db.set_pref(query.from_user.id, stake=stake)
        await query.answer(t("stake_set", stake=stake))

    @router.callback_query(F.data.startswith("w:"))
    async def on_wallet(query: CallbackQuery) -> None:
        await ensure_user(query.from_user)
        wallet = query.data.split(":")[1]
        await db.set_pref(query.from_user.id, wallet=wallet)
        await query.answer(t("wallet_tour_set") if wallet == "tour" else t("wallet_main_set"))

    @router.callback_query(F.data.startswith("b:"))
    async def on_bet(query: CallbackQuery, bot: Bot) -> None:
        _, game, kind, pick = query.data.split(":", 3)
        user = await ensure_user(query.from_user)
        if not await subs.is_subscribed(bot, user["id"]):
            await query.answer(subs.alert(), show_alert=True)
            return
        tournament_bet = user["pref_wallet"] == "tour" and await _tournament_on(cfg, db)
        chat_id = query.message.chat.id if query.message else query.from_user.id

        if await confirm_enabled(cfg, db):
            # Первое нажатие показывает, на что ставка, второе — подтверждает.
            key, now = (user["id"], chat_id, query.data), time.time()
            if pending.pop(key, 0) < now:
                for k in [k for k in pending if k[0] == user["id"] or pending[k] < now]:
                    pending.pop(k)
                pending[key] = now + cfg.bet_confirm_seconds
                coef = cfg.payout(kind, pick)
                stake = user["pref_stake"]
                button = suit_emoji(pick) if kind == "suit" else betting.side_name(pick).capitalize()
                await query.answer(
                    t("bet_confirm", game=game, pick=betting.describe_pick(kind, pick), amount=stake,
                      wallet=t("wallet_tour_word") if tournament_bet else "", coef=f"{coef:g}",
                      win=int(stake * coef), button=button, seconds=cfg.bet_confirm_seconds),
                    show_alert=True,
                )
                return
        try:
            text = await betting.place(
                cfg, db, user["id"], chat_id, int(game), kind, pick, user["pref_stake"], tournament_bet
            )
        except betting.BetError as e:
            await query.answer(str(e), show_alert=True)
            return
        await query.answer(text, show_alert=False)
        await refresh(cfg, db, bot, int(game), chat_id)

    return router
