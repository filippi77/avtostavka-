"""Приём ставки — общий для команд /bet, /tbet и кнопок карточки игры."""

import time

from .config import Config
from .db import DB, InsufficientFunds

SIDE_NAMES = {"P": "игрок", "B": "банкир", "T": "ничья"}


class BetError(Exception):
    """Ставка не принята; текст исключения можно показать игроку."""


def describe_pick(kind: str, pick: str) -> str:
    return pick if kind == "suit" else SIDE_NAMES[pick]


async def place(
    cfg: Config, db: DB, user_id: int, chat_id: int,
    game: int, kind: str, pick: str, amount: int, tournament_bet: bool,
) -> str:
    """Проверяет и принимает ставку. Возвращает текст подтверждения или бросает BetError."""
    max_bet = cfg.tournament_max_bet if tournament_bet else cfg.max_bet
    if not cfg.min_bet <= amount <= max_bet:
        raise BetError(f"Ставка от {cfg.min_bet} до {max_bet} фишек.")

    tournament_id = None
    if tournament_bet:
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if not current or current["ends_at"] <= time.time():
            raise BetError("Сейчас турнира нет.")
        tournament_id = current["id"]

    last = await db.last_game()
    if last is None:
        raise BetError("Ещё не видел ни одного поста канала — подождите следующую игру.")
    ahead = (game - last) % cfg.game_number_wrap
    if not 1 <= ahead <= cfg.max_games_ahead:
        raise BetError(f"Последняя игра #N{last}. Ставки принимаются на #N{last + 1}…#N{last + cfg.max_games_ahead}.")
    if await db.game_seen_since(game, int(time.time()) - cfg.bet_ttl_hours * 3600):
        raise BetError(f"Игра #N{game} уже началась, ставки закрыты.")

    if tournament_id is not None:
        await db.join_tournament(tournament_id, user_id, cfg.tournament_start_chips)
    coef = cfg.payout(kind, pick)
    try:
        await db.place_bet(user_id, chat_id, game, kind, pick, amount, coef, tournament_id)
    except InsufficientFunds:
        if tournament_id is not None:
            entry = await db.get_entry(tournament_id, user_id)
            raise BetError(
                f"Недостаточно турнирных фишек: осталось {entry['balance']}. Турнирные фишки не докупаются."
            ) from None
        user = await db.get_user(user_id)
        raise BetError(f"Недостаточно фишек: на балансе {user['balance']}. /bonus или /buy") from None

    if tournament_id is not None:
        left = (await db.get_entry(tournament_id, user_id))["balance"]
        prefix, wallet = "🏆 Турнирная ставка", "турнирных"
    else:
        left = (await db.get_user(user_id))["balance"]
        prefix, wallet = "✅ Ставка", ""
    return (
        f"{prefix} принята: #N{game} · {describe_pick(kind, pick)} · {amount} ×{coef:g} "
        f"(выигрыш {int(amount * coef)}). Осталось {left} {wallet} фишек".replace("  ", " ")
    )
