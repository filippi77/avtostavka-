import asyncio
import time
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from suitbot import betting, cards
from suitbot import tournament as tour
from suitbot.config import Config
from suitbot.db import DB, InsufficientFunds

CFG = replace(Config(token="x"), admins={42}, tournament_chats={-100}, tournament_min_bets=2,
              tournament_min_days_in_bot=0)


class FakeBot:
    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.edits: list[str] = []

    async def me(self):
        return SimpleNamespace(username="suit_bot")

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edits.append(text)


def run_with_db(tmp_path, body):
    """Запускает body(db) и всегда закрывает базу, чтобы упавший тест не вешал процесс."""
    async def go():
        db = DB(str(tmp_path / "t.sqlite3"))
        await db.open()
        try:
            await body(db)
        finally:
            await db.close()

    asyncio.run(go())


async def with_players(db) -> int:
    for uid, name in ((1, "Руслан"), (2, "Алсу"), (3, "Lega")):
        await db.ensure_user(uid, name, 500, username=name.lower())
    tid = await db.create_tournament(int(time.time()), int(time.time()) + 3600)
    for uid in (1, 2, 3):
        await db.join_tournament(tid, uid, 1000)
    return tid


def test_week_bounds_monday_midnight():
    tz = ZoneInfo("Europe/Moscow")
    now = datetime(2025, 10, 24, 15, 0, tzinfo=tz).timestamp()
    start, end = tour.week_bounds(now, "Europe/Moscow")
    assert datetime.fromtimestamp(start, tz) == datetime(2025, 10, 20, tzinfo=tz)
    assert datetime.fromtimestamp(end, tz) == datetime(2025, 10, 27, tzinfo=tz)


def test_format_ends():
    tz = ZoneInfo("Europe/Moscow")
    assert tour.format_ends(CFG, int(datetime(2025, 10, 27, tzinfo=tz).timestamp())) == "26.10 23:59"
    assert tour.format_ends(CFG, int(datetime(2025, 10, 25, 18, 30, tzinfo=tz).timestamp())) == "25.10 18:30"


def test_tournament_wallet_is_separate(tmp_path):
    async def body(db):
        tid = await with_players(db)
        bet = await db.place_bet(1, -100, 208, "suit", "♥", 300, 1.9, tournament_id=tid)
        assert (await db.get_user(1))["balance"] == 500
        entry = await db.get_entry(tid, 1)
        assert (entry["balance"], entry["bets_count"]) == (700, 1)

        await db.settle_bet(bet, True, 570)
        assert (await db.get_entry(tid, 1))["balance"] == 1270
        assert (await db.get_user(1))["balance"] == 500

        with pytest.raises(InsufficientFunds):
            await db.place_bet(1, -100, 209, "suit", "♥", 2000, 1.9, tournament_id=tid)

        entry, joined = await db.join_tournament(tid, 1, 1000)
        assert not joined and entry["balance"] == 1270  # повторный вход не пополняет фишки

    run_with_db(tmp_path, body)


def test_finish_refunds_open_bets_and_picks_eligible_winners(tmp_path):
    async def body(db):
        tid = await with_players(db)
        for game in (208, 209):
            b = await db.place_bet(1, -100, game, "side", "P", 100, 1.95, tournament_id=tid)
            await db.settle_bet(b, True, 195)
        # Алсу: больше всех фишек, но всего одна ставка из двух нужных.
        b = await db.place_bet(2, -100, 208, "side", "T", 500, 8, tournament_id=tid)
        await db.settle_bet(b, True, 4000)
        b = await db.place_bet(3, -100, 208, "suit", "♠", 100, 1.9, tournament_id=tid)
        await db.settle_bet(b, False, 0)
        await db.place_bet(3, -100, 210, "suit", "♠", 200, 1.9, tournament_id=tid)

        bot = FakeBot()
        await tour.finish(CFG, db, bot, await db.get_tournament(tid))

        assert (await db.get_entry(tid, 3))["balance"] == 900  # открытая ставка вернулась
        assert await db.active_tournament() is None
        chat_msg, admin_msg = dict(bot.sent)[-100], dict(bot.sent)[42]
        assert "Руслан — 1190 · 200 ⭐" in chat_msg and "Lega — 900 · 100 ⭐" in chat_msg
        assert "Алсу" not in chat_msg
        assert "@руслан" in admin_msg and "200 ⭐" in admin_msg

        bot.sent.clear()
        await tour.finish(CFG, db, bot, await db.get_tournament(tid))
        assert bot.sent == []

    run_with_db(tmp_path, body)


