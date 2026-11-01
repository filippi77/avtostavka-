"""Рейтинг: во время турнира — по турнирным фишкам, иначе — по обычным."""

from html import escape

from .config import Config
from .db import DB
from .i18n import t
from .tournament import place_mark

POPUP_LIMIT = 200  # Telegram обрезает всплывающее окно после 200 символов


def _bar(bal: int, top: int, cells: int = 6) -> str:
    """Полоска относительно лидера: видно, насколько игроки отстают."""
    filled = max(0, min(cells, round(cells * bal / top)))
    return "▰" * filled + "▱" * (cells - filled)


def _short(name: str, n: int = 12) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


async def _rows(cfg: Config, db: DB, user_id: int, limit: int = 10):
    """(заголовок, [(имя, фишки)], моё место или None, мои фишки или None)."""
    current = await db.active_tournament() if cfg.tournament_enabled else None
    if current:
        standings = await db.standings(current["id"])
        rows = [(e["name"], e["balance"]) for e in standings[:limit]]
        mine = next(((i + 1, e["balance"]) for i, e in enumerate(standings) if e["user_id"] == user_id), (None, None))
        return t("rating_title_tour"), rows, *mine
    top = await db.top(limit)
    user = await db.get_user(user_id)
    rank = await db.user_rank(user_id) if user else None
    return t("rating_title"), [(r["name"], r["balance"]) for r in top], rank, user["balance"] if user else None


async def popup_text(cfg: Config, db: DB, user_id: int) -> str:
    title, rows, place, balance = await _rows(cfg, db, user_id)
    if not rows:
        return t("rating_empty", title=title)
    if place:
        footer = t("rating_me", place=place, balance=balance)
    elif title.startswith("🏆"):
        footer = t("rating_not_in_tour")
    else:
        footer = t("rating_first_bet")
    lines = [f"{i + 1}. {_short(name)} {bal}" for i, (name, bal) in enumerate(rows)]
    while lines:
        text = "\n".join([t("rating_top", title=title, n=len(lines)), *lines, footer])
        if len(text) <= POPUP_LIMIT:
            return text
        lines.pop()
    return footer


async def full_text(cfg: Config, db: DB, user_id: int) -> str:
    title, rows, place, balance = await _rows(cfg, db, user_id)
    if not rows:
        return t("rating_empty", title=title)
    lines = [f"<b>{t('rating_top', title=title, n=len(rows))}</b>"]
    top = max((bal for _, bal in rows), default=1) or 1
    lines += [f"{place_mark(i)} {escape(name)} {_bar(bal, top)} {bal}" for i, (name, bal) in enumerate(rows)]
    if place:
        lines.append(t("rating_me_full", place=place, balance=balance))
    elif title.startswith("🏆"):
        lines.append(t("rating_not_in_tour_full"))
    return "\n".join(lines)
