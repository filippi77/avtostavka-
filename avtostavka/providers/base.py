"""Интерфейсы источников данных и исполнителя ставок."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import Bet, BetStatus, OddsQuote, PlacementResult


class OddsProvider(ABC):
    @abstractmethod
    def fetch(self) -> list[OddsQuote]:
        """Текущие котировки по всем отслеживаемым событиям."""


class ResultsProvider(ABC):
    @abstractmethod
    def result(self, bet: Bet) -> BetStatus | None:
        """Итог ставки или None, если событие ещё не рассчитано."""


class Executor(ABC):
    """Размещает ставку у букмекера или на бирже.

    Чтобы подключить реальную площадку, унаследуйтесь от этого класса и
    реализуйте place(): отправьте ставку через официальный API площадки и
    верните PlacementResult. Учтите правила площадки и законы вашей страны.
    """

    @abstractmethod
    def place(self, bet: Bet) -> PlacementResult:
        ...
