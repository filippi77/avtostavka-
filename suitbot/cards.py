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
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from . import activity, betting, duels, rating
from .access import SubscriptionChecker
from .config import Config
from .db import DB
from .i18n import suit_label, t
from .parser import SUITS

log = logging.getLogger(__name__)

# Суммы на кнопках карточки, по рядам. Последняя — для VIP (ставки до VIP_MAX_BET).
STAKE_ROWS = ((50, 100, 500),)
CARD_FREQUENCIES = (1, 5, 10, 0)  # варианты в панели; 0 — выключено
RATING_COOLDOWN = 5  # секунд между нажатиями «Рейтинг» одним игроком


async def card_every(cfg: Config, db: DB) -> int:
    return int(await db.get_state("card_every", str(cfg.card_every)))


def frequency_label(every: int) -> str:
    return {0: "выключены", 1: "каждая игра"}.get(every, f"раз в {every} игр")


SIDE_ICONS = {"P": "🎯", "B": "🏦", "T": "⚖️"}


def bar(n: int, cells: int = 8, full: int = 20) -> str:
    """Полоска заполненности: сколько ставок по сравнению с «полным» залом."""
    filled = min(cells, round(cells * min(n, full) / full))
    return "▓" * filled + "░" * (cells - filled)


def shares(counts: dict[str, int]) -> str:
    """Доля ставок по мастям в процентах: ♠ 30% ♣ 20% …"""
    total = sum(counts.get(s, 0) for s in SUITS)
    if not total:
        return ""
    return " ".join(f"{s} {round(100 * counts.get(s, 0) / total)}%" for s in SUITS)


def status_line(game: int, closed: bool) -> str:
    icon, text = ("🔴", t("card_closed")) if closed else ("🟢", t("card_open"))
    return f"<b>#N{game}</b> · {icon} {text}"


def card_text(cfg: Config, game: int, counts: dict[str, int], closed: bool, tournament_on: bool) -> str:
    total = sum(counts.values())
    lines = [f"🎴 {status_line(game, closed)}", f"{bar(total)} {t('card_total', n=total)}"]
    if not closed and total:
        lines.append(shares(counts))
    return "\n".join(lines)


