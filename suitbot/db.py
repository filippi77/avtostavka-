import time

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    username    TEXT,
    balance     INTEGER NOT NULL,
    last_bonus  INTEGER NOT NULL DEFAULT 0,
    created_at  INTEGER NOT NULL DEFAULT 0,
    -- что выбрано на кнопках карточки игры: сумма и кошелёк (main | tour)
    pref_stake  INTEGER NOT NULL DEFAULT 50,
    pref_wallet TEXT NOT NULL DEFAULT 'tour'
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
    wallet      TEXT NOT NULL DEFAULT 'main',  -- main | tour
    tournament_id INTEGER REFERENCES tournaments(id),
    created_at  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS bets_open ON bets(status, game);
CREATE TABLE IF NOT EXISTS tournaments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_at   INTEGER NOT NULL,
    ends_at     INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active'  -- active | finished
);
-- Турнирные фишки живут отдельно от обычных: их нельзя купить или получить бонусом.
CREATE TABLE IF NOT EXISTS tournament_entries (
    tournament_id INTEGER NOT NULL REFERENCES tournaments(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    balance     INTEGER NOT NULL,
    bets_count  INTEGER NOT NULL DEFAULT 0,
    joined_at   INTEGER NOT NULL,
    PRIMARY KEY (tournament_id, user_id)
);
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
-- Карточки игр с кнопками ставок, которые бот публикует в чате.
CREATE TABLE IF NOT EXISTS cards (
    game        INTEGER NOT NULL,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (game, chat_id)
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

    async def ensure_user(
        self, user_id: int, name: str, start_balance: int, username: str | None = None
    ) -> aiosqlite.Row:
        await self.conn.execute(
            "INSERT INTO users(id, name, username, balance, created_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name = excluded.name, username = excluded.username",
            (user_id, name, username, start_balance, int(time.time())),
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

    async def users_count(self) -> int:
        cur = await self.conn.execute("SELECT COUNT(*) AS n FROM users")
        return (await cur.fetchone())["n"]

    async def give_all(self, amount: int, tournament_id: int | None = None) -> int:
        """Начисляет всем игрокам (или всем участникам турнира). Возвращает, скольким."""
        if tournament_id is None:
            cur = await self.conn.execute("UPDATE users SET balance = balance + ?", (amount,))
        else:
            cur = await self.conn.execute(
                "UPDATE tournament_entries SET balance = balance + ? WHERE tournament_id = ?",
                (amount, tournament_id),
            )
        await self.conn.commit()
        return cur.rowcount

    async def set_pref(self, user_id: int, stake: int | None = None, wallet: str | None = None) -> None:
        if stake is not None:
            await self.conn.execute("UPDATE users SET pref_stake = ? WHERE id = ?", (stake, user_id))
        if wallet is not None:
            await self.conn.execute("UPDATE users SET pref_wallet = ? WHERE id = ?", (wallet, user_id))
        await self.conn.commit()

    async def top(self, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT id, name, balance FROM users ORDER BY balance DESC, id LIMIT ?", (limit,)
        )
        return await cur.fetchall()

    async def user_rank(self, user_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) + 1 AS n FROM users WHERE balance > (SELECT balance FROM users WHERE id = ?)",
            (user_id,),
        )
        return (await cur.fetchone())["n"]

    # --- ставки -------------------------------------------------------------

    async def place_bet(
        self, user_id: int, chat_id: int, game: int, kind: str, pick: str, amount: int, coef: float,
        tournament_id: int | None = None,
    ) -> int:
        # Списание и запись ставки — одной транзакцией, чтобы баланс не ушёл в минус.
        if tournament_id is None:
            cur = await self.conn.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?",
                (amount, user_id, amount),
            )
        else:
            cur = await self.conn.execute(
                "UPDATE tournament_entries SET balance = balance - ?, bets_count = bets_count + 1 "
                "WHERE tournament_id = ? AND user_id = ? AND balance >= ?",
                (amount, tournament_id, user_id, amount),
            )
        if not cur.rowcount:
            await self.conn.rollback()
            raise InsufficientFunds
        cur = await self.conn.execute(
            "INSERT INTO bets(user_id, chat_id, game, kind, pick, amount, coef, wallet, tournament_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, game, kind, pick, amount, coef,
             "main" if tournament_id is None else "tour", tournament_id, int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def _credit(self, bet: aiosqlite.Row, amount: int) -> None:
        if bet["wallet"] == "tour":
            await self.conn.execute(
                "UPDATE tournament_entries SET balance = balance + ? WHERE tournament_id = ? AND user_id = ?",
                (amount, bet["tournament_id"], bet["user_id"]),
            )
        else:
            await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, bet["user_id"]))

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
            cur2 = await self.conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,))
            await self._credit(await cur2.fetchone(), payout)
        await self.conn.commit()
        return bool(cur.rowcount)

    async def _refund(self, bets: list[aiosqlite.Row]) -> None:
        for bet in bets:
            await self.conn.execute(
                "UPDATE bets SET status = 'refunded', payout = amount WHERE id = ?", (bet["id"],)
            )
            await self._credit(bet, bet["amount"])
        await self.conn.commit()

    async def refund_stale_bets(self, older_than: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM bets WHERE status = 'open' AND created_at < ?", (older_than,)
        )
        stale = await cur.fetchall()
        await self._refund(stale)
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

    async def game_seen_at(self, number: int) -> int | None:
        cur = await self.conn.execute("SELECT seen_at FROM games WHERE number = ?", (number,))
        row = await cur.fetchone()
        return row["seen_at"] if row else None

    async def last_game(self) -> int | None:
        value = await self.get_state("last_game")
        return int(value) if value is not None else None

    # --- настройки из панели управления --------------------------------------

    async def get_state(self, key: str, default: str | None = None) -> str | None:
        cur = await self.conn.execute("SELECT value FROM state WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row["value"] if row else default

    async def set_state(self, key: str, value: str) -> None:
        await self.conn.execute(
            "INSERT INTO state(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        await self.conn.commit()

    # --- карточки игр -------------------------------------------------------

    async def get_card(self, game: int, chat_id: int, since: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM cards WHERE game = ? AND chat_id = ? AND created_at >= ?", (game, chat_id, since)
        )
        return await cur.fetchone()

    async def save_card(self, game: int, chat_id: int, message_id: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO cards(game, chat_id, message_id, created_at) VALUES (?, ?, ?, ?)",
            (game, chat_id, message_id, int(time.time())),
        )
        await self.conn.commit()

    async def open_cards_for_game(self, game: int, since: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT * FROM cards WHERE game = ? AND closed = 0 AND created_at >= ?", (game, since)
        )
        return await cur.fetchall()

    async def close_card(self, game: int, chat_id: int) -> None:
        await self.conn.execute("UPDATE cards SET closed = 1 WHERE game = ? AND chat_id = ?", (game, chat_id))
        await self.conn.commit()

    async def bet_counts(self, game: int, chat_id: int, since: int) -> dict[str, int]:
        cur = await self.conn.execute(
            "SELECT pick, COUNT(*) AS n FROM bets WHERE game = ? AND chat_id = ? AND created_at >= ? GROUP BY pick",
            (game, chat_id, since),
        )
        return {row["pick"]: row["n"] for row in await cur.fetchall()}

    # --- платежи ------------------------------------------------------------

    async def sales_summary(self, since: int = 0) -> tuple[int, int, int]:
        """(покупок, звёзд, покупателей) с момента since."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(stars), 0) AS stars, COUNT(DISTINCT user_id) AS buyers "
            "FROM payments WHERE created_at >= ?",
            (since,),
        )
        row = await cur.fetchone()
        return row["n"], row["stars"], row["buyers"]

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

    # --- турниры ------------------------------------------------------------

    async def active_tournament(self) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM tournaments WHERE status = 'active' ORDER BY id DESC LIMIT 1"
        )
        return await cur.fetchone()

    async def get_tournament(self, tournament_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute("SELECT * FROM tournaments WHERE id = ?", (tournament_id,))
        return await cur.fetchone()

    async def create_tournament(self, starts_at: int, ends_at: int) -> int:
        cur = await self.conn.execute(
            "INSERT INTO tournaments(starts_at, ends_at) VALUES (?, ?)", (starts_at, ends_at)
        )
        await self.conn.commit()
        return cur.lastrowid

    async def join_tournament(self, tournament_id: int, user_id: int, start_balance: int) -> tuple[aiosqlite.Row, bool]:
        """Возвращает (участие, только что вступил)."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO tournament_entries(tournament_id, user_id, balance, joined_at) "
            "VALUES (?, ?, ?, ?)",
            (tournament_id, user_id, start_balance, int(time.time())),
        )
        await self.conn.commit()
        return await self.get_entry(tournament_id, user_id), bool(cur.rowcount)

    async def get_entry(self, tournament_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT * FROM tournament_entries WHERE tournament_id = ? AND user_id = ?",
            (tournament_id, user_id),
        )
        return await cur.fetchone()

    async def standings(self, tournament_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT e.*, u.name, u.username, u.created_at AS user_created_at "
            "FROM tournament_entries e JOIN users u ON u.id = e.user_id "
            "WHERE e.tournament_id = ? "
            "ORDER BY e.balance DESC, e.bets_count DESC, e.joined_at",
            (tournament_id,),
        )
        return await cur.fetchall()

    async def finish_tournament(self, tournament_id: int) -> bool:
        """Закрывает турнир; нерассчитанные ставки возвращаются до подсчёта мест."""
        cur = await self.conn.execute(
            "UPDATE tournaments SET status = 'finished' WHERE id = ? AND status = 'active'",
            (tournament_id,),
        )
        if not cur.rowcount:
            await self.conn.commit()
            return False
        cur = await self.conn.execute(
            "SELECT * FROM bets WHERE status = 'open' AND tournament_id = ?", (tournament_id,)
        )
        await self._refund(await cur.fetchall())
        return True

    async def entries_count(self, tournament_id: int) -> int:
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n FROM tournament_entries WHERE tournament_id = ?", (tournament_id,)
        )
        return (await cur.fetchone())["n"]

    async def tournament_chats(self, tournament_id: int) -> list[int]:
        cur = await self.conn.execute(
            "SELECT DISTINCT chat_id FROM bets WHERE tournament_id = ? AND chat_id < 0", (tournament_id,)
        )
        return [row["chat_id"] for row in await cur.fetchall()]
