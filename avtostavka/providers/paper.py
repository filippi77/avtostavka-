"""Бумажная торговля: ставки только записываются, деньги не тратятся."""

from __future__ import annotations

import itertools

from ..models import Bet, PlacementResult
from .base import Executor


class PaperExecutor(Executor):
    def __init__(self):
        self._ids = itertools.count(1)

    def place(self, bet: Bet) -> PlacementResult:
        return PlacementResult(accepted=True, external_id=f"paper-{next(self._ids)}")
