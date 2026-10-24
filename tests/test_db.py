import asyncio
import time

import pytest

from suitbot.db import DB, InsufficientFunds


def run(coro):
    return asyncio.run(coro)


async def fresh_db(tmp_path) -> DB:
    db = DB(str(tmp_path / "t.sqlite3"))
    await db.open()
    await db.ensure_user(1, "Руслан", 100)
    return db


def test_bet_and_settle(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        bet_id = await db.place_bet(1, -100, 208, "suit", "♥", 40, 1.9)
        assert (await db.get_user(1))["balance"] == 60
        assert await db.settle_bet(bet_id, True, 76)
        assert not await db.settle_bet(bet_id, True, 76)  # повторный расчёт не платит
        assert (await db.get_user(1))["balance"] == 136
        await db.close()

    run(go())


def test_insufficient_funds(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        with pytest.raises(InsufficientFunds):
            await db.place_bet(1, -100, 208, "suit", "♥", 101, 1.9)
        assert (await db.get_user(1))["balance"] == 100
        assert await db.user_open_bets(1) == []
        await db.close()

    run(go())


def test_payment_is_idempotent(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        assert await db.record_payment("charge-1", 1, 50, 500)
        assert not await db.record_payment("charge-1", 1, 50, 500)
        assert (await db.get_user(1))["balance"] == 600
        await db.close()

    run(go())


def test_bonus_once_per_day(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        assert await db.claim_bonus(1, 100) == 0
        assert await db.claim_bonus(1, 100) > 0
        assert (await db.get_user(1))["balance"] == 200
        await db.close()

    run(go())


def test_game_seen_and_wraparound(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        now = int(time.time())
        await db.mark_game_seen(207, fresh_after=now - 3600)
        assert await db.last_game() == 207
        assert await db.game_seen_since(207, now - 10)
        assert not await db.game_seen_since(208, now - 10)
        await db.close()

    run(go())


def test_refund_stale(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        await db.place_bet(1, -100, 208, "side", "P", 30, 1.95)
        refunded = await db.refund_stale_bets(int(time.time()) + 1)
        assert len(refunded) == 1
        assert (await db.get_user(1))["balance"] == 100
        await db.close()

    run(go())


def test_sales_summary(tmp_path):
    async def go():
        db = await fresh_db(tmp_path)
        await db.ensure_user(2, "Алсу", 100)
        await db.record_payment("c1", 1, 5, 5000)
        await db.record_payment("c2", 1, 1, 1000)
        await db.record_payment("c3", 2, 10, 10000)
        assert await db.sales_summary() == (3, 16, 2)
        assert await db.sales_summary(int(time.time()) + 10) == (0, 0, 0)
        await db.close()

    run(go())
