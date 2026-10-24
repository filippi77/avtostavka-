"""Стратегия value-беттинга.

«Честная» вероятность исхода считается по котировкам букмекеров-ориентиров
с удалением маржи (нормализацией). Если у целевого букмекера коэффициент
выше справедливого настолько, что ожидаемая доходность p * k - 1 превышает
порог min_edge, генерируется сигнал.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from .config import StrategyConfig
from .models import BetSignal, OddsQuote, utcnow


def remove_margin(odds: dict[str, float]) -> dict[str, float]:
    """Переводит коэффициенты всех исходов рынка в вероятности без маржи."""
    implied = {sel: 1.0 / k for sel, k in odds.items() if k > 1.0}
    total = sum(implied.values())
    if total <= 0:
        return {}
    return {sel: p / total for sel, p in implied.items()}


class ValueStrategy:
    def __init__(self, cfg: StrategyConfig):
        self.cfg = cfg
        self._refs = {b.lower() for b in cfg.reference_bookmakers}
        self._targets = {b.lower() for b in cfg.target_bookmakers}

    def _is_target(self, bookmaker: str) -> bool:
        b = bookmaker.lower()
        if self._targets:
            return b in self._targets
        return b not in self._refs

    def _in_time_window(self, start: datetime, now: datetime) -> bool:
        delta = start - now
        return timedelta(minutes=self.cfg.min_minutes_to_start) <= delta <= timedelta(
            hours=self.cfg.max_hours_to_start
        )

    def fair_probabilities(self, quotes: list[OddsQuote]) -> dict[str, float]:
        """Средняя по ориентирам вероятность для каждого исхода одного рынка."""
        by_ref: dict[str, dict[str, float]] = defaultdict(dict)
        for q in quotes:
            if q.bookmaker.lower() in self._refs:
                by_ref[q.bookmaker.lower()][q.selection] = q.odds

        selections = {q.selection for q in quotes}
        sums: dict[str, float] = defaultdict(float)
        counts: dict[str, int] = defaultdict(int)
        for book_odds in by_ref.values():
            # Без полного набора исходов маржу корректно не снять.
            if set(book_odds) != selections or len(book_odds) < 2:
                continue
            for sel, p in remove_margin(book_odds).items():
                sums[sel] += p
                counts[sel] += 1
        return {sel: sums[sel] / counts[sel] for sel in sums}

    def generate(self, quotes: list[OddsQuote], now: datetime | None = None) -> list[BetSignal]:
        now = now or utcnow()
        sports = {s.lower() for s in self.cfg.sports}
        markets = {m.lower() for m in self.cfg.markets}

        grouped: dict[tuple[str, str], list[OddsQuote]] = defaultdict(list)
        for q in quotes:
            if sports and q.sport.lower() not in sports:
                continue
            if markets and q.market.lower() not in markets:
                continue
            grouped[q.market_key].append(q)

        signals: list[BetSignal] = []
        for market_quotes in grouped.values():
            if not self._in_time_window(market_quotes[0].start_time, now):
                continue
            fair = self.fair_probabilities(market_quotes)
            if not fair:
                continue

            # Для каждого исхода берём лучший коэффициент среди целевых букмекеров.
            best: dict[str, OddsQuote] = {}
            for q in market_quotes:
                if not self._is_target(q.bookmaker):
                    continue
                if q.selection not in best or q.odds > best[q.selection].odds:
                    best[q.selection] = q

            market_signals: list[BetSignal] = []
            for sel, q in best.items():
                if not self.cfg.min_odds <= q.odds <= self.cfg.max_odds:
                    continue
                p = fair.get(sel)
                if p is None:
                    continue
                edge = p * q.odds - 1.0
                if self.cfg.min_edge <= edge <= self.cfg.max_edge:
                    market_signals.append(
                        BetSignal(
                            quote=q,
                            fair_probability=p,
                            edge=edge,
                            reason=f"fair={1 / p:.2f} vs {q.bookmaker}={q.odds:.2f}",
                        )
                    )
            market_signals.sort(key=lambda s: s.edge, reverse=True)
            signals.extend(market_signals[:1] if self.cfg.one_bet_per_market else market_signals)

        signals.sort(key=lambda s: s.edge, reverse=True)
        return signals
