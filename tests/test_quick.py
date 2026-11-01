import asyncio
import datetime
import re
import time
from dataclasses import replace

from aiogram import Bot, Dispatcher
from aiogram.client.session.base import BaseSession
from aiogram.types import Chat, Message, Update, User

from suitbot import i18n, quick
from suitbot.access import SubscriptionChecker

from test_tournament import CFG, run_with_db


class Session(BaseSession):
    """Подставной Telegram: записывает вызовы; личка может быть закрыта."""

    def __init__(self, dm_open=True):
        super().__init__()
        self.calls, self.dm_open = [], dm_open

    async def make_request(self, bot, method, timeout=None):
        name = type(method).__name__
        if name == "GetMe":
            return User(id=1, is_bot=True, first_name="b", username="b")
        if name == "SendMessage" and method.chat_id > 0 and not self.dm_open:
            raise RuntimeError("bot can't initiate conversation")
        self.calls.append((name, getattr(method, "chat_id", None), getattr(method, "text", None)))
        if name in ("DeleteMessage", "SetMyCommands", "EditMessageText"):
            return True
        return Message(message_id=99, date=datetime.datetime.now(), chat=Chat(id=method.chat_id, type="group"), text="x")

    async def stream_content(self, *a, **k):
        yield b""

    async def close(self):
        pass


def command(text):
    return Update.model_validate({"update_id": 1, "message": {
        "message_id": 5, "date": datetime.datetime.now(), "text": text,
        "entities": [{"type": "bot_command", "offset": 0, "length": len(text)}],
        "chat": {"id": -100, "type": "supergroup", "title": "Chat"},
        "from": {"id": 7, "is_bot": False, "first_name": "Руслан"},
    }})


async def feed(cfg, db, session, text):
    bot = Bot("1:a", session=session)
    dp = Dispatcher()
    dp.include_router(quick.build_router(cfg, db, lambda u: db.ensure_user(u.id, u.first_name, 500),
                                         SubscriptionChecker(cfg)))
    await dp.feed_update(bot, command(text))
    await asyncio.sleep(0)


def test_quick_bet_deletes_command_and_answers_in_dm(tmp_path):
    async def body(db):
        await db.mark_game_seen(207, fresh_after=0)
        session = Session()
        await feed(CFG, db, session, "/hearts@b")
        assert ("DeleteMessage", -100, None) in session.calls
        dm = [c for c in session.calls if c[0] == "SendMessage"]
        assert dm == [("SendMessage", 7, dm[0][2])] and "#N208" in dm[0][2] and "♥" in dm[0][2]
        assert (await db.get_user(7))["balance"] == 450  # ставка 50 по умолчанию

    run_with_db(tmp_path, body)


def test_quick_bet_without_dm_replies_in_chat(tmp_path):
    async def body(db):
        session = Session(dm_open=False)
        await feed(CFG, db, session, "/player")  # игр ещё не было — ставка не пройдёт
        replies = [c for c in session.calls if c[0] == "SendMessage"]
        assert replies[0][1] == -100 and replies[0][2].startswith("Руслан: ")

    run_with_db(tmp_path, body)


def test_quick_bet_penalty(tmp_path):
    async def body(db):
        cfg = replace(CFG, game="penalty", game_number_wrap=288)
        i18n.set_game("penalty")
        try:
            await db.set_state("last_game", "42")
            await db.save_penalty_game(43, "Арсенал", "Бавария", {"1": 1.97, "2": 1.83, "O": 1.8, "U": 2.0}, 4.5)
            session = Session()
            await feed(cfg, db, session, "/over")
            dm = [c[2] for c in session.calls if c[0] == "SendMessage"][0]
            assert "#N43" in dm and "ТБ 4.5" in dm
        finally:
            i18n.set_game("baccarat")

    run_with_db(tmp_path, body)


def test_command_menus_are_valid():
    async def go():
        for game in ("baccarat", "penalty"):
            for lang in ("ru", "uz"):
                i18n.set_lang(lang)
                session = Session()
                await quick.set_commands(replace(CFG, game=game), Bot("1:a", session=session))
                assert [c[0] for c in session.calls] == ["SetMyCommands", "SetMyCommands"]
        i18n.set_lang("ru")
        for game in ("baccarat", "penalty"):
            for name in list(quick.quick_bets(replace(CFG, game=game))) + ["duel", "top", "start", "help"]:
                assert re.fullmatch(r"[a-z0-9_]{1,32}", name)
                for text in i18n.TEXTS[f"cmd_{name}"]:
                    assert 1 <= len(text) <= 256

    asyncio.run(go())
