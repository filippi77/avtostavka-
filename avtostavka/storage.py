"""Хранение истории ставок в SQLite."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .models import Bet, BetSignal, BetStatus, OddsQuote, utcnow

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_key TEXT NOT NULL,
    event_id TEXT NOT NULL,
    event_name TEXT NOT NULL,
    sport TEXT NOT NULL,
    start_time TEXT NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    odds REAL NOT NULL,
    fair_probability REAL NOT NULL,
    edge REAL NOT NULL,
    stake REAL NOT NULL,
    status TEXT NOT NULL,
    external_id TEXT,
    placed_at TEXT NOT NULL,
    settled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_bets_key ON bets(signal_key);
"""

_ACTIVE = (BetStatus.PENDING.value, BetStatus.WON.value, BetStatus.LOST.value, BetStatus.VOID.value)


def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


class Storage:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def save(self, bet: Bet) -> Bet:
        q = bet.signal.quote
        cur = self.conn.execute(
            """INSERT INTO bets (signal_key, event_id, event_name, sport, start_time, market,
               selection, bookmaker, odds, fair_probability, edge, stake, status, external_id,
               placed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                bet.signal.key, q.event_id, q.event_name, q.sport, _ts(q.start_time), q.market,
                q.selection, q.bookmaker, q.odds, bet.signal.fair_probability, bet.signal.edge,
                bet.stake, bet.status.value, bet.external_id, _ts(bet.placed_at),
            ),
        )
        self.conn.commit()
        bet.id = cur.lastrowid
        return bet

    def settle(self, bet_id: int, status: BetStatus, at: datetime | None = None) -> None:
        self.conn.execute(
            "UPDATE bets SET status = ?, settled_at = ? WHERE id = ? AND status = ?",
            (status.value, _ts(at or utcnow()), bet_id, BetStatus.PENDING.value),
        )
        self.conn.commit()

    def _row_to_bet(self, r: sqlite3.Row) -> Bet:
        quote = OddsQuote(
            event_id=r["event_id"], event_name=r["event_name"], sport=r["sport"],
            start_time=datetime.fromisoformat(r["start_time"]), market=r["market"],
            selection=r["selection"], bookmaker=r["bookmaker"], odds=r["odds"],
        )
        signal = BetSignal(quote=quote, fair_probability=r["fair_probability"], edge=r["edge"])
        return Bet(
            signal=signal, stake=r["stake"], status=BetStatus(r["status"]),
            placed_at=datetime.fromisoformat(r["placed_at"]), external_id=r["external_id"],
            id=r["id"],
            settled_at=datetime.fromisoformat(r["settled_at"]) if r["settled_at"] else None,
        )

    def bets(self, status: BetStatus | None = None) -> list[Bet]:
        if status is None:
            rows = self.conn.execute("SELECT * FROM bets ORDER BY id").fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM bets WHERE status = ? ORDER BY id", (status.value,)
            ).fetchall()
        return [self._row_to_bet(r) for r in rows]

    def placed_keys(self) -> set[str]:
        rows = self.conn.execute(
            f"SELECT DISTINCT signal_key FROM bets WHERE status IN ({','.join('?' * len(_ACTIVE))})",
            _ACTIVE,
        ).fetchall()
        return {r[0] for r in rows}
