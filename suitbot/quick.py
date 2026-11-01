"""Быстрые команды ставок в меню «/» чата.

/hearts, /player, /p1, /over… — ставка на ближайшую открытую игру суммой и
кошельком, которые игрок выбрал на карточке. Чтобы не засорять чат, бот
удаляет сообщение с командой (нужно право удалять сообщения), а ответ шлёт
игроку в личку. Если личка с ботом ещё не открыта — отвечает в чате и через
несколько секунд удаляет ответ.

Здесь же — списки команд для меню: в группах быстрые ставки, в личке — кабинет.
"""

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats, Message

from . import activity, betting, cards
from .access import SubscriptionChecker
from .config import Config
from .db import DB
from .i18n import t

log = logging.getLogger(__name__)

REPLY_TTL = 8  # секунд живёт ответ в чате, если в личку написать нельзя

# команда → (тип ставки, выбор)
BACCARAT = {
    "spades": ("suit", "♠"), "clubs": ("suit", "♣"), "hearts": ("suit", "♥"), "diamonds": ("suit", "♦"),
    "player": ("side", "P"), "banker": ("side", "B"), "tie": ("side", "T"),
}
PENALTY = {"p1": ("win", "1"), "p2": ("win", "2"), "over": ("total", "O"), "under": ("total", "U")}


def quick_bets(cfg: Config) -> dict[str, tuple[str, str]]:
    return PENALTY if cfg.game == "penalty" else BACCARAT


async def set_commands(cfg: Config, bot: Bot) -> None:
    """Меню «/»: в группах — быстрые ставки, в личке — кабинет. Вызывается при запуске и смене языка."""
    group = [BotCommand(command=name, description=t(f"cmd_{name}")) for name in quick_bets(cfg)]
    group += [BotCommand(command="duel", description=t("cmd_duel")), BotCommand(command="top", description=t("cmd_top"))]
    private = [BotCommand(command=name, description=t(f"cmd_{name}"))
               for name in ("start", "balance", "shop", "bonus", "spin", "tournament", "active", "help")]
    try:
        await bot.set_my_commands(group, scope=BotCommandScopeAllGroupChats())
        await bot.set_my_commands(private, scope=BotCommandScopeAllPrivateChats())
    except Exception:
        log.exception("set_my_commands failed")


async def next_game(cfg: Config, db: DB) -> int | None:
    """Ближайшая игра, на которую ещё принимаются ставки."""
    last = await db.last_game()
    return None if last is None else last % cfg.game_number_wrap + 1


async def _delete_later(message: Message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass


def build_router(cfg: Config, db: DB, ensure_user, subs: SubscriptionChecker) -> Router:
    router = Router()

    @router.message(Command(*quick_bets(cfg)), F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}), F.from_user,
                    ~F.sender_chat)
    async def on_quick_bet(message: Message, bot: Bot) -> None:
        name = message.text.split()[0].lstrip("/").split("@")[0].lower()
        kind, pick = quick_bets(cfg)[name]
        user = await ensure_user(message.from_user)

        game = await next_game(cfg, db)
        if not await subs.is_subscribed(bot, user["id"]):
            text = subs.alert()
        elif game is None:
            text = t("bet_no_games")
        else:
            tournament_bet = user["pref_wallet"] == "tour" and cfg.tournament_enabled \
                and await db.active_tournament() is not None
            try:
                text = await betting.place(cfg, db, user["id"], message.chat.id, game, kind, pick,
                                           user["pref_stake"], tournament_bet)
                await activity.add(cfg, db, user["id"], activity.POINTS_BET)
                await cards.refresh(cfg, db, bot, game, message.chat.id)
            except betting.BetError as e:
                text = str(e)

        try:
            await message.delete()  # команду из чата убираем, чтобы не мешала
        except Exception:
            pass
        try:
            await bot.send_message(user["id"], text)
        except Exception:
            # Личку с ботом игрок ещё не открывал — коротко отвечаем в чате и убираем ответ.
            reply = await bot.send_message(message.chat.id, f"{escape(message.from_user.first_name)}: {text}")
            asyncio.create_task(_delete_later(reply, REPLY_TTL))

    return router