def test_manual_start_and_auto_finish(tmp_path):
    async def body(db):
        bot = FakeBot()
        await db.set_state("main_chat", "-555")
        now = time.time()
        await tour.tick(CFG, db, bot, now)
        assert await db.active_tournament() is None  # без TOURNAMENT_AUTO сам не стартует

        started = await tour.start(CFG, db, bot, int(now) + 86400)
        assert started and {c for c, _ in bot.sent} == {-100, -555}
        assert "Турнир начался" in bot.sent[0][1]
        assert await tour.start(CFG, db, bot, int(now) + 86400) is None  # второй не запустить

        await tour.tick(CFG, db, bot, now + 60)
        assert (await db.active_tournament())["id"] == started["id"]
        await tour.tick(CFG, db, bot, started["ends_at"] + 1)
        assert await db.active_tournament() is None
        assert any("окончен" in text for _, text in bot.sent)

    run_with_db(tmp_path, body)


def test_auto_mode_rolls_over_weekly(tmp_path):
    async def body(db):
        cfg = replace(CFG, tournament_auto=True)
        bot = FakeBot()
        now = time.time()
        await tour.tick(cfg, db, bot, now)
        first = await db.active_tournament()
        await tour.tick(cfg, db, bot, first["ends_at"] + 1)
        second = await db.active_tournament()
        assert second["id"] != first["id"]
        assert second["ends_at"] == first["ends_at"] + 7 * 86400

    run_with_db(tmp_path, body)


def test_card_frequency_and_closing(tmp_path):
    async def body(db):
        bot = FakeBot()
        await db.set_state("card_every", "5")
        await cards.maybe_post(CFG, db, bot, 207, -100)  # 207+2=209 — не кратно 5
        assert bot.sent == []
        await cards.maybe_post(CFG, db, bot, 208, -100)  # 210 — кратно 5
        await cards.maybe_post(CFG, db, bot, 208, -100)  # повтор не дублирует
        assert len(bot.sent) == 1 and "Игра #N210" in bot.sent[0][1]

        await db.set_state("card_every", "0")
        await cards.maybe_post(CFG, db, bot, 213, -100)
        assert len(bot.sent) == 1

        await cards.close_for_game(CFG, db, bot, 210)
        assert "ставки закрыты" in bot.edits[-1]
        assert await db.open_cards_for_game(210, 0) == []

    run_with_db(tmp_path, body)


def test_betting_place_validation(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 500)
        await db.mark_game_seen(207, fresh_after=0)
        with pytest.raises(betting.BetError, match="турнира нет"):
            await betting.place(CFG, db, 1, -100, 209, "suit", "♥", 50, tournament_bet=True)
        with pytest.raises(betting.BetError, match="Последняя игра"):
            await betting.place(CFG, db, 1, -100, 300, "suit", "♥", 50, tournament_bet=False)

        text = await betting.place(CFG, db, 1, -100, 209, "suit", "♥", 50, tournament_bet=False)
        assert "Осталось 450 фишек" in text

        tid = await db.create_tournament(int(time.time()), int(time.time()) + 3600)
        text = await betting.place(CFG, db, 1, -100, 209, "side", "P", 100, tournament_bet=True)
        assert "Турнирная" in text and "Осталось 900 турнирных фишек" in text
        assert (await db.get_entry(tid, 1))["bets_count"] == 1
        with pytest.raises(betting.BetError, match="до 500"):
            await betting.place(CFG, db, 1, -100, 209, "side", "P", 600, tournament_bet=True)

    run_with_db(tmp_path, body)
