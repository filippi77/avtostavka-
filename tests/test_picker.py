import asyncio
import datetime
import time

from aiogram import Dispatcher
from aiogram.types import Update

from suitbot import cards
from suitbot.access import SubscriptionChecker
from suitbot.bot import build_router, display_name
from suitbot.cards import card_keyboard

from test_tournament import CFG, FakeBot, run_with_db


def test_group_card_has_bet_buttons(tmp_path):
    kb = card_keyboard(208, False, "suit_bot")
    data = [b.callback_data for row in kb.inline_keyboard for b in row if b.callback_data]
    assert "b:208:suit:♥" in data and "st:100" in data and "st:5000" in data


def test_private_pick_records_bet_in_main_chat(tmp_path):
    async def body(db):
        await db.set_state("main_chat", "-100")
        await db.set_state("last_game", "207")
        await db.ensure_user(7, "Руслан", 500)
        bot = FakeBot()
        dp = Dispatcher()
        subs = SubscriptionChecker(CFG)
        dp.include_router(cards.build_router(CFG, db, lambda u: db.ensure_user(u.id, u.first_name, 500), subs))
        dp.include_router(build_router(CFG, db, subs))

        def start(args):
            return Update.model_validate({"update_id": 1, "message": {
                "message_id": 1, "date": datetime.datetime.now(), "text": f"/start {args}",
                "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
                "chat": {"id": 7, "type": "private"}, "from": {"id": 7, "is_bot": False, "first_name": "Руслан"}}})

        def press(data):
            return Update.model_validate({"update_id": 2, "callback_query": {
                "id": "9", "chat_instance": "x", "data": data,
                "from": {"id": 7, "is_bot": False, "first_name": "Руслан"},
                "message": {"message_id": 3, "date": datetime.datetime.now(),
                            "chat": {"id": 7, "type": "private"}, "text": "x"}}})

        await dp.feed_update(bot, start("g208"))
        sent = bot.sent[-1]
        assert sent[0] == 7 and "Ставка на #N208" in sent[1]  # личка, не группа

        await dp.feed_update(bot, press("b:208:suit:♥"))
        bets = await db.open_bets_for_game(208)
        assert len(bets) == 1 and bets[0]["chat_id"] == -100  # ставка записана на карточку основного чата
        assert (await db.get_user(7))["balance"] == 450

    run_with_db(tmp_path, body)
