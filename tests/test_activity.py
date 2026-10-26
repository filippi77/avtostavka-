import datetime
import time
from dataclasses import replace

from aiogram import Dispatcher
from aiogram.types import Update

from suitbot import activity
from suitbot.access import SubscriptionChecker
from suitbot import tournament as tour

from test_tournament import CFG, FakeBot, run_with_db

ACFG = replace(CFG, activity_min_points=2)


def group_msg(uid, text, reply_to=None, n=[0]):
    n[0] += 1
    m = {"message_id": n[0], "date": datetime.datetime.now(), "text": text,
         "chat": {"id": -100, "type": "supergroup", "title": "Chat"},
         "from": {"id": uid, "is_bot": False, "first_name": f"u{uid}"}}
    if reply_to:
        m["reply_to_message"] = {"message_id": 1, "date": datetime.datetime.now(), "text": "x",
                                 "chat": m["chat"], "from": {"id": reply_to, "is_bot": False, "first_name": "r"}}
    return Update.model_validate({"update_id": n[0], "message": m})


def test_chat_messages_earn_points_with_antispam(tmp_path):
    async def body(db):
        dp = Dispatcher()
        dp.include_router(activity.build_router(
            ACFG, db, lambda u: db.ensure_user(u.id, u.first_name, 500), SubscriptionChecker(ACFG)))
        bot = FakeBot()
        week = activity.week_of(ACFG)
        await dp.feed_update(bot, group_msg(1, "ок"))  # коротко — не считается
        assert await db.activity_of(week, 1) == (0, None)
        await dp.feed_update(bot, group_msg(1, "сегодня черва заходит хорошо"))
        await dp.feed_update(bot, group_msg(1, "и ещё одно сообщение подряд"))  # чаще раза в минуту — нет
        assert await db.activity_of(week, 1) == (1, 1)
        await dp.feed_update(bot, group_msg(2, "согласен, черва сегодня огонь", reply_to=1))  # ответ — +1
        assert await db.activity_of(week, 2) == (2, 1)
        assert await db.activity_of(week, 1) == (1, 2)
        await db.conn.execute("UPDATE activity SET last_msg_at = last_msg_at - 61")
        await dp.feed_update(bot, group_msg(1, "через минуту снова считается"))
        assert await db.activity_of(week, 1) == (2, 1)

    run_with_db(tmp_path, body)


def test_drop_first_n_win(tmp_path):
    async def body(db):
        for uid in (1, 2, 3, 4):
            await db.ensure_user(uid, f"u{uid}", 500)
        drop_id = await db.create_drop(-100, 300, 3)
        assert await db.claim_drop(drop_id, 1) == "ok"
        assert await db.claim_drop(drop_id, 1) == "again"
        assert await db.claim_drop(drop_id, 2) == "ok"
        assert await db.claim_drop(drop_id, 3) == "ok"
        assert await db.claim_drop(drop_id, 4) == "late"
        assert [(await db.get_user(u))["balance"] for u in (1, 2, 3, 4)] == [800, 800, 800, 500]
        assert (await db.get_drop(drop_id))["closed"] == 1
        assert [w["user_id"] for w in await db.drop_winners(drop_id)] == [1, 2, 3]

        star = await db.create_drop(-100, 0, 1, "50 ⭐")
        assert await db.claim_drop(star, 4) == "ok"
        assert (await db.get_user(4))["balance"] == 500  # звёзды отправляет админ, фишек нет
        assert await db.claim_drop(star, 1) == "late"

    run_with_db(tmp_path, body)


def test_drop_post_and_expiry(tmp_path):
    async def body(db):
        bot = FakeBot()
        assert await activity.post_drop(ACFG, db, bot) == "Чат ещё не выбран."
        await db.set_state("main_chat", "-100")
        await activity.post_drop(ACFG, db, bot, stars=True)
        assert "Звёздная раздача" in bot.sent[-1][1] and "50 ⭐" in bot.sent[-1][1]
        await db.conn.execute("UPDATE drops SET created_at = created_at - 3600")
        old = await db.open_drops_older_than(int(time.time()) - 600)
        assert len(old) == 1 and await db.close_drop(old[0]["id"])

    run_with_db(tmp_path, body)


def test_next_drop_inside_hours():
    zone = tour.zone(ACFG.tournament_tz)
    for _ in range(200):
        now = time.time() + _ * 3571
        at = activity.next_drop_at(ACFG, now)
        assert at > now
        assert 10 <= datetime.datetime.fromtimestamp(at, zone).hour < 23


def test_finish_week_announces_and_reports(tmp_path):
    async def body(db):
        bot = FakeBot()
        await db.set_state("main_chat", "-100")
        week = activity.week_of(ACFG) - 7 * 86400
        for uid, pts in ((1, 9), (2, 5), (3, 1)):
            await db.ensure_user(uid, f"Игрок{uid}", 500, username=f"p{uid}")
            await db.add_activity(week, uid, pts)
        await activity.finish_week(ACFG, db, bot, week)
        chat = dict(bot.sent)[-100]
        admin = dict(bot.sent)[42]
        assert "Игрок1 — 9 · 100 ⭐" in chat and "Игрок2 — 5 · 50 ⭐" in chat and "Игрок3" not in chat  # 1 < минимума
        assert "@p1" in admin and "100 ⭐" in admin

    run_with_db(tmp_path, body)
