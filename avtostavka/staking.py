"""Расчёт размера ставки."""

from __future__ import annotations

import math

from .config import StakingConfig
from .models import BetSignal


def kelly_fraction(probability: float, odds: float) -> float:
    """Доля банка по критерию Келли: (p*k - 1) / (k - 1). Не меньше нуля."""
    if odds <= 1.0:
        return 0.0
    return max(0.0, (probability * odds - 1.0) / (odds - 1.0))


class StakeCalculator:
    def __init__(self, cfg: StakingConfig):
        self.cfg = cfg

    def _raw(self, signal: BetSignal, bankroll: float) -> float:
        c = self.cfg
        if c.method == "fixed":
            return c.fixed_amount
        if c.method == "percent":
            return bankroll * c.percent
        return bankroll * c.kelly_fraction * kelly_fraction(signal.fair_probability, signal.quote.odds)

    def stake(self, signal: BetSignal, bankroll: float) -> float:
        """Возвращает размер ставки или 0, если ставить не нужно."""
        c = self.cfg
        raw = min(self._raw(signal, bankroll), c.max_stake, bankroll)
        if c.round_to > 0:
            raw = math.floor(raw / c.round_to + 1e-9) * c.round_to
        raw = round(raw, 2)
        return raw if raw >= c.min_stake else 0.0
