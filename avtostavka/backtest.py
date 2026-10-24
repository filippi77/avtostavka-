"""Бэктест стратегии на исторических котировках и результатах."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .config import Config
from .engine import Engine, Stats
from .models import OddsQuote
from .notifier import Notifier
from .providers.base import OddsProvider, ResultsProvider
from .providers.paper import PaperExecutor
from .storage import Storage


class _Silent(Notifier):
    def send(self, text: str) -> None:
        pass


class _NoOdds(OddsProvider):
    def fetch(self) -> list[OddsQuote]:
        return []


def run_backtest(cfg: Config, quotes: list[OddsQuote], results: ResultsProvider) -> Stats:
    """События проигрываются в хронологическом порядке.

    Ставка «делается» за min_minutes_to_start + 1 минуту до начала события,
    расчёт — сразу после. Банкролл и лимиты учитываются так же, как в боевом режиме.
    """
    engine = Engine(cfg, _NoOdds(), PaperExecutor(), results, Storage(":memory:"), _Silent())
    by_event: dict[str, list[OddsQuote]] = defaultdict(list)
    for q in quotes:
        by_event[q.event_id].append(q)

    lead = timedelta(minutes=cfg.strategy.min_minutes_to_start + 1)
    for event_quotes in sorted(by_event.values(), key=lambda qs: qs[0].start_time):
        start = event_quotes[0].start_time
        engine.process(event_quotes, now=start - lead)
        engine.settle(now=start + timedelta(hours=3))
    return engine.stats()
