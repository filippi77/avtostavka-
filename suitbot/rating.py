"""Рейтинг: во время турнира — по турнирным фишкам, иначе — по обычным."""

from html import escape

from .config import Config
from .db import DB
from .tournament import place_mark

POPUP_LIMIT = 200  # Telegram обрезает всплывающее окно после 200 символов


def _short(name: str, n: int = 12) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


async def _rows(cfg: Config, db: DB, user_id: int, limit: int = 10):
    """(заголовок, [(имя, фишки)], моё место или None, мои фишки или None)."""
    current = await db.active_tournament() if cfg.tournament_enabled else None
    if current:
        standings = await db.standings(current["id"])
        rows = [(e["name"], e["balance"]) for e in standings[:limit]]
        mine = next(((i + 1, e["balance"]) for i, e in enumerate(standings) if e["user_id"] == user_id), (None, None))
        return "🏆 Турнир", rows, *mine
    top = await db.top(limit)
    user = await db.get_user(user_id)
    rank = await db.user_rank(user_id) if user else None
    return "📊 Рейтинг", [(r["name"], r["balance"]) for r in top], rank, user["balance"] if user else None


async def popup_text(cfg: Config, db: DB, user_id: int) -> str:
    title, rows, place, balance = await _rows(cfg, db, user_id)
    if not rows:
        return f"{title}: пока никого нет."
    if place:
        footer = f"Вы: {place} место · {balance}"
    elif title.startswith("🏆"):
        footer = "Вы не в турнире: /tournament"
    else:
        footer = "Сделайте первую ставку, чтобы попасть в рейтинг"
    lines = [f"{i + 1}. {_short(name)} {bal}" for i, (name, bal) in enumerate(rows)]
    while lines:
        text = "\n".join([f"{title} · топ {len(lines)}", *lines, footer])
        if len(text) <= POPUP_LIMIT:
            return text
        lines.pop()
    return footer


async def full_text(cfg: Config, db: DB, user_id: int) -> str:
    title, rows, place, balance = await _rows(cfg, db, user_id)
    if not rows:
        return f"{title}: пока никого нет."
    lines = [f"<b>{title} · топ {len(rows)}</b>"]
    lines += [f"{place_mark(i)} {escape(name)} — {bal}" for i, (name, bal) in enumerate(rows)]
    if place:
        lines.append(f"\nВы: <b>{place} место</b> · {balance} фишек")
    elif title.startswith("🏆"):
        lines.append("\nВы ещё не в турнире — вступайте: /tournament")
    return "\n".join(lines)
