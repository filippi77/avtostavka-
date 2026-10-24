"""Базовые модели данных."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OddsQuote:
    """Одна котировка: коэффициент букмекера на исход рынка события."""

    event_id: str
    event_name: str
    sport: str
    start_time: datetime
    market: str
    selection: str
    bookmaker: str
    odds: float

    @property
    def market_key(self) -> tuple[str, str]:
        return (self.event_id, self.market)


@dataclass(frozen=True)
class BetSignal:
    """Сигнал стратегии: на что и почему стоит поставить."""

    quote: OddsQuote
    fair_probability: float
    edge: float  # ожидаемая доходность на единицу ставки: p * k - 1
    reason: str = ""

    @property
    def key(self) -> str:
        q = self.quote
        return f"{q.event_id}|{q.market}|{q.selection}"


class BetStatus(str, enum.Enum):
    PENDING = "pending"
    WON = "won"
    LOST = "lost"
    VOID = "void"
    REJECTED = "rejected"


@dataclass
class Bet:
    signal: BetSignal
    stake: float
    status: BetStatus = BetStatus.PENDING
    placed_at: datetime = field(default_factory=utcnow)
    external_id: str | None = None
    id: int | None = None
    settled_at: datetime | None = None

    @property
    def odds(self) -> float:
        return self.signal.quote.odds

    @property
    def profit(self) -> float:
        """Реализованная прибыль (0 для неподсчитанных ставок)."""
        if self.status is BetStatus.WON:
            return self.stake * (self.odds - 1)
        if self.status is BetStatus.LOST:
            return -self.stake
        return 0.0


@dataclass(frozen=True)
class PlacementResult:
    accepted: bool
    external_id: str | None = None
    odds: float | None = None  # фактический коэффициент, если отличается
    message: str = ""
