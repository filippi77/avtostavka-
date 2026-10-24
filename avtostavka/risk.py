"""Риск-менеджмент: лимиты, которые проверяются перед каждой ставкой."""

from __future__ import annotations

from dataclasses import dataclass

from .config import RiskConfig
from .models import BetSignal


@dataclass
class PortfolioState:
    bankroll: float  # текущий банк (стартовый + реализованная прибыль)
    peak_bankroll: float
    open_bets: int
    open_stake: float  # сумма нерассчитанных ставок
    today_profit: float
    today_bets: int
    event_exposure: dict[str, float]
    placed_keys: set[str]

    @property
    def available(self) -> float:
        return self.bankroll - self.open_stake


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    stake: float
    reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg

    def halt_reason(self, state: PortfolioState) -> str | None:
        """Причина полной остановки торговли (или None)."""
        c = self.cfg
        if state.today_profit <= -c.daily_loss_limit_pct * c.starting_bankroll:
            return f"достигнут дневной лимит убытка ({state.today_profit:.2f})"
        if state.peak_bankroll > 0:
            dd = 1 - state.bankroll / state.peak_bankroll
            if dd >= c.max_drawdown_pct:
                return f"достигнута максимальная просадка ({dd:.1%})"
        if state.today_bets >= c.max_bets_per_day:
            return "достигнут лимит ставок за день"
        return None

    def check(self, signal: BetSignal, stake: float, state: PortfolioState) -> RiskDecision:
        c = self.cfg
        if stake <= 0:
            return RiskDecision(False, 0.0, "нулевая ставка")
        halt = self.halt_reason(state)
        if halt:
            return RiskDecision(False, 0.0, halt)
        if signal.key in state.placed_keys:
            return RiskDecision(False, 0.0, "ставка на этот исход уже сделана")
        if state.open_bets >= c.max_open_bets:
            return RiskDecision(False, 0.0, "слишком много открытых ставок")

        # Ставку можно урезать до лимитов, а не отклонять целиком.
        stake = min(stake, c.max_stake_pct * state.bankroll, state.available)
        event_left = c.max_event_exposure_pct * state.bankroll - state.event_exposure.get(
            signal.quote.event_id, 0.0
        )
        stake = round(min(stake, event_left), 2)
        if stake <= 0:
            return RiskDecision(False, 0.0, "исчерпан лимит на событие или свободный банк")
        return RiskDecision(True, stake)
