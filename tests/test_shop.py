import time
from dataclasses import replace
from types import SimpleNamespace

import pytest

from suitbot import betting, shop
from suitbot.db import DB

from test_tournament import CFG, FakeBot, run_with_db


class ChatBot(FakeBot):
    """Подставной бот с методами для админских прав в чате."""

    def __init__(self, status="member", fail=False):
        super().__init__()
        self.status, self.fail, self.calls = status, fail, []
        self.title = None

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.status, custom_title=self.title)

    async def promote_chat_member(self, chat_id, user_id, **rights):
        if self.fail:
            raise RuntimeError("not enough rights")
        self.calls.append(("promote", rights))
        self.status = "administrator" if any(rights.values()) else "member"

    async def set_chat_administrator_custom_title(self, chat_id, user_id, title):
        self.calls.append(("title", title))
        self.title = title


async def player(db: DB, balance=100_000):
    await db.ensure_user(1, "Руслан", balance, username="ruslan")
    return await db.get_user(1)


def test_spend_and_badge_in_names(tmp_path):
    async def body(db):
        await player(db, 15_000)
        assert await db.spend(1, 10_000, "badge:0")
        assert not await db.spend(1, 10_000, "badge:1")  # осталось 5000
        await db.set_badge(1, "💎")
        assert (await db.top())[0]["name"] == "💎 Руслан"
        await db.mark_game_seen(207, fresh_after=0)
        await db.place_bet(1, -100, 208, "suit", "♥", 100, 1.9)
        assert (await db.open_bets_for_game(208))[0]["name"] == "💎 Руслан"
        assert await db.shop_sales() == (1, 10_000)

    run_with_db(tmp_path, body)


def test_vip_raises_bet_limit(tmp_path):
    async def body(db):
        await player(db)
        await db.mark_game_seen(207, fresh_after=0)
        with pytest.raises(betting.BetError, match="VIP"):
            await betting.place(CFG, db, 1, -100, 208, "suit", "♥", 25_000, tournament_bet=False)
        until = await db.extend_vip(1, 7 * 86400)
        assert until > time.time() + 6 * 86400
        await betting.place(CFG, db, 1, -100, 208, "suit", "♥", 25_000, tournament_bet=False)
        assert await db.extend_vip(1, 7 * 86400) == until + 7 * 86400  # продление от текущего конца

    run_with_db(tmp_path, body)


def test_extra_spin(tmp_path):
    async def body(db):
        await player(db)
        assert await db.claim_spin(1) == 0
        assert await db.claim_spin(1) > 0
        await db.add_extra_spin(1)
        assert await db.claim_spin(1) == 0  # купленная попытка
        assert await db.claim_spin(1) > 0

    run_with_db(tmp_path, body)


def test_title_purchase_flow(tmp_path):
    async def body(db):
        await db.set_state("main_chat", "-100")
        user = await player(db)
        bot = ChatBot()
        assert await shop.give_title(CFG, db, bot, user, "Хайроллер") is None
        assert ("title", "Хайроллер") in bot.calls and bot.calls[0] == ("promote", {"can_invite_users": True})
        row = await db.get_title(-100, 1)
        assert row["title"] == "Хайроллер" and row["until"] > time.time() + 6 * 86400
        assert "Руслан — «Хайроллер»" in bot.sent[-1][1]

        # продление и смена своего звания — без повторного назначения админом
        bot.calls.clear()
        assert await shop.give_title(CFG, db, bot, user, "Снайпер") is None
        assert bot.calls == [("title", "Снайпер")]
        assert (await db.get_title(-100, 1))["until"] > row["until"]

        # срок вышел — бот снимает только своё звание
        await db.conn.execute("UPDATE titles SET until = 0")

        async def one_tick(*_):
            raise SystemExit

        real = shop.asyncio.sleep
        shop.asyncio.sleep = one_tick
        try:
            with pytest.raises(SystemExit):
                await shop.loop(CFG, db, bot)
        finally:
            shop.asyncio.sleep = real
        assert bot.status == "member" and await db.get_title(-100, 1) is None

    run_with_db(tmp_path, body)


def test_title_refused_for_admins_and_errors(tmp_path):
    async def body(db):
        user = await player(db)
        assert "Чат ещё не настроен" in await shop.give_title(CFG, db, ChatBot(), user, "Х")
        await db.set_state("main_chat", "-100")
        assert "уже администратор" in await shop.give_title(CFG, db, ChatBot("administrator"), user, "Х")
        assert "вступите в чат" in await shop.give_title(CFG, db, ChatBot("left"), user, "Х")
        assert "нет права" in await shop.give_title(CFG, db, ChatBot(fail=True), user, "Х")
        assert await db.get_title(-100, 1) is None

    run_with_db(tmp_path, body)


def test_valid_title():
    assert shop.valid_title("Король масти")
    assert shop.valid_title("Mast qiroli")
    assert not shop.valid_title("👑 Король")  # эмодзи Telegram не пропустит
    assert not shop.valid_title("Очень длинное звание тут")
    assert not shop.valid_title("@admin")
    assert not shop.valid_title("")
    from suitbot import i18n
    try:
        for lang in ("ru", "uz"):
            for game in ("baccarat", "penalty"):
                i18n.set_lang(lang)
                i18n.set_game(game)
                for title in shop.ready_titles():
                    assert shop.valid_title(title), (lang, game, title)
    finally:
        i18n.set_lang("ru")
        i18n.set_game("baccarat")


def test_suit_labels_have_russian_names():
    from suitbot import i18n
    try:
        i18n.set_lang("ru")
        assert i18n.suit_label("♠") == "♠️ Пики"
        assert i18n.suit_label("♥") == "♥️ Черви"
        i18n.set_lang("uz")
        assert i18n.suit_label("♣").endswith("Chillak")
    finally:
        i18n.set_lang("ru")
