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
    id = 1

    def __init__(self):
        self.sent: list[tuple[int, str]] = []
        self.edits: list[str] = []

    async def __call__(self, method, request_timeout=None):
        # message.reply(...) и т.п. вызывают бота напрямую с объектом метода
        self.sent.append((getattr(method, "chat_id", None), getattr(method, "text", "")))
        return SimpleNamespace(message_id=len(self.sent))

    async def me(self):
        return SimpleNamespace(username="suit_bot")

    async def send_message(self, chat_id, text, reply_markup=None, **kwargs):
        self.sent.append((chat_id, text))
        return SimpleNamespace(message_id=len(self.sent))

    async def edit_message_text(self, text, chat_id, message_id, reply_markup=None):
        self.edits.append(text)
        self.last_markup = reply_markup


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
        await cards.maybe_post(CFG, db, bot, 208, -100)  # карточка на 209 — не кратно 5
        assert bot.sent == []
        await cards.maybe_post(CFG, db, bot, 209, -100)  # на 210 — кратно 5
        await cards.maybe_post(CFG, db, bot, 209, -100)  # повтор не дублирует
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


def test_bet_window_closes_next_game(tmp_path):
    async def body(db):
        cfg = replace(CFG, bet_window_seconds=30)
        await db.ensure_user(1, "Руслан", 500)
        await db.mark_game_seen(207, fresh_after=0)
        await betting.place(cfg, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        await db.conn.execute("UPDATE games SET seen_at = seen_at - 31 WHERE number = 207")
        with pytest.raises(betting.BetError, match="закрыт"):
            await betting.place(cfg, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        # на игры дальше окно не влияет
        await betting.place(cfg, db, 1, -100, 209, "suit", "♥", 50, tournament_bet=False)

    run_with_db(tmp_path, body)


def test_rating_popup_fits_and_shows_own_place(tmp_path):
    from suitbot import rating

    async def body(db):
        for uid in range(1, 16):
            await db.ensure_user(uid, f"Игрок с длинным именем {uid}", 100 * uid)
        text = await rating.popup_text(CFG, db, 3)
        assert len(text) <= rating.POPUP_LIMIT
        assert text.startswith("📊 Рейтинг") and "1. Игрок с дли… 1500" in text
        assert text.endswith("Вы: 13 место · 300")

        tid = await db.create_tournament(int(time.time()), int(time.time()) + 3600)
        await db.join_tournament(tid, 5, 1000)
        assert "Вы не в турнире" in await rating.popup_text(CFG, db, 3)
        assert "Вы: 1 место · 1000" in await rating.popup_text(CFG, db, 5)

    run_with_db(tmp_path, body)


def test_subscription_checker():
    from suitbot.access import SubscriptionChecker

    class Bot:
        def __init__(self, status):
            self.status, self.calls = status, 0

        async def get_chat_member(self, chat_id, user_id):
            self.calls += 1
            if self.status == "error":
                raise RuntimeError("bot is not admin")
            return SimpleNamespace(status=self.status)

    async def go():
        assert await SubscriptionChecker(CFG).is_subscribed(Bot("left"), 1)  # проверка выключена
        subs = SubscriptionChecker(replace(CFG, required_channel="@stat_bakkara"))
        assert not await subs.is_subscribed(Bot("left"), 1)
        bot = Bot("member")
        assert await subs.is_subscribed(bot, 1) and await subs.is_subscribed(bot, 1)
        assert bot.calls == 1  # подписка закеширована
        assert await subs.is_subscribed(Bot("error"), 2)  # бот не админ канала — не блокируем
        assert subs.channel_url == "https://t.me/stat_bakkara"

    asyncio.run(go())


def test_group_with_channel_posts_becomes_main_chat(tmp_path):
    import datetime

    from aiogram import Dispatcher
    from aiogram.types import Update

    from suitbot.access import SubscriptionChecker
    from suitbot.bot import build_router

    async def body(db):
        bot = FakeBot()
        dp = Dispatcher()
        dp.include_router(build_router(CFG, db, SubscriptionChecker(CFG)))
        update = Update.model_validate({"update_id": 1, "message": {
            "message_id": 1, "date": datetime.datetime.now(), "text": "⏳ #N272. ▶️ 2(7♣️ 5♥️) - 2(6♠️ 6♦️)",
            "chat": {"id": -100777, "type": "supergroup", "title": "Baccara Chat"},
            "sender_chat": {"id": -200, "type": "channel", "title": "Statistika"}, "is_automatic_forward": True,
        }})
        await dp.feed_update(bot, update)
        assert await db.get_state("main_chat") == "-100777"
        assert bot.sent[0][0] == -100777 and "Игра #N273" in bot.sent[0][1]

    run_with_db(tmp_path, body)


def test_format_ends_without_tz_database(monkeypatch):
    def missing(name):
        raise KeyError(name)  # как ZoneInfoNotFoundError на сервере без tzdata

    monkeypatch.setattr(tour, "ZoneInfo", missing)
    tz = ZoneInfo("Europe/Moscow")
    ts = int(datetime(2025, 10, 25, 18, 30, tzinfo=tz).timestamp())
    assert tour.format_ends(CFG, ts) == "25.10 18:30"


def test_give_all(tmp_path):
    from suitbot import admin

    async def body(db):
        tid = await with_players(db)
        await db.set_state("main_chat", "-555")
        bot = FakeBot()
        note = await admin.give_all(CFG, db, bot, "main", 1000, announce=True)
        assert note == "Выдано +1000 обычных фишек: 3 игрокам."
        assert [(await db.get_user(u))["balance"] for u in (1, 2, 3)] == [1500] * 3
        assert bot.sent[-1][0] == -555 and "+1000" in bot.sent[-1][1]

        bot.sent.clear()
        await admin.give_all(CFG, db, bot, "tour", 200, announce=False)
        assert (await db.get_entry(tid, 2))["balance"] == 1200
        assert bot.sent == []

        await tour.finish(CFG, db, bot, await db.get_tournament(tid))
        assert "некому" in await admin.give_all(CFG, db, bot, "tour", 200, announce=False)

    run_with_db(tmp_path, body)


def test_setchat_from_anonymous_group_admin(tmp_path):
    import datetime

    from aiogram import Dispatcher
    from aiogram.types import Update

    from suitbot import admin

    def setchat(sender_chat_id, user_id):
        return Update.model_validate({"update_id": 1, "message": {
            "message_id": 1, "date": datetime.datetime.now(), "text": "/setchat",
            "entities": [{"type": "bot_command", "offset": 0, "length": 8}],
            "chat": {"id": -100555, "type": "supergroup", "title": "Penalty"},
            "from": {"id": user_id, "is_bot": True, "first_name": "Group"},
            "sender_chat": {"id": sender_chat_id, "type": "supergroup" if sender_chat_id == -100555 else "channel",
                            "title": "x"},
        }})

    async def body(db):
        bot = FakeBot()
        dp = Dispatcher()
        dp.include_router(admin.build_router(CFG, db))
        await dp.feed_update(bot, setchat(-200, 136817688))  # от имени чужого канала — не админ
        assert await db.get_state("main_chat") is None
        await dp.feed_update(bot, setchat(-100555, 1087968824))  # анонимный админ группы
        assert await db.get_state("main_chat") == "-100555"

    run_with_db(tmp_path, body)
