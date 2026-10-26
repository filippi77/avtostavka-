import json
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
    pref_wallet TEXT NOT NULL DEFAULT 'tour',
    last_spin   INTEGER NOT NULL DEFAULT 0,
    -- магазин: значок у имени, VIP до какого времени, купленные попытки крутилки
    badge       TEXT NOT NULL DEFAULT '',
    vip_until   INTEGER NOT NULL DEFAULT 0,
    extra_spins INTEGER NOT NULL DEFAULT 0
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
-- Дуэли: двое угадывают масть игрока в games_total играх подряд начиная с start_game.
CREATE TABLE IF NOT EXISTS duels (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    message_id    INTEGER,
    challenger_id INTEGER NOT NULL REFERENCES users(id),
    opponent_id   INTEGER REFERENCES users(id),  -- NULL: открытый вызов, принять может любой
    stake         INTEGER NOT NULL,
    games_total   INTEGER NOT NULL,
    start_game    INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending',  -- pending | active | finished | declined | expired
    winner_id     INTEGER,
    created_at    INTEGER NOT NULL,
    started_at    INTEGER
);
CREATE TABLE IF NOT EXISTS duel_picks (
    duel_id     INTEGER NOT NULL REFERENCES duels(id),
    game        INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    suit        TEXT NOT NULL,
    hit         INTEGER,  -- NULL пока игра не рассчитана
    PRIMARY KEY (duel_id, game, user_id)
);
-- Рассчитанные игры дуэли (в том числе те, где кто-то не выбрал масть).
CREATE TABLE IF NOT EXISTS duel_games (
    duel_id     INTEGER NOT NULL REFERENCES duels(id),
    game        INTEGER NOT NULL,
    PRIMARY KEY (duel_id, game)
);
-- Пенальти: команды и коэффициенты игры из последнего поста канала до её начала.
CREATE TABLE IF NOT EXISTS penalty_games (
    number      INTEGER PRIMARY KEY,
    home        TEXT NOT NULL,
    away        TEXT NOT NULL,
    odds        TEXT NOT NULL,  -- JSON: {"1": 1.92, "2": 1.89, "O": 1.66, "U": 2.09}
    line        REAL,
    updated_at  INTEGER NOT NULL
);
-- Активность за неделю (week — начало недели, unix): очки за сообщения, ставки, дуэли.
CREATE TABLE IF NOT EXISTS activity (
    week        INTEGER NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    points      INTEGER NOT NULL DEFAULT 0,
    last_msg_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (week, user_id)
);
-- Внезапные раздачи в чате: первые N нажавших получают фишки (или звёзды от админа).
CREATE TABLE IF NOT EXISTS drops (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     INTEGER NOT NULL,
    message_id  INTEGER,
    amount      INTEGER NOT NULL,      -- фишек каждому; 0 — звёздная раздача
    stars_prize TEXT,
    winners_max INTEGER NOT NULL,
    created_at  INTEGER NOT NULL,
    closed      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS drop_claims (
    drop_id     INTEGER NOT NULL REFERENCES drops(id),
    user_id     INTEGER NOT NULL,
    claimed_at  INTEGER NOT NULL,
    PRIMARY KEY (drop_id, user_id)
);
-- Звания в чате, выданные ботом через права админа: снимаются, когда срок вышел.
CREATE TABLE IF NOT EXISTS titles (
    chat_id     INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    title       TEXT NOT NULL,
    until       INTEGER NOT NULL,
    PRIMARY KEY (chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS purchases (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    item        TEXT NOT NULL,
    price       INTEGER NOT NULL,
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
        await self._migrate()
        await self.conn.commit()

    async def _migrate(self) -> None:
        """Добавляет столбцы, появившиеся в новых версиях, в базу, созданную старой."""
        added = {"users": {
            "last_spin": "INTEGER NOT NULL DEFAULT 0",
            "badge": "TEXT NOT NULL DEFAULT ''",
            "vip_until": "INTEGER NOT NULL DEFAULT 0",
            "extra_spins": "INTEGER NOT NULL DEFAULT 0",
        }}
        for table, columns in added.items():
            cur = await self.conn.execute(f"PRAGMA table_info({table})")
            existing = {row["name"] for row in await cur.fetchall()}
            for name, ddl in columns.items():
                if name not in existing:
                    await self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")

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

    async def claim_spin(self, user_id: int, period: int = 86400) -> int:
        """Отмечает попытку крутилки и возвращает 0, либо возвращает секунды до следующей."""
        now = int(time.time())
        cur = await self.conn.execute(
            "UPDATE users SET last_spin = ? WHERE id = ? AND last_spin <= ?", (now, user_id, now - period)
        )
        if not cur.rowcount:
            # сегодняшняя попытка потрачена — берём купленную в магазине, если есть
            cur = await self.conn.execute(
                "UPDATE users SET extra_spins = extra_spins - 1 WHERE id = ? AND extra_spins > 0", (user_id,)
            )
        await self.conn.commit()
        if cur.rowcount:
            return 0
        user = await self.get_user(user_id)
        return user["last_spin"] + period - now

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
            "SELECT id, (CASE WHEN users.badge != '' THEN users.badge || ' ' ELSE '' END || users.name) AS name, balance FROM users ORDER BY balance DESC, id LIMIT ?", (limit,)
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
            "SELECT b.*, (CASE WHEN u.badge != '' THEN u.badge || ' ' ELSE '' END || u.name) AS name FROM bets b JOIN users u ON u.id = b.user_id "
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

    async def mark_game_seen(self, number: int, fresh_after: int, wrap: int = 1440) -> None:
        """Отмечает, что игра началась: ставки на неё больше не принимаются.

        Номера игр повторяются по кругу, поэтому старую запись с тем же
        номером (старше fresh_after) считаем новой игрой. Последняя игра
        не откатывается назад, если канал отредактировал пост старой игры.
        """
        now = int(time.time())
        await self.conn.execute(
            "INSERT INTO games(number, seen_at) VALUES (?, ?) "
            "ON CONFLICT(number) DO UPDATE SET seen_at = excluded.seen_at, settled_at = NULL "
            "WHERE games.seen_at < ?",
            (number, now, fresh_after),
        )
        last = await self.last_game()
        if last is None or 0 < (number - last) % wrap < wrap // 2:
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
            "SELECT e.*, (CASE WHEN u.badge != '' THEN u.badge || ' ' ELSE '' END || u.name) AS name, u.username, u.created_at AS user_created_at "
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

    # --- пенальти ------------------------------------------------------------

    async def save_penalty_game(self, number: int, home: str, away: str, odds: dict, line: float | None) -> None:
        await self.conn.execute(
            "INSERT INTO penalty_games(number, home, away, odds, line, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(number) DO UPDATE SET home = excluded.home, away = excluded.away, "
            "odds = excluded.odds, line = excluded.line, updated_at = excluded.updated_at",
            (number, home, away, json.dumps(odds), line, int(time.time())),
        )
        await self.conn.commit()

    async def get_penalty_game(self, number: int, since: int = 0) -> dict | None:
        cur = await self.conn.execute(
            "SELECT * FROM penalty_games WHERE number = ? AND updated_at >= ?", (number, since)
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {"home": row["home"], "away": row["away"], "odds": json.loads(row["odds"]), "line": row["line"]}

    # --- дуэли --------------------------------------------------------------

    async def create_duel(self, chat_id: int, challenger_id: int, opponent_id: int | None,
                          stake: int, games_total: int) -> int:
        cur = await self.conn.execute(
            "INSERT INTO duels(chat_id, challenger_id, opponent_id, stake, games_total, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, challenger_id, opponent_id, stake, games_total, int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_duel_message(self, duel_id: int, message_id: int) -> None:
        await self.conn.execute("UPDATE duels SET message_id = ? WHERE id = ?", (message_id, duel_id))
        await self.conn.commit()

    async def get_duel(self, duel_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute(
            "SELECT d.*, (CASE WHEN c.badge != '' THEN c.badge || ' ' ELSE '' END || c.name) AS challenger_name, (CASE WHEN o.badge != '' THEN o.badge || ' ' ELSE '' END || o.name) AS opponent_name FROM duels d "
            "JOIN users c ON c.id = d.challenger_id LEFT JOIN users o ON o.id = d.opponent_id WHERE d.id = ?",
            (duel_id,),
        )
        return await cur.fetchone()

    async def user_busy_in_duel(self, user_id: int) -> bool:
        cur = await self.conn.execute(
            "SELECT 1 FROM duels WHERE status IN ('pending', 'active') AND (challenger_id = ? OR opponent_id = ?)",
            (user_id, user_id),
        )
        return await cur.fetchone() is not None

    async def accept_duel(self, duel_id: int, opponent_id: int, start_game: int) -> bool:
        """Списывает ставки с обоих и запускает дуэль. False — если у кого-то не хватает фишек."""
        duel = await self.get_duel(duel_id)
        if not duel or duel["status"] != "pending":
            return False
        for uid in (duel["challenger_id"], opponent_id):
            cur = await self.conn.execute(
                "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?", (duel["stake"], uid, duel["stake"])
            )
            if not cur.rowcount:
                await self.conn.rollback()
                return False
        await self.conn.execute(
            "UPDATE duels SET status = 'active', opponent_id = ?, start_game = ?, started_at = ? WHERE id = ?",
            (opponent_id, start_game, int(time.time()), duel_id),
        )
        await self.conn.commit()
        return True

    async def set_duel_games(self, duel_id: int, games_total: int) -> bool:
        cur = await self.conn.execute(
            "UPDATE duels SET games_total = ? WHERE id = ? AND status = 'pending'", (games_total, duel_id)
        )
        await self.conn.commit()
        return bool(cur.rowcount)

    async def set_duel_status(self, duel_id: int, status: str, only_from: str) -> bool:
        cur = await self.conn.execute(
            "UPDATE duels SET status = ? WHERE id = ? AND status = ?", (status, duel_id, only_from)
        )
        await self.conn.commit()
        return bool(cur.rowcount)

    async def active_duels(self) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT id FROM duels WHERE status = 'active'")
        return [await self.get_duel(row["id"]) for row in await cur.fetchall()]

    async def stale_pending_duels(self, older_than: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT id FROM duels WHERE status = 'pending' AND created_at < ?", (older_than,)
        )
        return [await self.get_duel(row["id"]) for row in await cur.fetchall()]

    async def set_duel_pick(self, duel_id: int, game: int, user_id: int, suit: str) -> None:
        await self.conn.execute(
            "INSERT INTO duel_picks(duel_id, game, user_id, suit) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(duel_id, game, user_id) DO UPDATE SET suit = excluded.suit WHERE duel_picks.hit IS NULL",
            (duel_id, game, user_id, suit),
        )
        await self.conn.commit()

    async def duel_picks(self, duel_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM duel_picks WHERE duel_id = ?", (duel_id,))
        return await cur.fetchall()

    async def settle_duel_game(self, duel_id: int, game: int, player_suits: set[str]) -> bool:
        """Отмечает угадавших в игре. False — если игра уже рассчитана."""
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO duel_games(duel_id, game) VALUES (?, ?)", (duel_id, game)
        )
        if not cur.rowcount:
            await self.conn.commit()
            return False
        for pick in await self.duel_picks(duel_id):
            if pick["game"] == game:
                await self.conn.execute(
                    "UPDATE duel_picks SET hit = ? WHERE duel_id = ? AND game = ? AND user_id = ?",
                    (int(pick["suit"] in player_suits), duel_id, game, pick["user_id"]),
                )
        await self.conn.commit()
        return True

    async def duel_settled_games(self, duel_id: int) -> set[int]:
        cur = await self.conn.execute("SELECT game FROM duel_games WHERE duel_id = ?", (duel_id,))
        return {row["game"] for row in await cur.fetchall()}

    async def finish_duel(self, duel_id: int, winner_id: int | None) -> bool:
        """Завершает дуэль: победителю весь банк, при ничьей ставки возвращаются."""
        duel = await self.get_duel(duel_id)
        cur = await self.conn.execute(
            "UPDATE duels SET status = 'finished', winner_id = ? WHERE id = ? AND status = 'active'",
            (winner_id, duel_id),
        )
        if not cur.rowcount:
            await self.conn.commit()
            return False
        if winner_id is None:
            for uid in (duel["challenger_id"], duel["opponent_id"]):
                await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (duel["stake"], uid))
        else:
            await self.conn.execute(
                "UPDATE users SET balance = balance + ? WHERE id = ?", (duel["stake"] * 2, winner_id)
            )
        await self.conn.commit()
        return True

    async def duel_stats(self, user_id: int) -> tuple[int, int, int]:
        """(побед, поражений, ничьих) в завершённых дуэлях."""
        cur = await self.conn.execute(
            "SELECT SUM(winner_id = ?) AS w, SUM(winner_id IS NOT NULL AND winner_id != ?) AS l, "
            "SUM(winner_id IS NULL) AS d FROM duels "
            "WHERE status = 'finished' AND (challenger_id = ? OR opponent_id = ?)",
            (user_id, user_id, user_id, user_id),
        )
        row = await cur.fetchone()
        return row["w"] or 0, row["l"] or 0, row["d"] or 0

    # --- активность ---------------------------------------------------------

    async def add_activity(self, week: int, user_id: int, points: int, message_cooldown: int | None = None) -> bool:
        """Начисляет очки активности. С message_cooldown — не чаще раза в столько секунд
        (для сообщений в чате). Возвращает, начислено ли."""
        now = int(time.time())
        await self.conn.execute(
            "INSERT OR IGNORE INTO activity(week, user_id) VALUES (?, ?)", (week, user_id)
        )
        if message_cooldown is None:
            cur = await self.conn.execute(
                "UPDATE activity SET points = points + ? WHERE week = ? AND user_id = ?", (points, week, user_id)
            )
        else:
            cur = await self.conn.execute(
                "UPDATE activity SET points = points + ?, last_msg_at = ? "
                "WHERE week = ? AND user_id = ? AND last_msg_at <= ?",
                (points, now, week, user_id, now - message_cooldown),
            )
        await self.conn.commit()
        return bool(cur.rowcount)

    async def activity_top(self, week: int, limit: int = 10) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT a.user_id, a.points, (CASE WHEN u.badge != '' THEN u.badge || ' ' ELSE '' END || u.name) AS name, u.username FROM activity a JOIN users u ON u.id = a.user_id "
            "WHERE a.week = ? AND a.points > 0 ORDER BY a.points DESC, a.last_msg_at LIMIT ?",
            (week, limit),
        )
        return await cur.fetchall()

    async def activity_of(self, week: int, user_id: int) -> tuple[int, int | None]:
        """(очки, место) игрока за неделю; место None, если очков нет."""
        cur = await self.conn.execute("SELECT points FROM activity WHERE week = ? AND user_id = ?", (week, user_id))
        row = await cur.fetchone()
        points = row["points"] if row else 0
        if not points:
            return 0, None
        cur = await self.conn.execute(
            "SELECT COUNT(*) + 1 AS n FROM activity WHERE week = ? AND points > ?", (week, points)
        )
        return points, (await cur.fetchone())["n"]

    # --- раздачи ------------------------------------------------------------

    async def create_drop(self, chat_id: int, amount: int, winners_max: int, stars_prize: str | None = None) -> int:
        cur = await self.conn.execute(
            "INSERT INTO drops(chat_id, amount, stars_prize, winners_max, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, amount, stars_prize, winners_max, int(time.time())),
        )
        await self.conn.commit()
        return cur.lastrowid

    async def set_drop_message(self, drop_id: int, message_id: int) -> None:
        await self.conn.execute("UPDATE drops SET message_id = ? WHERE id = ?", (message_id, drop_id))
        await self.conn.commit()

    async def get_drop(self, drop_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute("SELECT * FROM drops WHERE id = ?", (drop_id,))
        return await cur.fetchone()

    async def claim_drop(self, drop_id: int, user_id: int) -> str:
        """"ok" — успел и получил приз, "again" — уже забирал, "late" — раздача закончилась."""
        drop = await self.get_drop(drop_id)
        if not drop or drop["closed"]:
            return "late"
        cur = await self.conn.execute(
            "INSERT OR IGNORE INTO drop_claims(drop_id, user_id, claimed_at) "
            "SELECT ?, ?, ? WHERE (SELECT COUNT(*) FROM drop_claims WHERE drop_id = ?) < ?",
            (drop_id, user_id, int(time.time()), drop_id, drop["winners_max"]),
        )
        if not cur.rowcount:
            await self.conn.commit()
            claimed = await self.conn.execute(
                "SELECT 1 FROM drop_claims WHERE drop_id = ? AND user_id = ?", (drop_id, user_id)
            )
            return "again" if await claimed.fetchone() else "late"
        if drop["amount"]:
            await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (drop["amount"], user_id))
        count = await self.conn.execute("SELECT COUNT(*) AS n FROM drop_claims WHERE drop_id = ?", (drop_id,))
        if (await count.fetchone())["n"] >= drop["winners_max"]:
            await self.conn.execute("UPDATE drops SET closed = 1 WHERE id = ?", (drop_id,))
        await self.conn.commit()
        return "ok"

    async def drop_winners(self, drop_id: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(
            "SELECT c.user_id, (CASE WHEN u.badge != '' THEN u.badge || ' ' ELSE '' END || u.name) AS name, u.username FROM drop_claims c JOIN users u ON u.id = c.user_id "
            "WHERE c.drop_id = ? ORDER BY c.claimed_at, c.rowid",
            (drop_id,),
        )
        return await cur.fetchall()

    async def close_drop(self, drop_id: int) -> bool:
        cur = await self.conn.execute("UPDATE drops SET closed = 1 WHERE id = ? AND closed = 0", (drop_id,))
        await self.conn.commit()
        return bool(cur.rowcount)

    async def open_drops_older_than(self, ts: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM drops WHERE closed = 0 AND created_at < ?", (ts,))
        return await cur.fetchall()

    # --- магазин ------------------------------------------------------------

    async def spend(self, user_id: int, price: int, item: str) -> bool:
        """Списывает фишки за покупку. False — не хватает."""
        cur = await self.conn.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?", (price, user_id, price)
        )
        if cur.rowcount:
            await self.conn.execute(
                "INSERT INTO purchases(user_id, item, price, created_at) VALUES (?, ?, ?, ?)",
                (user_id, item, price, int(time.time())),
            )
        await self.conn.commit()
        return bool(cur.rowcount)

    async def refund_purchase(self, user_id: int, price: int, item: str) -> None:
        await self.conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (price, user_id))
        await self.conn.execute(
            "INSERT INTO purchases(user_id, item, price, created_at) VALUES (?, ?, ?, ?)",
            (user_id, f"refund:{item}", -price, int(time.time())),
        )
        await self.conn.commit()

    async def set_badge(self, user_id: int, badge: str) -> None:
        await self.conn.execute("UPDATE users SET badge = ? WHERE id = ?", (badge, user_id))
        await self.conn.commit()

    async def extend_vip(self, user_id: int, seconds: int) -> int:
        """Продлевает VIP (от текущего конца, если он ещё действует). Возвращает новый конец."""
        now = int(time.time())
        await self.conn.execute(
            "UPDATE users SET vip_until = MAX(vip_until, ?) + ? WHERE id = ?", (now, seconds, user_id)
        )
        await self.conn.commit()
        return (await self.get_user(user_id))["vip_until"]

    async def add_extra_spin(self, user_id: int) -> None:
        await self.conn.execute("UPDATE users SET extra_spins = extra_spins + 1 WHERE id = ?", (user_id,))
        await self.conn.commit()

    async def set_title(self, chat_id: int, user_id: int, title: str, until: int) -> None:
        await self.conn.execute(
            "INSERT OR REPLACE INTO titles(chat_id, user_id, title, until) VALUES (?, ?, ?, ?)",
            (chat_id, user_id, title, until),
        )
        await self.conn.commit()

    async def get_title(self, chat_id: int, user_id: int) -> aiosqlite.Row | None:
        cur = await self.conn.execute("SELECT * FROM titles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        return await cur.fetchone()

    async def expired_titles(self, now: int) -> list[aiosqlite.Row]:
        cur = await self.conn.execute("SELECT * FROM titles WHERE until <= ?", (now,))
        return await cur.fetchall()

    async def delete_title(self, chat_id: int, user_id: int) -> None:
        await self.conn.execute("DELETE FROM titles WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
        await self.conn.commit()

    async def shop_sales(self) -> tuple[int, int]:
        """(покупок, фишек потрачено) без возвратов."""
        cur = await self.conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(price), 0) AS chips FROM purchases WHERE price > 0"
        )
        row = await cur.fetchone()
        return row["n"], row["chips"]
