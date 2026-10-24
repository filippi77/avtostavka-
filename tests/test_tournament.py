import asyncio
import time
from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from suitbot import tournament as tour
from suitbot.config import Config
from suitbot.db import DB, InsufficientFunds

CFG = replace(Config(token="x"), admins={42}, tournament_chats={-100}, tournament_min_bets=2,
              tournament_min_days_in_bot=0)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


def run(coro):
    return asyncio.run(coro)


async def setup(tmp_path):
    db = DB(str(tmp_path / "t.sqlite3"))
    await db.open()
    for uid, name in ((1, "Руслан"), (2, "Алсу"), (3, "Lega")):
        await db.ensure_user(uid, name, 500, username=name.lower())
    tid = await db.create_tournament(int(time.time()), int(time.time()) + 3600)
    for uid in (1, 2, 3):
        await db.join_tournament(tid, uid, 1000)
    return db, tid


def test_week_bounds_monday_midnight():
    # Пятница 24.10.2025 15:00 по Москве → неделя с пн 20.10 до пн 27.10.
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2025, 10, 24, 15, 0, tzinfo=tz).timestamp()
    start, end = tour.week_bounds(now, "Europe/Moscow")
    assert datetime.fromtimestamp(start, tz) == datetime(2025, 10, 20, tzinfo=tz)
    assert datetime.fromtimestamp(end, tz) == datetime(2025, 10, 27, tzinfo=tz)


def test_tournament_wallet_is_separate(tmp_path):
    async def go():
        db, tid = await setup(tmp_path)
        bet = await db.place_bet(1, -100, 208, "suit", "♥", 300, 1.9, tournament_id=tid)
        assert (await db.get_user(1))["balance"] == 500  # обычные фишки не тронуты
        entry = await db.get_entry(tid, 1)
        assert (entry["balance"], entry["bets_count"]) == (700, 1)

        await db.settle_bet(bet, True, 570)
        assert (await db.get_entry(tid, 1))["balance"] == 1270
        assert (await db.get_user(1))["balance"] == 500

        with pytest.raises(InsufficientFunds):
            await db.place_bet(1, -100, 209, "suit", "♥", 2000, 1.9, tournament_id=tid)
        await db.close()

    run(go())


def test_join_is_once(tmp_path):
    async def go():
        db, tid = await setup(tmp_path)
        await db.place_bet(1, -100, 208, "suit", "♥", 300, 1.9, tournament_id=tid)
        entry, joined = await db.join_tournament(tid, 1, 1000)
        assert not joined and entry["balance"] == 700  # повторный вход не пополняет фишки
        await db.close()

    run(go())


def test_finish_refunds_open_bets_and_picks_eligible_winners(tmp_path):
    async def go():
        db, tid = await setup(tmp_path)
        # Руслан: 2 ставки, обе выиграли → в призах.
        for game in (208, 209):
            b = await db.place_bet(1, -100, game, "side", "P", 100, 1.95, tournament_id=tid)
            await db.settle_bet(b, True, 195)
        # Алсу: одна крупная выигрышная ставка — больше всех фишек, но мало ставок.
        b = await db.place_bet(2, -100, 208, "side", "T", 500, 8, tournament_id=tid)
        await db.settle_bet(b, True, 4000)
        # Lega: 2 ставки, одна ещё не рассчитана к концу турнира.
        b = await db.place_bet(3, -100, 208, "suit", "♠", 100, 1.9, tournament_id=tid)
        await db.settle_bet(b, False, 0)
        await db.place_bet(3, -100, 210, "suit", "♠", 200, 1.9, tournament_id=tid)

        bot = FakeBot()
        await tour.finish(CFG, db, bot, await db.get_tournament(tid))

        assert (await db.get_entry(tid, 3))["balance"] == 900  # открытая ставка вернулась
        assert await db.active_tournament() is None

        chat_msg = dict(bot.sent)[-100]
        admin_msg = dict(bot.sent)[42]
        assert "Руслан — 1190" in chat_msg and "Lega — 900" in chat_msg
        assert "Алсу" not in chat_msg  # 1 ставка из 2 нужных
        assert "@руслан" in admin_msg and "Telegram Premium" in admin_msg

        # Повторное завершение ничего не шлёт.
        bot.sent.clear()
        await tour.finish(CFG, db, bot, await db.get_tournament(tid))
        assert bot.sent == []
        await db.close()

    run(go())


def test_tick_rolls_over_to_new_week(tmp_path):
    async def go():
        db = DB(str(tmp_path / "t.sqlite3"))
        await db.open()
        bot = FakeBot()
        now = time.time()
        await tour.tick(CFG, db, bot, now)
        first = await db.active_tournament()
        assert first and first["ends_at"] > now
        assert "Турнир недели начался" in bot.sent[0][1]

        await tour.tick(CFG, db, bot, now + 60)
        assert (await db.active_tournament())["id"] == first["id"]

        await tour.tick(CFG, db, bot, first["ends_at"] + 1)
        second = await db.active_tournament()
        assert second["id"] != first["id"]
        assert second["ends_at"] == first["ends_at"] + 7 * 86400
        assert any("окончен" in text for _, text in bot.sent)
        await db.close()

    run(go())
