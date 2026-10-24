"""Загрузка конфигурации из TOML."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any


@dataclass
class StrategyConfig:
    # Букмекеры-ориентиры (sharp), по которым считается «честная» вероятность.
    reference_bookmakers: list[str] = field(default_factory=lambda: ["pinnacle"])
    # Букмекеры, у которых бот ставит. Пусто — любые, кроме ориентиров.
    target_bookmakers: list[str] = field(default_factory=list)
    min_edge: float = 0.03
    max_edge: float = 0.25  # слишком большой перевес — скорее ошибка в данных
    min_odds: float = 1.4
    max_odds: float = 6.0
    # Не ставить на события, до начала которых меньше N минут или больше M часов.
    min_minutes_to_start: int = 5
    max_hours_to_start: int = 48
    # Только одна ставка на рынок (исход с наибольшим перевесом).
    one_bet_per_market: bool = True
    sports: list[str] = field(default_factory=list)  # пусто — все виды спорта
    markets: list[str] = field(default_factory=list)  # пусто — все рынки


@dataclass
class StakingConfig:
    method: str = "kelly"  # fixed | percent | kelly
    fixed_amount: float = 10.0
    percent: float = 0.01
    kelly_fraction: float = 0.25
    min_stake: float = 1.0
    max_stake: float = 100.0
    round_to: float = 0.01


@dataclass
class RiskConfig:
    starting_bankroll: float = 1000.0
    max_open_bets: int = 20
    max_stake_pct: float = 0.05  # не больше 5% банка в одну ставку
    max_event_exposure_pct: float = 0.10
    daily_loss_limit_pct: float = 0.10
    max_drawdown_pct: float = 0.30  # от пика банка — полная остановка
    max_bets_per_day: int = 50


@dataclass
class ProviderConfig:
    odds_source: str = "file"  # file | theoddsapi
    odds_file: str = "examples/odds.json"
    results_file: str = "examples/results.json"
    executor: str = "paper"  # paper (свой исполнитель — см. README)
    api_key_env: str = "ODDS_API_KEY"
    regions: str = "eu"
    theoddsapi_sports: list[str] = field(default_factory=lambda: ["soccer_epl"])
    timeout_sec: float = 15.0


@dataclass
class NotifyConfig:
    telegram_token_env: str = "TELEGRAM_BOT_TOKEN"
    telegram_chat_id: str = ""


@dataclass
class Config:
    db_path: str = "avtostavka.db"
    poll_interval_sec: int = 60
    dry_run: bool = True
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    staking: StakingConfig = field(default_factory=StakingConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    provider: ProviderConfig = field(default_factory=ProviderConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)


def _build(cls: type, data: dict[str, Any]):
    known = {f.name: f for f in fields(cls)}
    unknown = set(data) - set(known)
    if unknown:
        raise ValueError(f"Неизвестные параметры в секции {cls.__name__}: {sorted(unknown)}")
    kwargs = {}
    for name, value in data.items():
        sub = _SECTIONS.get(name) if cls is Config else None
        kwargs[name] = _build(sub, value) if sub else value
    return cls(**kwargs)


_SECTIONS = {
    "strategy": StrategyConfig,
    "staking": StakingConfig,
    "risk": RiskConfig,
    "provider": ProviderConfig,
    "notify": NotifyConfig,
}


def validate(cfg: Config) -> None:
    s, st, r = cfg.strategy, cfg.staking, cfg.risk
    errors = []
    if not 0 <= s.min_edge < s.max_edge:
        errors.append("strategy: требуется 0 <= min_edge < max_edge")
    if not 1.0 < s.min_odds <= s.max_odds:
        errors.append("strategy: требуется 1 < min_odds <= max_odds")
    if st.method not in ("fixed", "percent", "kelly"):
        errors.append("staking.method: fixed | percent | kelly")
    if not 0 < st.kelly_fraction <= 1:
        errors.append("staking.kelly_fraction должен быть в (0, 1]")
    if not 0 < st.min_stake <= st.max_stake:
        errors.append("staking: требуется 0 < min_stake <= max_stake")
    if r.starting_bankroll <= 0:
        errors.append("risk.starting_bankroll должен быть > 0")
    for name in ("max_stake_pct", "max_event_exposure_pct", "daily_loss_limit_pct", "max_drawdown_pct"):
        if not 0 < getattr(r, name) <= 1:
            errors.append(f"risk.{name} должен быть в (0, 1]")
    if cfg.provider.odds_source not in ("file", "theoddsapi"):
        errors.append("provider.odds_source: file | theoddsapi")
    if not cfg.dry_run and cfg.provider.executor == "paper":
        errors.append("dry_run = false требует реального исполнителя, а не paper")
    if errors:
        raise ValueError("Ошибки конфигурации:\n  " + "\n  ".join(errors))


def load_config(path: str | os.PathLike | None) -> Config:
    if path is None:
        cfg = Config()
    else:
        with Path(path).open("rb") as fh:
            cfg = _build(Config, tomllib.load(fh))
    validate(cfg)
    return cfg
