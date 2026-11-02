import asyncio
import os
import time
from dataclasses import replace

import pytest

from suitbot import admin, betting
from suitbot.db import DB

from test_tournament import CFG, FakeBot, run_with_db

RCFG = replace(CFG, reset_amount=5000)


def test_reset_balances_voids_open_things_and_backs_up(tmp_path):
    async def body(db):
        for uid, bal in ((1, 100), (2, 80_000), (3, 0)):
            await db.ensure_user(uid, f"u{uid}", bal)
        await db.mark_game_seen(207, fresh_after=0)
        await db.place_bet(1, -100, 208, "suit", "♥", 50, 1.9)
        duel = await db.create_duel(-100, 2, 3, 100, 3)
        await db.create_duel(-100, 1, None, 100, 3)  # висящий вызов
        await db.join_tournament(await db.create_tournament(int(time.time()), int(time.time()) + 3600), 2, 1000)
        await db.set_badge(2, "💎")

        users, bets, duels_n = await db.reset_balances(5000)
        assert (users, bets, duels_n) == (3, 1, 2)
        assert [(await db.get_user(u))["balance"] for u in (1, 2, 3)] == [5000, 5000, 5000]
        assert await db.open_bets_for_game(208) == []  # отменённая ставка не выплатится позже
        assert (await db.get_duel(duel))["status"] == "expired"
        assert (await db.get_user(2))["badge"] == "💎"  # магазин не трогаем
        assert (await db.get_entry(1, 2))["balance"] == 1000  # турнирные фишки тоже

    run_with_db(tmp_path, body)


def test_backup_file_is_a_readable_copy(tmp_path):
    async def go():
        db = DB(str(tmp_path / "live.sqlite3"))
        await db.open()
        await db.ensure_user(1, "Руслан", 777)
        path = await db.backup()
        await db.reset_balances(5000)
        await db.close()
        copy = DB(path)
        await copy.open()
        try:
            assert (await copy.get_user(1))["balance"] == 777  # копия сделана до сброса
        finally:
            await copy.close()
        assert os.path.exists(path)

    asyncio.run(go())


def test_do_reset_announces_with_window(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 100)
        await db.set_state("main_chat", "-100")
        await db.set_state("bet_window", "40")
        bot = FakeBot()
        note = await admin.do_reset(RCFG, db, bot, announce=True)
        assert note.startswith("Готово: 1 игрокам выдано по 5000")
        assert "5000 фишек" in bot.sent[-1][1] and "через 40 с" in bot.sent[-1][1]

        bot.sent.clear()
        await db.set_state("bet_window", "0")
        await admin.do_reset(RCFG, db, bot, announce=True)
        assert "через" not in bot.sent[-1][1]
        bot.sent.clear()
        await admin.do_reset(RCFG, db, bot, announce=False)
        assert bot.sent == []

    run_with_db(tmp_path, body)


def test_confirm_screen_warns_about_purchased_chips(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 100)
        await db.record_payment("c1", 1, 5, 500)
        text, kb = await admin.reset_confirm(RCFG, db)
        assert "5000" in text and "купленные за звёзды" in text and "покупателей: 1" in text
        assert [b.callback_data for row in kb.inline_keyboard for b in row] == ["adm:rd:1", "adm:rd:0", "adm:refresh"]

    run_with_db(tmp_path, body)


def test_bet_cutoff_window_is_adjustable(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 5000)
        await db.mark_game_seen(207, fresh_after=0)
        await db.conn.execute("UPDATE games SET seen_at = seen_at - 35 WHERE number = 207")

        await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)  # окна ещё нет
        await db.set_state("bet_window", "30")
        with pytest.raises(betting.BetError, match="закрыт"):
            await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        await db.set_state("bet_window", "45")  # окно шире, чем прошло с поста
        await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        assert await betting.bet_window(RCFG, db) == 45

    run_with_db(tmp_path, body)
