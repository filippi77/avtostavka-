from suitbot.penalty import bet_wins, parse_pick, parse_post

UPCOMING = "⏳ #N44 #t_05_35\nМанчестер Сити (0:0) Ювентус\nП1 1.92 | П2 1.89\nТБ 4.5 1.66 | ТМ 4.5 2.09"
LIVE = "⏳ #N42 #t_05_25\nЛиверпуль (1:0) Реал\nП1 2.25 | П2 1.57"
FINISHED_AWAY = "🏁 #N41 #t_05_20\nАрсенал (0:2) Ливерпуль ✅\nП1 1.73 | П2 1.99\nТБ 4.5 1.41 | ТМ 4.5 2.61"
FINISHED_HOME = "🏁 #N40 #t_05_15\n✅ Ливерпуль (4:3) Арсенал\nП1 1.89 | П2 1.91\nТБ 4.5 1.79 | ТМ 4.5 2.02"


def test_upcoming_post():
    p = parse_post(UPCOMING)
    assert (p.number, p.home, p.away, p.score) == (44, "Манчестер Сити", "Ювентус", (0, 0))
    assert p.odds == {"1": 1.92, "2": 1.89, "O": 1.66, "U": 2.09} and p.line == 4.5
    assert not p.started and not p.finished


def test_live_post_without_total():
    p = parse_post(LIVE)
    assert p.started and not p.finished
    assert p.line is None and p.odds == {"1": 2.25, "2": 1.57}


def test_finished_posts_and_settlement():
    away = parse_post(FINISHED_AWAY)
    assert away.finished and away.winner == "2" and away.total == 2
    assert bet_wins("win", "2", away) and not bet_wins("win", "1", away)
    assert bet_wins("total", "U4.5", away) and not bet_wins("total", "O4.5", away)

    home = parse_post(FINISHED_HOME)
    assert (home.home, home.away, home.winner, home.total) == ("Ливерпуль", "Арсенал", "1", 7)
    assert bet_wins("total", "O4.5", home)


def test_parse_pick():
    assert parse_pick("П1") == ("win", "1")
    assert parse_pick("p2") == ("win", "2")
    assert parse_pick("ТБ") == ("total", "O")
    assert parse_pick("тм") == ("total", "U")
    assert parse_pick("♥") is None
    assert parse_post("Ставлю на П1") is None


def test_timer_closes_next_series(tmp_path):
    import asyncio
    import time
    from dataclasses import replace

    from suitbot import bot as botmod
    from suitbot.config import Config
    from test_tournament import FakeBot, run_with_db

    cfg = replace(Config(token="x"), game="penalty", game_number_wrap=288)

    async def body(db):
        bot = FakeBot()
        await db.save_penalty_game(43, "Арсенал", "Бавария", {"1": 1.97, "2": 1.83}, None)
        await db.set_state("pen_close", f"43:{int(time.time()) + 60}")

        async def one_tick(*_):
            raise asyncio.CancelledError

        real_sleep = botmod.asyncio.sleep
        botmod.asyncio.sleep = one_tick
        try:
            for _ in range(2):
                try:
                    await botmod.penalty_close_loop(cfg, db, bot)
                except asyncio.CancelledError:
                    pass
                if _ == 0:
                    assert not await db.game_seen_since(43, 0)  # время ещё не вышло
                    await db.set_state("pen_close", f"43:{int(time.time()) - 1}")
        finally:
            botmod.asyncio.sleep = real_sleep
        assert await db.game_seen_since(43, 0)
        assert await db.get_state("pen_close") == ""

    run_with_db(tmp_path, body)
