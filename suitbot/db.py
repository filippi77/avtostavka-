import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    balance     INTEGER NOT NULL,
    last_bonus  INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS bets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    chat_id     INTEGER NOT NULL,
    game        INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    pick        TEXT NOT NULL,
    amount      INTEGER NOT NULL,
    coef        REAL NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',  -- open | won | lost | refunded
    payout      INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS bets_open ON bets(status, game);
CREATE TABLE IF NOT EXISTS games (
    number      INTEGER PRIMARY KEY,
    seen_at     INTEGER NOT NULL,
    settled_at  INTEGER
);
CREATE TABLE IF NOT EXISTS payments (
    charge_id   TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    stars       INTEGER NOT NULL,
    chips       INTEGER NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS state (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


class InsufficientFunds(Exception):
    pass


class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn: aiosqlite.Connection

    async def open(self) -> None:
        self.conn = await aiosqlite.connect(self.path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.executescript(SCHEMA)
        await self.conn.commit()

    async def close(self) -> None:
        await self.conn.close()

    # --- пользователи -------------------------------------------------------

    async def ensure_user(self, user_id: int, name: str, start_balance: int) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT INTO users(id, name, balance) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name",
            (user_id, name, start_balance),
        )
        await self.conn.commit()
        return await self.get_user(user_id)

    async def get_user(self, user_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        return await cur.fetchone()

    async def add_balance(self, user_id: int, delta: int) -> None:
        await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (delta, user_id))
        await self.conn.commit()

    async def claim_bonus(self, user_id: int, amount: int, period: int = 86400) -> int:
        """Выдаёт бонус и возвращает 0, либо возвращает секунды до следующего."""
        now = int(time.time())
        cur = await self.conn.execute(
            "UPDATE users SET balance = balance + ?, last_bonus = ? WHERE id = ? AND last_bonus <= ?",
            (amount, now, user_id, now - period),
        )
        await self.conn.commit()
        if cur.rowcount:
            return 0
        user = await self.get_user(user_id)
        return user["last_bonus"] + period - now

    async def top(self, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT name, balance FROM users ORDER BY balance DESC LIMIT ?", (limit,))
        return await cur.fetchall()

    # --- ставки -------------------------------------------------------------

    async def place_bet(
        self, user_id: int, chat_id: int, game: int, kind: str, pick: str, amount: int, coef: float
    ) -> int:
        # Списание и запись ставки — одной транзакцией, чтобы баланс не ушёл в минус.
        cur = await self.conn.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
            (amount, user_id, amount),
        )
        if not cur.rowcount:
            await self.conn.rollback()
            raise InsufficientFunds
        cur = await self.conn.execute(
            "INSERT INTO bets(user_id, chat_id, game, kind, pick, amount, coef, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, game, kind, pick, amount, coef, int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def open_bets_for_game(self, game: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT b.*, u.name FROM bets b JOIN users u ON u.id = b.user_id "
            "WHERE b.status = 'open' AND b.game = ?",
            (game,),
        )
        return await cur.fetchall()

    async def user_open_bets(self, user_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM bets WHERE status = 'open' AND user_id = ? ORDER BY game", (user_id,)
        )
        return await cur.fetchall()

    async def settle_bet(self, bet_id: int, won: bool, payout: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE bets SET status = ?, payout = ? WHERE id = ? AND status = 'open'",
            ("won" if won else "lost", payout, bet_id),
        )
        if cur.rowcount and payout:
            await self.conn.execute(
                "UPDATE users SET balance = balance + ? "
                "WHERE id = (SELECT user_id FROM bets WHERE id = ?)",
                (payout, bet_id),
            )
        await self.conn.commit()
        return bool(cur.rowcount)

    async def refund_stale_bets(self, older_than: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM bets WHERE status = 'open' AND created_at < ?", (older_than,)
        )
        stale = await cur.fetchall()
        for bet in stale:
            await self.conn.execute(
                "UPDATE bets SET status = 'refunded', payout = amount WHERE id = ?", (bet["id"],)
            )
            await self.conn.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?", (bet["amount"], bet["user_id"])
            )
        await self.conn.commit()
        return stale

    # --- игры ---------------------------------------------------------------

    async def mark_game_seen(self, number: int, fresh_after: int) -> None:
        """Отмечает, что по игре появился пост: ставки на неё больше не принимаются.

        Номера игр повторяются по кругу, поэтому старую запись с тем же
        номером (старше fresh_after) считаем новой игрой.
        """
        now = int(time.time())
        await self.conn.execute(
            "INSERT INTO games(number, seen_at) VALUES (?, ?) "
            "ON CONFLICT(number) DO UPDATE SET seen_at = excluded.seen_at, settled_at = NULL "
            "WHERE games.seen_at < ?",
            (number, now, fresh_after),
        )
        await self.conn.execute(
            "INSERT INTO state(key, value) VALUES ('last_game', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(number),),
        )
        await self.conn.commit()

    async def game_seen_since(self, number: int, since: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM games WHERE number = ? AND seen_at >= ?", (number, since)
        )
        return await cur.fetchone() is not None

    async def last_game(self) -> int | None:
        cur = await self.conn.execute("SELECT value FROM state WHERE key = 'last_game'")
        row = await cur.fetchone()
        return int(row["value"]) if row else None

    # --- платежи ------------------------------------------------------------

    async def record_payment(self, charge_id: str, user_id: int, stars: int, chips: int) -> bool:
        """Зачисляет фишки за оплату. Повторное событие с тем же charge_id игнорируется."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO payments(charge_id, user_id, stars, chips, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (charge_id, user_id, stars, chips, int(time.time())),
        )
        if cur.rowcount:
            await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (chips, user_id))
        await self.conn.commit()
        return bool(cur.rowcount)
