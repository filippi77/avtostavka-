import time
from dataclasses import replace

from suitbot import duels
from suitbot.parser import parse_game

from test_tournament import CFG, FakeBot, run_with_db

DCFG = replace(CFG, duel_games=3)


def post(number, player_cards, finished=True):
    marker = "" if finished else "⏳ "
    return parse_game(f"{marker}#N{number}. 5({player_cards}) - 3(A♣ 2♦)")


async def start_duel(db, stake=100):
    for uid, name in ((1, "Руслан"), (2, "Алсу")):
        await db.ensure_user(uid, name, 500)
    await db.mark_game_seen(207, fresh_after=0)
    duel_id = await db.create_duel(-100, 1, 2, stake, DCFG.duel_games)
    await db.set_duel_message(duel_id, 77)
    assert await db.accept_duel(duel_id, 2, 208)
    return duel_id


def test_accept_freezes_stakes_and_requires_funds(tmp_path):
    async def body(db):
        duel_id = await start_duel(db)
        assert [(await db.get_user(u))["balance"] for u in (1, 2)] == [400, 400]
        assert (await db.get_duel(duel_id))["status"] == "active"
        assert await db.user_busy_in_duel(1)

        await db.ensure_user(3, "Бедный", 20)
        other = await db.create_duel(-100, 3, None, 100, 3)
        await db.ensure_user(4, "Богатый", 1000)
        assert not await db.accept_duel(other, 4, 210)  # у вызывающего не хватает
        assert (await db.get_user(4))["balance"] == 1000  # ничего не списано

    run_with_db(tmp_path, body)


def test_full_duel_hidden_picks_and_winner(tmp_path):
    async def body(db):
        bot = FakeBot()
        duel_id = await start_duel(db)
        duel = await db.get_duel(duel_id)
        assert await duels.current_game(db, duel) == 208

        await db.set_duel_pick(duel_id, 208, 1, "♥")
        text, kb = await duels.render(DCFG, db, await db.get_duel(duel_id))
        assert "Руслан ✅ выбрал · Алсу ⏳ думает" in text and "♥" not in text  # масть скрыта
        assert kb.inline_keyboard[0][0].callback_data == f"duel:p:{duel_id}:208:♠"

        await db.set_duel_pick(duel_id, 208, 2, "♠")
        # игра 208 началась — масти раскрываются, выбор переходит на 209
        await db.mark_game_seen(208, fresh_after=0)
        await duels.on_game_started(DCFG, db, bot, 208)
        assert "игра идёт — Руслан ♥️ · Алсу ♠️" in bot.edits[-1]
        assert bot.last_markup.inline_keyboard[0][0].callback_data.endswith(":209:♠")

        await duels.on_game_result(DCFG, db, bot, post(208, "10♥ 5♦"))  # ♥ есть, ♠ нет
        assert "счёт <b>1 : 0</b>" in bot.edits[-1]
        await duels.on_game_result(DCFG, db, bot, post(208, "10♥ 5♦"))  # повтор не считается
        assert "счёт <b>1 : 0</b>" in bot.edits[-1]

        for game, cards, picks in ((209, "2♠ 3♠", {1: "♦", 2: "♠"}), (210, "4♣ 9♥", {1: "♥"})):
            for uid, suit in picks.items():
                await db.set_duel_pick(duel_id, game, uid, suit)
            await db.mark_game_seen(game, fresh_after=0)
            await duels.on_game_result(DCFG, db, bot, post(game, cards))

        duel = await db.get_duel(duel_id)
        assert duel["status"] == "finished" and duel["winner_id"] == 1  # 2 : 1
        assert [(await db.get_user(u))["balance"] for u in (1, 2)] == [600, 400]
        assert "Руслан</b> побеждает в дуэли 2 : 1 и забирает 200" in bot.sent[-1][1]
        assert "Алсу — ❌" in bot.edits[-1]  # пропущенная игра — промах
        assert await db.duel_stats(1) == (1, 0, 0) and await db.duel_stats(2) == (0, 1, 0)

    run_with_db(tmp_path, body)


def test_draw_returns_stakes(tmp_path):
    async def body(db):
        bot = FakeBot()
        duel_id = await start_duel(db)
        for game in (208, 209, 210):
            await db.mark_game_seen(game, fresh_after=0)
            await duels.on_game_result(DCFG, db, bot, post(game, "2♠ 3♠"))  # никто не выбирал
        assert (await db.get_duel(duel_id))["winner_id"] is None
        assert [(await db.get_user(u))["balance"] for u in (1, 2)] == [500, 500]
        assert "ничья" in bot.sent[-1][1]

    run_with_db(tmp_path, body)


def test_pending_duel_expires_without_charging(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 500)
        duel_id = await db.create_duel(-100, 1, None, 100, 3)
        await db.conn.execute("UPDATE duels SET created_at = created_at - 3600 WHERE id = ?", (duel_id,))
        stale = await db.stale_pending_duels(int(time.time()) - 600)
        assert [d["id"] for d in stale] == [duel_id]
        assert await db.set_duel_status(duel_id, "expired", only_from="pending")
        assert not await db.accept_duel(duel_id, 2, 210)
        assert (await db.get_user(1))["balance"] == 500

    run_with_db(tmp_path, body)


def test_spin_claim_once_a_day(tmp_path):
    async def body(db):
        await db.ensure_user(1, "Руслан", 500)
        assert await db.claim_spin(1) == 0
        assert 0 < await db.claim_spin(1) <= 86400

    run_with_db(tmp_path, body)


def test_slot_value_decoding():
    from suitbot.bot import SLOT_SYMBOLS

    def reels(value):
        return [SLOT_SYMBOLS[((value - 1) >> (2 * i)) & 3] for i in range(3)]

    assert reels(64) == ["7️⃣"] * 3
    assert reels(1) == ["BAR"] * 3
    assert reels(22) == ["🍇"] * 3
    assert reels(43) == ["🍋"] * 3


def test_migration_adds_last_spin(tmp_path):
    import asyncio
    import sqlite3

    from suitbot.db import DB

    path = tmp_path / "old.sqlite3"
    con = sqlite3.connect(path)  # база старой версии, без last_spin
    con.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT, "
                "balance INTEGER NOT NULL, last_bonus INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL DEFAULT 0, "
                "pref_stake INTEGER NOT NULL DEFAULT 50, pref_wallet TEXT NOT NULL DEFAULT 'tour')")
    con.execute("INSERT INTO users(id, name, balance) VALUES (1, 'Юрий', 785)")
    con.commit()
    con.close()

    async def go():
        db = DB(str(path))
        await db.open()
        try:
            assert (await db.get_user(1))["balance"] == 785
            assert await db.claim_spin(1) == 0
        finally:
            await db.close()

    asyncio.run(go())
