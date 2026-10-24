"""Котировки и результаты через The Odds API (https://the-odds-api.com)."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime

from ..models import Bet, BetStatus, OddsQuote
from .base import OddsProvider, ResultsProvider

log = logging.getLogger(__name__)

BASE_URL = "https://api.the-odds-api.com/v4"


class TheOddsApiProvider(OddsProvider, ResultsProvider):
    def __init__(self, api_key: str, sports: list[str], regions: str = "eu",
                 markets: str = "h2h", timeout: float = 15.0):
        if not api_key:
            raise ValueError("Не задан API-ключ The Odds API")
        self.api_key = api_key
        self.sports = sports
        self.regions = regions
        self.markets = markets
        self.timeout = timeout
        self._scores: dict[str, dict] = {}

    def _get(self, path: str, **params) -> list[dict]:
        params["apiKey"] = self.api_key
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=self.timeout) as resp:
            remaining = resp.headers.get("x-requests-remaining")
            if remaining is not None:
                log.debug("The Odds API: осталось запросов %s", remaining)
            return json.loads(resp.read().decode("utf-8"))

    @staticmethod
    def parse(sport: str, events: list[dict]) -> list[OddsQuote]:
        quotes = []
        for ev in events:
            start = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            name = f'{ev.get("home_team", "")} — {ev.get("away_team", "")}'
            for book in ev.get("bookmakers", []):
                for market in book.get("markets", []):
                    for outcome in market.get("outcomes", []):
                        quotes.append(
                            OddsQuote(
                                event_id=ev["id"], event_name=name, sport=sport,
                                start_time=start, market=market["key"],
                                selection=outcome["name"], bookmaker=book["key"],
                                odds=float(outcome["price"]),
                            )
                        )
        return quotes

    def fetch(self) -> list[OddsQuote]:
        quotes: list[OddsQuote] = []
        for sport in self.sports:
            try:
                events = self._get(f"/sports/{sport}/odds", regions=self.regions,
                                   markets=self.markets, oddsFormat="decimal")
            except Exception as exc:  # одна лига не должна ронять весь цикл
                log.warning("Не удалось получить котировки %s: %s", sport, exc)
                continue
            quotes.extend(self.parse(sport, events))
        return quotes

    def refresh_scores(self) -> None:
        for sport in self.sports:
            try:
                for ev in self._get(f"/sports/{sport}/scores", daysFrom=3):
                    self._scores[ev["id"]] = ev
            except Exception as exc:
                log.warning("Не удалось получить результаты %s: %s", sport, exc)

    def result(self, bet: Bet) -> BetStatus | None:
        q = bet.signal.quote
        ev = self._scores.get(q.event_id)
        if not ev or not ev.get("completed") or q.market != "h2h" or not ev.get("scores"):
            return None
        scores = {s["name"]: float(s["score"]) for s in ev["scores"]}
        top = max(scores.values())
        leaders = [n for n, v in scores.items() if v == top]
        winner = leaders[0] if len(leaders) == 1 else "Draw"
        return BetStatus.WON if q.selection == winner else BetStatus.LOST
