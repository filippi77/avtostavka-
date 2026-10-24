"""Командная строка: python -m avtostavka {run,scan,stats,backtest}."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from .backtest import run_backtest
from .config import Config, load_config
from .engine import Engine
from .notifier import Notifier, TelegramNotifier
from .providers import (
    FileOddsProvider,
    FileResultsProvider,
    PaperExecutor,
    TheOddsApiProvider,
)
from .storage import Storage
from .strategy import ValueStrategy


def build_engine(cfg: Config) -> Engine:
    p = cfg.provider
    if p.odds_source == "theoddsapi":
        markets = ",".join(cfg.strategy.markets) or "h2h"
        provider = TheOddsApiProvider(os.environ.get(p.api_key_env, ""), p.theoddsapi_sports,
                                      p.regions, markets, p.timeout_sec)
        odds, results = provider, provider
    else:
        odds, results = FileOddsProvider(p.odds_file), FileResultsProvider(p.results_file)

    if p.executor != "paper":
        raise SystemExit(f"Исполнитель '{p.executor}' не подключён — см. раздел README «Реальные ставки»")
    executor = PaperExecutor()

    token = os.environ.get(cfg.notify.telegram_token_env, "")
    notifier = (TelegramNotifier(token, cfg.notify.telegram_chat_id)
                if token and cfg.notify.telegram_chat_id else Notifier())
    return Engine(cfg, odds, executor, results, Storage(cfg.db_path), notifier)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="avtostavka", description="Бот для автоставок")
    parser.add_argument("-c", "--config", default=None, help="путь к config.toml")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="запустить бота")
    run.add_argument("--once", action="store_true", help="один цикл и выход")
    sub.add_parser("scan", help="показать найденные value-ставки, ничего не ставя")
    sub.add_parser("stats", help="статистика по истории ставок")
    bt = sub.add_parser("backtest", help="бэктест на исторических данных")
    bt.add_argument("odds", help="JSON с котировками")
    bt.add_argument("results", help="JSON с результатами")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        cfg = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.cmd == "backtest":
        stats = run_backtest(cfg, FileOddsProvider(args.odds).fetch(), FileResultsProvider(args.results))
        print(stats.format())
        return 0

    engine = build_engine(cfg)
    if args.cmd == "stats":
        print(engine.stats().format())
    elif args.cmd == "scan":
        signals = ValueStrategy(cfg.strategy).generate(engine.odds.fetch())
        if not signals:
            print("Value-ставок не найдено")
        for s in signals:
            q = s.quote
            print(f"{s.edge:+6.1%}  {q.event_name} | {q.market}: {q.selection} @ {q.odds:.2f} "
                  f"({q.bookmaker}), {s.reason}")
    elif args.once:
        engine.run_once()
        print(engine.stats().format())
    else:
        engine.run_forever()
    return 0