def card_keyboard(game: int, tournament_on: bool, bot_username: str | None, duels_on: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=suit_label(s), callback_data=f"b:{game}:suit:{s}") for s in SUITS],
        [InlineKeyboardButton(text=f"{SIDE_ICONS[code]} {betting.side_name(code).capitalize()}",
                              callback_data=f"b:{game}:side:{code}") for code in betting.SIDES],
        *[[InlineKeyboardButton(text=f"💰 {x}", callback_data=f"st:{x}") for x in row] for row in STAKE_ROWS],
    ]
    if tournament_on:
        rows.append([
            InlineKeyboardButton(text=t("card_btn_tour"), callback_data="w:tour"),
            InlineKeyboardButton(text=t("card_btn_main"), callback_data="w:main"),
        ])
    last = [InlineKeyboardButton(text=t("card_btn_rating"), callback_data="rate")]
    if duels_on:
        last.append(InlineKeyboardButton(text=t("card_btn_duel"), callback_data="duel:help"))
    if bot_username:
        last.append(InlineKeyboardButton(text=t("card_btn_cabinet"), url=f"https://t.me/{bot_username}?start=menu"))
    rows.append(last)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def picker_keyboard(game: int, info: dict | None, tournament_on: bool, stake: int | None = None,
                    wallet: str | None = None) -> InlineKeyboardMarkup:
    """Выбор ставки в личке: масть или исход, сумма, кошелёк. Текущие сумма и кошелёк отмечены ✓."""
    if info is None:
        bets = [[InlineKeyboardButton(text=suit_label(x), callback_data=f"b:{game}:suit:{x}") for x in SUITS],
                [InlineKeyboardButton(text=f"{SIDE_ICONS[c]} {betting.side_name(c).capitalize()}",
                                      callback_data=f"b:{game}:side:{c}") for c in betting.SIDES]]
    else:
        odds = info["odds"]
        bets = []
        if "1" in odds and "2" in odds:
            bets.append([InlineKeyboardButton(text=f"{betting.describe_pick('win', x, info)} ×{odds[x]:g}",
                                              callback_data=f"b:{game}:win:{x}") for x in ("1", "2")])
        if info["line"] is not None and "O" in odds and "U" in odds:
            bets.append([InlineKeyboardButton(text=f"{betting.describe_pick('total', x + format(info['line'], 'g'))} ×{odds[x]:g}",
                                              callback_data=f"b:{game}:total:{x}") for x in ("O", "U")])
    rows = [*bets, *[[InlineKeyboardButton(text=f"💰 {x}{' ✓' if x == stake else ''}", callback_data=f"st:{x}")
                      for x in row] for row in STAKE_ROWS]]
    if tournament_on:
        rows.append([
            InlineKeyboardButton(text=t("card_btn_tour") + (" ✓" if wallet == "tour" else ""), callback_data="w:tour"),
            InlineKeyboardButton(text=t("card_btn_main") + (" ✓" if wallet == "main" else ""), callback_data="w:main"),
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def pen_card_text(game: int, info: dict, counts: dict[str, int], closed: bool, tournament_on: bool) -> str:
    total = sum(counts.values())
    return "\n".join([
        f"⚽️ {status_line(game, closed)}",
        f"{escape(info['home'])} — {escape(info['away'])}",
        f"{bar(total)} {t('card_total', n=total)}",
    ])


def pen_card_keyboard(game: int, info: dict, tournament_on: bool, bot_username: str | None,
                      duels_on: bool = False) -> InlineKeyboardMarkup:
    odds = info["odds"]
    rows = []
    if "1" in odds and "2" in odds:
        rows.append([InlineKeyboardButton(text=f"{betting.describe_pick('win', x, info)} ×{odds[x]:g}",
                                          callback_data=f"b:{game}:win:{x}") for x in ("1", "2")])
    if info["line"] is not None and "O" in odds and "U" in odds:
        rows.append([InlineKeyboardButton(text=f"{betting.describe_pick('total', x + format(info['line'], 'g'))} ×{odds[x]:g}",
                                          callback_data=f"b:{game}:total:{x}") for x in ("O", "U")])
    base = card_keyboard(game, tournament_on, bot_username, duels_on).inline_keyboard
    return InlineKeyboardMarkup(inline_keyboard=[*rows, *base[2:]])  # суммы, кошелёк и нижний ряд — как в баккаре


async def _render(cfg: Config, db: DB, game: int, counts: dict[str, int], closed: bool, me_username: str | None):
    """Текст и кнопки карточки для текущей игры (баккара или пенальти). None — нечего показывать."""
    on = await _tournament_on(cfg, db)
    duels_on = await duels.enabled(cfg, db)
    if cfg.game == "penalty":
        info = await db.get_penalty_game(game, _since(cfg))
        if not info:
            return None
        kb = None if closed else pen_card_keyboard(game, info, on, me_username, duels_on)
        return pen_card_text(game, info, counts, closed, on), kb
    kb = None if closed else card_keyboard(game, on, me_username, duels_on)
    return card_text(cfg, game, counts, closed, on), kb


async def send_picker(cfg: Config, db: DB, bot: Bot, chat_id: int, game: int) -> None:
    """Личный выбор ставки на игру: приходит игроку в личку по кнопке из чата."""
    if await db.game_seen_since(game, _since(cfg)):
        await bot.send_message(chat_id, t("picker_closed", game=game))
        return
    on = await _tournament_on(cfg, db)
    info = None
    if cfg.game == "penalty":
        info = await db.get_penalty_game(game, _since(cfg))
        if not info:
            await bot.send_message(chat_id, t("bet_no_games"))
            return
    if info is None:
        odds = t("card_odds", suit=f"{cfg.payout_suit:g}", p=f"{cfg.payout_player:g}", t=f"{cfg.payout_tie:g}")
    else:
        odds = t("pen_card_hint")
    user = await db.get_user(chat_id)  # в личке chat_id совпадает с id игрока
    lines = [t("picker_title", game=game), odds]
    mine = [b for b in await db.user_open_bets(chat_id) if b["game"] == game]
    if mine:
        lines.append(t("picker_mine", items=", ".join(
            f"{describe_pick_text(b)} · {b['amount']}" for b in mine)))
    await bot.send_message(chat_id, "\n".join(lines),
                           reply_markup=picker_keyboard(game, info, on, user["pref_stake"], user["pref_wallet"]))


def describe_pick_text(bet) -> str:
    return betting.describe_pick(bet["kind"], bet["pick"])


def _since(cfg: Config) -> int:
    return int(time.time()) - cfg.bet_ttl_hours * 3600


async def _tournament_on(cfg: Config, db: DB) -> bool:
    return cfg.tournament_enabled and await db.active_tournament() is not None


async def maybe_post(cfg: Config, db: DB, bot: Bot, seen_game: int, chat_id: int) -> None:
    """Вызывается при первом посте игры seen_game. В баккаре — карточка на следующую
    игру, в пенальти — на эту же: канал публикует серии заранее."""
    every = await card_every(cfg, db)
    game = seen_game if cfg.game == "penalty" else seen_game + 1
    if not every or game % every or await db.get_card(game, chat_id, _since(cfg)):
        return
    me = await bot.me()
    rendered = await _render(cfg, db, game, {}, False, me.username)
    if not rendered:
        return
    msg = await bot.send_message(chat_id, rendered[0], reply_markup=rendered[1])
    await db.save_card(game, chat_id, msg.message_id)


async def refresh(cfg: Config, db: DB, bot: Bot, game: int, chat_id: int, closed: bool = False) -> None:
    card = await db.get_card(game, chat_id, _since(cfg))
    if not card or card["closed"]:
        return
    counts = await db.bet_counts(game, chat_id, _since(cfg))
    me = await bot.me()
    rendered = await _render(cfg, db, game, counts, closed, me.username)
    try:
        if rendered:
            await bot.edit_message_text(
                text=rendered[0], chat_id=chat_id, message_id=card["message_id"], reply_markup=rendered[1],
            )
    except Exception as e:  # "message is not modified" и т.п. — не страшно
        log.debug("card edit skipped: %s", e)
    if closed:
        await db.close_card(game, chat_id)


async def close_for_game(cfg: Config, db: DB, bot: Bot, game: int) -> None:
    for card in await db.open_cards_for_game(game, _since(cfg)):
        await refresh(cfg, db, bot, game, card["chat_id"], closed=True)


async def window_loop(cfg: Config, db: DB, bot: Bot) -> None:
    """Закрывает карточку по таймеру после поста предыдущей игры, не дожидаясь поста самой игры:
    канал публикует их с задержкой, а игра на сайте уже идёт. Значение — из /admin."""
    while True:
        try:
            window = await betting.bet_window(cfg, db)
            last = await db.last_game()
            seen = await db.game_seen_at(last) if last is not None else None
            if window and seen and time.time() > seen + window:
                await close_for_game(cfg, db, bot, last % cfg.game_number_wrap + 1)
        except Exception:
            log.exception("card window loop failed")
        await asyncio.sleep(2)


def build_router(cfg: Config, db: DB, ensure_user, subs: SubscriptionChecker) -> Router:
    router = Router()
    rating_pressed: dict[int, float] = {}

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
        # Ставку из личного выбора записываем на карточку в основном чате, а не в личку.
        chat_id = query.message.chat.id if query.message else query.from_user.id
        if query.message and query.message.chat.type == ChatType.PRIVATE:
            main_chat = await db.get_state("main_chat")
            if not main_chat:
                await query.answer(t("bet_no_games"), show_alert=True)
                return
            chat_id = int(main_chat)
        if await db.game_seen_since(int(game), _since(cfg)):
            await query.answer(t("bet_started", game=game), show_alert=True)
            return

        try:
            text = await betting.place(
                cfg, db, user["id"], chat_id, int(game), kind, pick, user["pref_stake"], tournament_bet
            )
        except betting.BetError as e:
            await query.answer(str(e), show_alert=True)
            return
        await activity.add(cfg, db, user["id"], activity.POINTS_BET)
        # Короткая плашка сверху на пару секунд — видит только нажавший, в чат ничего не пишется.
        await query.answer(text, show_alert=False)
        await refresh(cfg, db, bot, int(game), chat_id)

    return router
