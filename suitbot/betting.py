"""Приём ставки — общий для команд /bet, /tbet и кнопок карточки игры."""

import time

from .config import Config
from .db import DB, InsufficientFunds
from .i18n import t
from .parser import suit_emoji

SIDES = ("P", "B", "T")


def side_name(code: str) -> str:
    return t(f"side_{code}")


class BetError(Exception):
    """Ставка не принята; текст исключения можно показать игроку."""


def describe_pick(kind: str, pick: str, info: dict | None = None) -> str:
    if kind == "suit":
        return suit_emoji(pick)
    if kind == "side":
        return side_name(pick)
    if kind == "win":
        team = (info or {}).get("home" if pick == "1" else "away", "")
        return t("pick_win", side=pick, team=team).strip()
    if kind == "total":
        return t("pick_over" if pick[0] == "O" else "pick_under", line=f"{float(pick[1:]):g}")
    return pick


async def penalty_coef(cfg: Config, db: DB, game: int, kind: str, pick: str) -> tuple[str, float, dict]:
    """Коэффициент пенальти-ставки из поста канала. Для тотала к выбору добавляется линия: "O" → "O4.5"."""
    info = await db.get_penalty_game(game, int(time.time()) - cfg.bet_ttl_hours * 3600)
    side = pick[0] if kind == "total" else pick
    if not info or side not in info["odds"] or (kind == "total" and info["line"] is None):
        raise BetError(t("bet_no_odds", game=game))
    if kind == "total":
        pick = f"{side}{info['line']:g}"
    return pick, info["odds"][side], info


async def place(
    cfg: Config, db: DB, user_id: int, chat_id: int,
    game: int, kind: str, pick: str, amount: int, tournament_bet: bool,
) -> str:
    """Проверяет и принимает ставку. Возвращает текст подтверждения или бросает BetError."""
    max_bet = cfg.tournament_max_bet if tournament_bet else cfg.max_bet
    if not cfg.min_bet <= amount <= max_bet:
        raise BetError(t("bet_limits", min=cfg.min_bet, max=max_bet))

    tournament_id = None
    if tournament_bet:
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if not current or current["ends_at"] <= time.time():
            raise BetError(t("bet_no_tour"))
        tournament_id = current["id"]

    last = await db.last_game()
    if last is None:
        raise BetError(t("bet_no_games"))
    ahead = (game - last) % cfg.game_number_wrap
    if not 1 <= ahead <= cfg.max_games_ahead:
        raise BetError(t("bet_range", last=last, first=last + 1, to=last + cfg.max_games_ahead))
    if await db.game_seen_since(game, int(time.time()) - cfg.bet_ttl_hours * 3600):
        raise BetError(t("bet_started", game=game))
    if cfg.bet_window_seconds and ahead == 1:
        seen = await db.game_seen_at(last)
        if seen and time.time() > seen + cfg.bet_window_seconds:
            raise BetError(t("bet_window", game=game))

    if tournament_id is not None:
        await db.join_tournament(tournament_id, user_id, cfg.tournament_start_chips)
    info = None
    if kind in ("win", "total"):
        pick, coef, info = await penalty_coef(cfg, db, game, kind, pick)
    else:
        coef = cfg.payout(kind, pick)
    try:
        await db.place_bet(user_id, chat_id, game, kind, pick, amount, coef, tournament_id)
    except InsufficientFunds:
        if tournament_id is not None:
            entry = await db.get_entry(tournament_id, user_id)
            raise BetError(t("bet_no_tour_chips", balance=entry["balance"])) from None
        user = await db.get_user(user_id)
        raise BetError(t("bet_no_chips", balance=user["balance"])) from None

    if tournament_id is not None:
        left = (await db.get_entry(tournament_id, user_id))["balance"]
    else:
        left = (await db.get_user(user_id))["balance"]
    return t(
        "bet_ok_tour" if tournament_id is not None else "bet_ok",
        game=game, pick=describe_pick(kind, pick, info), amount=amount, coef=f"{coef:g}", win=int(amount * coef), left=left,
    )
