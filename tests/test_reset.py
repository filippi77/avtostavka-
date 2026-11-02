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

        reset, kept, bets, duels_n = await db.reset_balances(5000)
        assert (reset, kept, bets, duels_n) == (3, 0, 1, 2)
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
        assert note.startswith("Готово: 1 игрокам выдано по 5000, у 0 покупателей баланс сохранён")
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
        assert "станет <b>5000</b> фишек у 0" in text and "(1, всего 5 ⭐)" in text and "остаются" in text
        assert [b.callback_data for row in kb.inline_keyboard for b in row] == ["adm:rd:1", "adm:rd:0", "adm:refresh"]

    run_with_db(tmp_path, body)


def test_bet_cutoff_window_is_adjustable(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 5000)
        await db.mark_game_seen(207, fresh_after=0)
        await db.conn.execute("UPDATE games SET seen_at = seen_at - 35 WHERE number = 207")

        await db.set_state("bet_window", "0")  # таймер выключен — закрытие только по посту игры
        await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        await db.set_state("bet_window", "30")
        with pytest.raises(betting.BetError, match="закрыт"):
            await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        await db.set_state("bet_window", "45")  # окно шире, чем прошло с поста
        await betting.place(RCFG, db, 1, -100, 208, "suit", "♥", 50, tournament_bet=False)
        assert await betting.bet_window(RCFG, db) == 45

    run_with_db(tmp_path, body)


def test_buyers_keep_their_balance_and_get_frozen_chips_back(tmp_path):
    async def body(db):
        for uid, bal in ((1, 12_000), (2, 300), (3, 900), (4, 800)):
            await db.ensure_user(uid, f"u{uid}", bal)
        await db.record_payment("c1", 1, 5, 500)  # игроки 1 и 3 покупали фишки за звёзды
        await db.record_payment("c2", 3, 1, 100)
        await db.mark_game_seen(207, fresh_after=0)
        await db.place_bet(1, -100, 208, "suit", "♥", 500, 1.9)  # покупатель: 12 000 → 11 500
        await db.place_bet(2, -100, 208, "suit", "♥", 100, 1.9)  # не покупал: 300 → 200
        duel = await db.create_duel(-100, 3, 4, 100, 3)
        assert await db.accept_duel(duel, 4, 208)  # у 3: 900 → 800, у 4: 800 → 700
        tid = await db.create_tournament(int(time.time()), int(time.time()) + 3600)
        await db.join_tournament(tid, 4, 1000)
        await db.place_bet(4, -100, 208, "side", "P", 200, 1.95, tournament_id=tid)  # турнирная ставка

        reset, kept, bets, duels_n = await db.reset_balances(5000)
        assert (reset, kept, bets, duels_n) == (2, 2, 2, 1)
        balances = [(await db.get_user(u))["balance"] for u in (1, 2, 3, 4)]
        # Покупка добавила фишки: у 1-го было 12 500, у 3-го 1 000. Они сохранили баланс и получили
        # обратно замороженное на ставке и в дуэли; остальным — 5000.
        assert balances == [12_500, 5000, 1000, 5000]
        open_left = await db.open_bets_for_game(208)
        assert [(b["user_id"], b["wallet"]) for b in open_left] == [(4, "tour")]  # турнирная ставка не тронута
        assert (await db.get_entry(tid, 4))["balance"] == 800

    run_with_db(tmp_path, body)


async def _games_every(db, seconds, count=8, last=300):
    """Игры #N293…#N300 с постами раз в `seconds` секунд; последняя — только что."""
    now = int(time.time())
    for i in range(count):
        n = last - count + 1 + i
        await db.mark_game_seen(n, fresh_after=0)
        await db.conn.execute("UPDATE games SET seen_at = ? WHERE number = ?", (now - (count - 1 - i) * seconds, n))
    await db.conn.commit()


def test_auto_window_follows_real_game_interval(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 5000)
        await db.set_state("last_game", "300")
        assert await betting.bet_window(RCFG, db) == 30  # данных мало — безопасное значение
        await _games_every(db, 60)
        assert await db.game_interval(1440) == 60
        assert await betting.bet_window(RCFG, db) == 40  # 60 с между играми − запас 20 с

        await db.conn.execute("UPDATE games SET seen_at = seen_at - 35 WHERE number = 300")  # пост 300 был 35 с назад
        await betting.place(RCFG, db, 1, -100, 301, "suit", "♥", 50, tournament_bet=False)  # ещё можно
        await db.conn.execute("UPDATE games SET seen_at = seen_at - 10 WHERE number = 300")  # уже 45 с
        with pytest.raises(betting.BetError, match="закрыт"):
            await betting.place(RCFG, db, 1, -100, 301, "suit", "♥", 50, tournament_bet=False)

        await db.set_state("bet_reserve", "30")  # запас побольше — закрываем ещё раньше
        assert await betting.bet_window(RCFG, db) == 30
        await _games_every(db, 90)
        assert await betting.bet_window(RCFG, db) == 60  # интервал вырос — окно подстроилось

    run_with_db(tmp_path, body)


def test_interval_ignores_gaps_and_other_modes(tmp_path):
    async def body(db):
        await _games_every(db, 60)
        await db.conn.execute("UPDATE games SET seen_at = seen_at - 3600 WHERE number <= 295")  # остановка бота
        assert await db.game_interval(1440) == 60  # длинный пропуск не портит оценку
        await db.set_state("bet_window", "45")
        assert await betting.bet_window(RCFG, db) == 45
        await db.set_state("bet_window", "0")
        assert await betting.bet_window(RCFG, db) == 0
        assert await betting.bet_window(replace(RCFG, game="penalty"), db) == 0  # у пенальти свой механизм

    run_with_db(tmp_path, body)
