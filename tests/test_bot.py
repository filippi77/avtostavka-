import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from avtostavka.backtest import run_backtest
from avtostavka.config import Config, RiskConfig, StakingConfig, StrategyConfig, load_config, validate
from avtostavka.engine import Engine
from avtostavka.models import Bet, BetSignal, BetStatus, OddsQuote, PlacementResult
from avtostavka.notifier import Notifier
from avtostavka.providers import FileOddsProvider, FileResultsProvider, PaperExecutor
from avtostavka.providers.base import Executor, OddsProvider, ResultsProvider
from avtostavka.risk import PortfolioState, RiskManager
from avtostavka.staking import StakeCalculator, kelly_fraction
from avtostavka.storage import Storage
from avtostavka.strategy import ValueStrategy, remove_margin

NOW = datetime(2026, 5, 1, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parent.parent


def quote(sel, book, odds, event="e1", market="h2h", start=NOW + timedelta(hours=2)):
    return OddsQuote(event, f"Event {event}", "soccer", start, market, sel, book, odds)


def market(event="e1", soft_home=2.3, start=NOW + timedelta(hours=2)):
    return [
        quote("home", "pinnacle", 2.0, event, start=start),
        quote("away", "pinnacle", 2.0, event, start=start),
        quote("home", "soft", soft_home, event, start=start),
        quote("away", "soft", 1.8, event, start=start),
    ]


class Silent(Notifier):
    def send(self, text):
        pass


class StaticOdds(OddsProvider):
    def __init__(self, quotes):
        self.quotes = quotes

    def fetch(self):
        return self.quotes


class FixedResults(ResultsProvider):
    def __init__(self, status):
        self.status = status

    def result(self, bet):
        return self.status


class StrategyTests(unittest.TestCase):
    def test_remove_margin_normalizes(self):
        probs = remove_margin({"a": 1.9, "b": 1.9})
        self.assertAlmostEqual(probs["a"], 0.5)
        self.assertAlmostEqual(sum(probs.values()), 1.0)

    def test_finds_value_on_soft_book(self):
        signals = ValueStrategy(StrategyConfig()).generate(market(), now=NOW)
        self.assertEqual(len(signals), 1)
        s = signals[0]
        self.assertEqual((s.quote.selection, s.quote.bookmaker), ("home", "soft"))
        self.assertAlmostEqual(s.edge, 0.15)

    def test_no_signal_below_min_edge(self):
        self.assertEqual(ValueStrategy(StrategyConfig()).generate(market(soft_home=2.04), now=NOW), [])

    def test_suspicious_edge_ignored(self):
        self.assertEqual(ValueStrategy(StrategyConfig()).generate(market(soft_home=3.0), now=NOW), [])

    def test_time_window(self):
        late = market(start=NOW + timedelta(minutes=2))
        far = market(start=NOW + timedelta(days=5))
        strat = ValueStrategy(StrategyConfig())
        self.assertEqual(strat.generate(late, now=NOW), [])
        self.assertEqual(strat.generate(far, now=NOW), [])

    def test_incomplete_reference_market_skipped(self):
        quotes = [q for q in market() if not (q.bookmaker == "pinnacle" and q.selection == "away")]
        self.assertEqual(ValueStrategy(StrategyConfig()).generate(quotes, now=NOW), [])

    def test_one_bet_per_market(self):
        quotes = [
            quote("a", "pinnacle", 3.0), quote("b", "pinnacle", 3.0), quote("c", "pinnacle", 3.0),
            quote("a", "soft", 3.3), quote("b", "soft", 3.2), quote("c", "soft", 2.5),
        ]
        one = ValueStrategy(StrategyConfig()).generate(quotes, now=NOW)
        many = ValueStrategy(StrategyConfig(one_bet_per_market=False)).generate(quotes, now=NOW)
        self.assertEqual([s.quote.selection for s in one], ["a"])
        self.assertEqual([s.quote.selection for s in many], ["a", "b"])


class StakingTests(unittest.TestCase):
    def signal(self, p=0.5, odds=2.3):
        return BetSignal(quote("home", "soft", odds), p, p * odds - 1)

    def test_kelly_formula(self):
        self.assertAlmostEqual(kelly_fraction(0.5, 2.3), 0.15 / 1.3)
        self.assertEqual(kelly_fraction(0.3, 2.0), 0.0)

    def test_fractional_kelly_and_caps(self):
        calc = StakeCalculator(StakingConfig(kelly_fraction=0.25, max_stake=100))
        self.assertAlmostEqual(calc.stake(self.signal(), 1000), 28.84)
        self.assertEqual(calc.stake(self.signal(), 100000), 100)

    def test_below_min_stake_is_zero(self):
        calc = StakeCalculator(StakingConfig(method="fixed", fixed_amount=0.5, min_stake=1))
        self.assertEqual(calc.stake(self.signal(), 1000), 0.0)


class RiskTests(unittest.TestCase):
    def state(self, **kw):
        base = dict(bankroll=1000, peak_bankroll=1000, open_bets=0, open_stake=0, today_profit=0,
                    today_bets=0, event_exposure={}, placed_keys=set())
        base.update(kw)
        return PortfolioState(**base)

    def signal(self):
        return BetSignal(quote("home", "soft", 2.3), 0.5, 0.15)

    def test_stake_capped(self):
        d = RiskManager(RiskConfig(max_stake_pct=0.05)).check(self.signal(), 500, self.state())
        self.assertTrue(d.allowed)
        self.assertEqual(d.stake, 50)

    def test_duplicate_blocked(self):
        d = RiskManager(RiskConfig()).check(self.signal(), 10, self.state(placed_keys={"e1|h2h|home"}))
        self.assertFalse(d.allowed)

    def test_daily_loss_halts(self):
        rm = RiskManager(RiskConfig(daily_loss_limit_pct=0.1))
        self.assertIsNotNone(rm.halt_reason(self.state(today_profit=-100)))
        self.assertIsNone(rm.halt_reason(self.state(today_profit=-99)))

    def test_drawdown_halts(self):
        rm = RiskManager(RiskConfig(max_drawdown_pct=0.3))
        self.assertIsNotNone(rm.halt_reason(self.state(bankroll=700, peak_bankroll=1000)))

    def test_event_exposure(self):
        rm = RiskManager(RiskConfig(max_event_exposure_pct=0.1, max_stake_pct=1))
        d = rm.check(self.signal(), 80, self.state(event_exposure={"e1": 70}))
        self.assertEqual(d.stake, 30)
        self.assertFalse(rm.check(self.signal(), 80, self.state(event_exposure={"e1": 100})).allowed)


class EngineTests(unittest.TestCase):
    def engine(self, quotes, results=None, executor=None, cfg=None):
        return Engine(cfg or Config(), StaticOdds(quotes), executor or PaperExecutor(), results,
                      Storage(), Silent())

    def test_places_and_does_not_duplicate(self):
        eng = self.engine(market())
        self.assertEqual(len(eng.process(market(), now=NOW)), 1)
        self.assertEqual(eng.process(market(), now=NOW), [])
        self.assertEqual(len(eng.storage.bets()), 1)

    def test_settlement_updates_bankroll(self):
        eng = self.engine(market(), results=FixedResults(BetStatus.WON))
        bet = eng.process(market(), now=NOW)[0]
        self.assertEqual(eng.settle(now=NOW), 1)
        stats = eng.stats()
        self.assertEqual(stats.won, 1)
        self.assertAlmostEqual(stats.bankroll, 1000 + bet.stake * 1.3)

    def test_rejected_bet_recorded_and_retried(self):
        class Reject(Executor):
            def place(self, bet):
                return PlacementResult(False, message="odds changed")

        eng = self.engine(market(), executor=Reject())
        self.assertEqual(eng.process(market(), now=NOW), [])
        self.assertEqual(eng.storage.bets()[0].status, BetStatus.REJECTED)
        self.assertNotIn("e1|h2h|home", eng.storage.placed_keys())

    def test_daily_loss_limit_stops_betting(self):
        cfg = Config(risk=RiskConfig(daily_loss_limit_pct=0.01))
        eng = self.engine([], results=FixedResults(BetStatus.LOST), cfg=cfg)
        eng.process(market("e1"), now=NOW)
        eng.settle(now=NOW)
        self.assertEqual(eng.process(market("e2"), now=NOW), [])


class FilesAndBacktestTests(unittest.TestCase):
    def test_example_files_parse(self):
        quotes = FileOddsProvider(ROOT / "examples" / "odds.json").fetch()
        self.assertTrue(quotes)
        self.assertGreater(quotes[0].start_time, datetime.now(timezone.utc))

    def test_backtest_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = Path(tmp) / "r.json"
            res.write_text(json.dumps({"e1": {"h2h": "home"}, "e2": {"h2h": "away"}}))
            quotes = market("e1", start=NOW) + market("e2", start=NOW + timedelta(hours=5))
            stats = run_backtest(Config(), quotes, FileResultsProvider(res))
        self.assertEqual((stats.won, stats.lost), (1, 1))

    def test_example_config_loads(self):
        cfg = load_config(ROOT / "config.example.toml")
        self.assertTrue(cfg.dry_run)

    def test_invalid_config_rejected(self):
        with self.assertRaises(ValueError):
            validate(Config(strategy=StrategyConfig(min_edge=0.5, max_edge=0.1)))
        with self.assertRaises(ValueError):
            validate(Config(dry_run=False))


class StorageTests(unittest.TestCase):
    def test_roundtrip(self):
        st = Storage()
        bet = st.save(Bet(BetSignal(quote("home", "soft", 2.3), 0.5, 0.15), 10, placed_at=NOW))
        st.settle(bet.id, BetStatus.LOST, at=NOW)
        loaded = st.bets()[0]
        self.assertEqual(loaded.status, BetStatus.LOST)
        self.assertEqual(loaded.profit, -10)
        self.assertEqual(loaded.signal.quote.start_time, NOW + timedelta(hours=2))


if __name__ == "__main__":
    unittest.main()
