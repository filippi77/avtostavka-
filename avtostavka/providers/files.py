"""Котировки и результаты из JSON-файлов (для тестов, демо и бэктеста)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from ..models import Bet, BetStatus, OddsQuote, utcnow
from .base import OddsProvider, ResultsProvider


def parse_time(value: str) -> datetime:
    """ISO-время или смещение от текущего момента в часах, например «+2.5h»."""
    if value.startswith("+") and value.endswith("h"):
        return utcnow() + timedelta(hours=float(value[1:-1]))
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_quotes(data: list[dict]) -> list[OddsQuote]:
    """Формат: список событий, у каждого markets -> bookmakers -> {исход: коэф}."""
    quotes = []
    for ev in data:
        start = parse_time(ev["start_time"])
        for market, books in ev["markets"].items():
            for bookmaker, outcomes in books.items():
                for selection, odds in outcomes.items():
                    quotes.append(
                        OddsQuote(
                            event_id=str(ev["id"]),
                            event_name=ev["name"],
                            sport=ev.get("sport", ""),
                            start_time=start,
                            market=market,
                            selection=selection,
                            bookmaker=bookmaker,
                            odds=float(odds),
                        )
                    )
    return quotes


class FileOddsProvider(OddsProvider):
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self) -> list[OddsQuote]:
        return parse_quotes(json.loads(self.path.read_text(encoding="utf-8")))


class FileResultsProvider(ResultsProvider):
    """Формат: {"event_id": {"market": "выигравший исход" | "void"}}."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def result(self, bet: Bet) -> BetStatus | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        q = bet.signal.quote
        winner = data.get(q.event_id, {}).get(q.market)
        if winner is None:
            return None
        if winner == "void":
            return BetStatus.VOID
        return BetStatus.WON if winner == q.selection else BetStatus.LOST
