"""Основной цикл: котировки → сигналы → размер ставки → риск → размещение → расчёт."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from .config import Config
from .models import Bet, BetStatus, OddsQuote, utcnow
from .notifier import Notifier
from .providers.base import Executor, OddsProvider, ResultsProvider
from .risk import PortfolioState, RiskManager
from .staking import StakeCalculator
from .storage import Storage
from .strategy import ValueStrategy

log = logging.getLogger(__name__)


@dataclass
class Stats:
    total: int
    pending: int
    won: int
    lost: int
    void: int
    turnover: float
    profit: float
    bankroll: float
    max_drawdown: float

    @property
    def roi(self) -> float:
        return self.profit / self.turnover if self.turnover else 0.0

    @property
    def hit_rate(self) -> float:
        decided = self.won + self.lost
        return self.won / decided if decided else 0.0

    def format(self) -> str:
        return (
            f"Ставок: {self.total} (в игре {self.pending}, выигрыш {self.won}, "
            f"проигрыш {self.lost}, возврат {self.void})\n"
            f"Оборот: {self.turnover:.2f}  Прибыль: {self.profit:+.2f}  ROI: {self.roi:+.2%}\n"
            f"Проходимость: {self.hit_rate:.1%}  Банк: {self.bankroll:.2f}  "
            f"Макс. просадка: {self.max_drawdown:.1%}"
        )


class Engine:
    def __init__(self, cfg: Config, odds: OddsProvider, executor: Executor,
                 results: ResultsProvider | None, storage: Storage,
                 notifier: Notifier | None = None):
        self.cfg = cfg
        self.odds = odds
        self.executor = executor
        self.results = results
        self.storage = storage
        self.notifier = notifier or Notifier()
        self.strategy = ValueStrategy(cfg.strategy)
        self.staking = StakeCalculator(cfg.staking)
        self.risk = RiskManager(cfg.risk)
        self._halted_reason: str | None = None

    # --- состояние портфеля -------------------------------------------------

    def _equity_curve(self, bets: list[Bet]) -> tuple[float, float, float]:
        """Текущий банк, его пик и максимальная просадка по рассчитанным ставкам."""
        bank = peak = self.cfg.risk.starting_bankroll
        max_dd = 0.0
        settled = [b for b in bets if b.settled_at is not None]
        settled.sort(key=lambda b: b.settled_at)
        for b in settled:
            bank += b.profit
            peak = max(peak, bank)
            max_dd = max(max_dd, 1 - bank / peak if peak > 0 else 0.0)
        return bank, peak, max_dd

    def state(self, now: datetime | None = None) -> PortfolioState:
        now = now or utcnow()
        bets = self.storage.bets()
        bank, peak, _ = self._equity_curve(bets)
        today = now.date()
        pending = [b for b in bets if b.status is BetStatus.PENDING]
        exposure: dict[str, float] = {}
        for b in pending:
            eid = b.signal.quote.event_id
            exposure[eid] = exposure.get(eid, 0.0) + b.stake
        return PortfolioState(
            bankroll=bank,
            peak_bankroll=peak,
            open_bets=len(pending),
            open_stake=sum(b.stake for b in pending),
            today_profit=sum(b.profit for b in bets if b.settled_at and b.settled_at.date() == today),
            today_bets=sum(1 for b in bets
                           if b.placed_at.date() == today and b.status is not BetStatus.REJECTED),
            event_exposure=exposure,
            placed_keys=self.storage.placed_keys(),
        )

    def stats(self) -> Stats:
        bets = self.storage.bets()
        bank, _, max_dd = self._equity_curve(bets)
        counted = [b for b in bets if b.status is not BetStatus.REJECTED]
        by = lambda s: sum(1 for b in counted if b.status is s)  # noqa: E731
        return Stats(
            total=len(counted), pending=by(BetStatus.PENDING), won=by(BetStatus.WON),
            lost=by(BetStatus.LOST), void=by(BetStatus.VOID),
            turnover=sum(b.stake for b in counted if b.status in (BetStatus.WON, BetStatus.LOST)),
            profit=sum(b.profit for b in counted), bankroll=bank, max_drawdown=max_dd,
        )

    # --- шаги цикла ---------------------------------------------------------

    def process(self, quotes: list[OddsQuote], now: datetime | None = None) -> list[Bet]:
        now = now or utcnow()
        placed: list[Bet] = []
        for signal in self.strategy.generate(quotes, now=now):
            state = self.state(now)
            halt = self.risk.halt_reason(state)
            if halt:
                if halt != self._halted_reason:
                    self.notifier.send(f"⛔ Торговля приостановлена: {halt}")
                    self._halted_reason = halt
                break
            self._halted_reason = None

            stake = self.staking.stake(signal, state.available)
            decision = self.risk.check(signal, stake, state)
            if not decision.allowed:
                log.debug("Пропуск %s: %s", signal.key, decision.reason)
                continue

            bet = Bet(signal=signal, stake=decision.stake, placed_at=now)
            result = self.executor.place(bet)
            if not result.accepted:
                bet.status = BetStatus.REJECTED
                self.storage.save(bet)
                log.warning("Ставка отклонена %s: %s", signal.key, result.message)
                continue
            bet.external_id = result.external_id
            if result.odds and result.odds != signal.quote.odds:
                log.info("Коэффициент изменился %.2f → %.2f", signal.quote.odds, result.odds)
            self.storage.save(bet)
            placed.append(bet)
            q = signal.quote
            self.notifier.send(
                f"✅ {q.event_name} | {q.market}: {q.selection} @ {q.odds:.2f} ({q.bookmaker})\n"
                f"Ставка {bet.stake:.2f}, перевес {signal.edge:+.1%}"
                + (" [paper]" if self.cfg.dry_run else "")
            )
        return placed

    def settle(self, now: datetime | None = None) -> int:
        if self.results is None:
            return 0
        refresh = getattr(self.results, "refresh_scores", None)
        if callable(refresh):
            refresh()
        settled = 0
        for bet in self.storage.bets(BetStatus.PENDING):
            status = self.results.result(bet)
            if status is None:
                continue
            self.storage.settle(bet.id, status, at=now)
            bet.status = status
            settled += 1
            q = bet.signal.quote
            self.notifier.send(f"🏁 {q.event_name}: {q.selection} — {status.value}, {bet.profit:+.2f}")
        return settled

    def run_once(self) -> list[Bet]:
        self.settle()
        try:
            quotes = self.odds.fetch()
        except Exception as exc:
            log.error("Ошибка получения котировок: %s", exc)
            return []
        log.info("Получено котировок: %d", len(quotes))
        return self.process(quotes)

    def run_forever(self) -> None:
        mode = "PAPER" if self.cfg.dry_run else "LIVE"
        self.notifier.send(f"🤖 Автоставка запущена ({mode})")
        try:
            while True:
                started = time.monotonic()
                self.run_once()
                elapsed = time.monotonic() - started
                time.sleep(max(0.0, self.cfg.poll_interval_sec - elapsed))
        except KeyboardInterrupt:
            log.info("Остановлено пользователем")
