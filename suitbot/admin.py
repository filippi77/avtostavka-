"""Панель управления в личке с ботом: /admin (только для ADMINS)."""

import logging
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import activity, cards, duels, i18n, shop
from .i18n import t
from . import tournament as tour
from .config import Config
from .db import DB

log = logging.getLogger(__name__)

TOURNAMENT_DAYS = (1, 3, 7)
GIFT_AMOUNTS = {"main": (500, 1000, 5000), "tour": (200, 500, 1000)}
WALLET_NAMES = {"main": "обычных", "tour": "турнирных"}


def invite_text(cfg: Config, tournament=None) -> str:
    text = t("invite", start=cfg.start_balance, bonus=cfg.bonus_amount, days=cfg.bonus_period_days)
    text += t("invite_shop")
    if tournament:
        text += t("invite_tour", ends=tour.format_ends(cfg, tournament["ends_at"]), prizes=tour.prizes_text(cfg))
    return text + t("invite_footer")


async def panel(cfg: Config, db: DB, bot: Bot) -> tuple[str, InlineKeyboardMarkup]:
    main_chat = await db.get_state("main_chat")
    if main_chat:
        try:
            chat_title = escape((await bot.get_chat(int(main_chat))).title or main_chat)
        except Exception:
            chat_title = f"{main_chat} (бот не видит чат)"
    else:
        chat_title = "выберется сам с первым постом канала в группе (или /setchat)"

    current = await db.active_tournament()
    every = await cards.card_every(cfg, db)
    last = await db.last_game()

    lines = [
        "⚙️ <b>Панель управления</b>\n",
        f"Чат: {chat_title}",
        f"Последняя игра канала: {f'#N{last}' if last is not None else 'ещё не видел'}",
        f"Карточки ставок: {cards.frequency_label(every)}",
    ]
    rows: list[list[InlineKeyboardButton]] = []
    if current:
        n = await db.entries_count(current["id"])
        lines.append(f"Турнир: 🟢 идёт до {tour.format_ends(cfg, current['ends_at'])}, участников {n}")
        rows.append([
            InlineKeyboardButton(text="📊 Таблица", callback_data="adm:table"),
            InlineKeyboardButton(text="⏹ Завершить сейчас", callback_data="adm:end"),
        ])
    else:
        lines.append("Турнир: ⚪️ не идёт")
        rows.append([
            InlineKeyboardButton(text=f"▶️ Турнир {d} дн.", callback_data=f"adm:start:{d}") for d in TOURNAMENT_DAYS
        ])
    lines.append(f"Призы: {' / '.join(escape(p) for p in cfg.tournament_prizes)}")

    try:
        balance = f"{(await bot.get_my_star_balance()).amount} ⭐"
    except Exception:
        balance = "не удалось получить"
    n, stars, buyers = await db.sales_summary()
    day_n, day_stars, _ = await db.sales_summary(int(time.time()) - 86400)
    lines += [
        "",
        f"⭐ Баланс звёзд бота: {balance}",
        f"Продажи всего: {stars} ⭐ · {n} покупок · {buyers} покупателей",
        f"За сутки: {day_stars} ⭐ · {day_n} покупок",
    ]

    rows.append([
        InlineKeyboardButton(
            text=("✅ " if every == f else "") + {0: "Выкл", 1: "Каждая"}.get(f, f"Раз в {f}"),
            callback_data=f"adm:cards:{f}",
        )
        for f in cards.CARD_FREQUENCIES
    ])
    duels_on = await duels.enabled(cfg, db)
    lines.append(f"Дуэли: {'✅ включены' if duels_on else '⛔️ выключены'}")
    rows.append([
        InlineKeyboardButton(text=f"⚔️ Дуэли: {'выключить' if duels_on else 'включить'}", callback_data="adm:duels"),
    ])
    if duels_on:
        rows.append([InlineKeyboardButton(text="📢 Анонс дуэлей в чат", callback_data="adm:duelnews")])
    other = "uz" if i18n.LANG == "ru" else "ru"
    lines.append(f"Язык для игроков: {i18n.LANGS[i18n.LANG]}")
    rows.append([InlineKeyboardButton(text=f"🌐 Язык → {i18n.LANGS[other]}", callback_data=f"adm:lang:{other}")])
    act_on, drops_on = await activity.activity_on(cfg, db), await activity.drops_on(cfg, db)
    nxt = await db.get_state("drop_next")
    nxt_text = tour.format_ends(cfg, int(nxt)) if nxt and drops_on else "—"
    lines.append(f"Актив недели: {'✅' if act_on else '⛔️'} · раздачи: {'✅' if drops_on else '⛔️'} "
                 f"(следующая ~{nxt_text})")
    rows.append([
        InlineKeyboardButton(text=f"🔥 Актив: {'выкл' if act_on else 'вкл'}", callback_data="adm:act"),
        InlineKeyboardButton(text=f"🎁 Раздачи: {'выкл' if drops_on else 'вкл'}", callback_data="adm:drops"),
    ])
    rows.append([
        InlineKeyboardButton(text="🎁 Раздача сейчас", callback_data="adm:dropnow"),
        InlineKeyboardButton(text="⭐ Звёздная раздача", callback_data="adm:dropstar"),
        InlineKeyboardButton(text="🔥 Таблица", callback_data="adm:acttable"),
    ])
    shop_open = await shop.shop_on(cfg, db)
    bought, spent = await db.shop_sales()
    lines.append(f"Магазин: {'✅ открыт' if shop_open else '⛔️ закрыт'} · покупок {bought} на {spent} фишек")
    rows.append([
        InlineKeyboardButton(text=f"🛒 Магазин: {'закрыть' if shop_open else 'открыть'}", callback_data="adm:shop"),
        InlineKeyboardButton(text="📢 Анонс магазина", callback_data="adm:shopnews"),
    ])
    rows.append([InlineKeyboardButton(text="🎁 Выдать всем фишки", callback_data="adm:gift")])
    rows.append([InlineKeyboardButton(text="📢 Приглашение в чат (и закрепить)", callback_data="adm:invite")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:refresh")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def duel_news_text(cfg: Config) -> str:
    return t("duel_news", min=cfg.duel_min_stake, max=cfg.duel_max_stake,
             options=", ".join(map(str, cfg.duel_game_options)))


async def gift_menu(cfg: Config, db: DB) -> tuple[str, InlineKeyboardMarkup]:
    current = await db.active_tournament()
    rows = [[InlineKeyboardButton(text=f"💰 +{a}", callback_data=f"adm:gq:main:{a}") for a in GIFT_AMOUNTS["main"]]]
    text = f"🎁 <b>Выдать всем фишки</b>\n\n💰 Обычные — всем игрокам ({await db.users_count()})"
    if current:
        rows.append([InlineKeyboardButton(text=f"🏆 +{a}", callback_data=f"adm:gq:tour:{a}") for a in GIFT_AMOUNTS["tour"]])
        text += f"\n🏆 Турнирные — всем участникам турнира ({await db.entries_count(current['id'])}), места не меняются"
    text += "\n\nДругая сумма: <code>/giveall 2000</code> или <code>/giveall турнир 300</code>"
    rows.append([InlineKeyboardButton(text="← Назад", callback_data="adm:refresh")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def gift_confirm(db: DB, wallet: str, amount: int) -> tuple[str, InlineKeyboardMarkup]:
    current = await db.active_tournament()
    who = f"всем участникам турнира ({await db.entries_count(current['id'])})" if wallet == "tour" and current \
        else f"всем игрокам ({await db.users_count()})"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, и объявить в чате", callback_data=f"adm:gd:{wallet}:{amount}:1")],
        [InlineKeyboardButton(text="✅ Да, без объявления", callback_data=f"adm:gd:{wallet}:{amount}:0")],
        [InlineKeyboardButton(text="Отмена", callback_data="adm:gift")],
    ])
    return f"Выдать <b>+{amount}</b> {WALLET_NAMES[wallet]} фишек {who}?", kb


async def give_all(cfg: Config, db: DB, bot: Bot, wallet: str, amount: int, announce: bool) -> str:
    current = await db.active_tournament()
    if wallet == "tour" and not current:
        return "Турнира нет — турнирные фишки выдать некому."
    n = await db.give_all(amount, current["id"] if wallet == "tour" else None)
    if announce:
        main_chat = await db.get_state("main_chat")
        if main_chat:
            text = t("gift_tour" if wallet == "tour" else "gift_all", amount=amount)
            try:
                await bot.send_message(int(main_chat), text)
            except Exception:
                log.exception("failed to announce gift")
    return f"Выдано +{amount} {WALLET_NAMES[wallet]} фишек: {n} игрокам."


def build_router(cfg: Config, db: DB) -> Router:
    router = Router()
    is_admin = F.from_user.id.in_(cfg.admins)

    @router.message(Command("admin"), is_admin, F.chat.type == ChatType.PRIVATE)
    async def cmd_admin(message: Message, bot: Bot) -> None:
        text, kb = await panel(cfg, db, bot)
        await message.answer(text, reply_markup=kb)

    @router.message(Command("admin"))
    async def cmd_admin_denied(message: Message) -> None:
        # Сюда попадают все, кого нет в ADMINS: подсказываем, что вписать, вместо молчания.
        if message.from_user is None or message.sender_chat is not None:
            await message.reply("Команду нужно писать от своего личного аккаунта, а не от имени канала.")
            return
        await message.reply(
            f"Нет доступа к панели. Ваш id: <code>{message.from_user.id}</code>\n"
            "Впишите его в настройку ADMINS (в начале файла бота) и перезапустите бота."
        )

    @router.message(Command("giveall"), is_admin)
    async def cmd_giveall(message: Message, bot: Bot) -> None:
        """/giveall 1000 — всем обычные фишки; /giveall турнир 300 — турнирные участникам."""
        args = (message.text or "").split()[1:]
        wallet = "tour" if args and args[0].lower() in ("турнир", "tour", "т") else "main"
        amount = args[-1] if args else ""
        if not amount.isdigit() or int(amount) <= 0:
            await message.reply("Формат: <code>/giveall 1000</code> или <code>/giveall турнир 300</code>")
            return
        text, kb = await gift_confirm(db, wallet, int(amount))
        await message.answer(text, reply_markup=kb)

    # Анонимный админ пишет от имени самой группы (sender_chat == чат) — так может только админ этой группы.
    is_group_admin = is_admin | (F.sender_chat.id == F.chat.id)

    @router.message(Command("setchat"), is_group_admin, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
    async def cmd_setchat(message: Message) -> None:
        await db.set_state("main_chat", str(message.chat.id))
        await message.reply("✅ Этот чат выбран основным: сюда будут приходить карточки игр и объявления турнира.")

    @router.callback_query(F.data.startswith("adm:"), is_admin)
    async def on_admin(query: CallbackQuery, bot: Bot) -> None:
        parts = query.data.split(":")
        action = parts[1]
        note = None

        if action in ("gift", "gq"):
            # Подменю выдачи и подтверждение — показываем их вместо панели.
            text, kb = await gift_menu(cfg, db) if action == "gift" else await gift_confirm(db, parts[2], int(parts[3]))
            await query.answer()
            await query.message.edit_text(text, reply_markup=kb)
            return
        if action == "lang":
            await db.set_state("lang", parts[2])
            i18n.set_lang(parts[2])
            note = f"Язык для игроков: {i18n.LANGS[i18n.LANG]}. Новые карточки и сообщения — на нём."
        elif action == "shop":
            on = await shop.shop_on(cfg, db)
            await db.set_state("shop_enabled", "0" if on else "1")
            note = "Магазин закрыт." if on else "Магазин открыт."
        elif action == "act":
            on = await activity.activity_on(cfg, db)
            await db.set_state("activity_enabled", "0" if on else "1")
            note = "Актив недели выключен." if on else "Актив недели включён."
        elif action == "drops":
            on = await activity.drops_on(cfg, db)
            await db.set_state("drops_enabled", "0" if on else "1")
            note = "Автоматические раздачи выключены." if on else "Автоматические раздачи включены."
        elif action in ("dropnow", "dropstar"):
            note = await activity.post_drop(cfg, db, bot, stars=action == "dropstar")
        elif action == "acttable":
            await bot.send_message(query.from_user.id, await activity.board_text(cfg, db, query.from_user.id))
        elif action == "duels":
            on = await duels.enabled(cfg, db)
            await db.set_state("duels_enabled", "0" if on else "1")
            note = "Дуэли выключены." if on else "Дуэли включены."
        elif action == "shopnews":
            main_chat = await db.get_state("main_chat")
            if not main_chat:
                note = "Чат ещё не выбран."
            else:
                me = await bot.me()
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=t("shop_open_btn"), url=f"https://t.me/{me.username}?start=shop")
                ]])
                msg = await bot.send_message(int(main_chat), shop.news_text(cfg), reply_markup=kb)
                try:
                    await bot.pin_chat_message(int(main_chat), msg.message_id, disable_notification=True)
                    note = "Анонс магазина отправлен и закреплён."
                except Exception:
                    note = "Анонс магазина отправлен."
        elif action == "duelnews":
            main_chat = await db.get_state("main_chat")
            if not main_chat:
                note = "Чат ещё не выбран."
            else:
                msg = await bot.send_message(int(main_chat), duel_news_text(cfg))
                try:
                    await bot.pin_chat_message(int(main_chat), msg.message_id, disable_notification=True)
                    note = "Анонс отправлен и закреплён."
                except Exception:
                    note = "Анонс отправлен."
        elif action == "gd":
            note = await give_all(cfg, db, bot, parts[2], int(parts[3]), parts[4] == "1")
        elif action == "start":
            days = int(parts[2])
            started = await tour.start(cfg, db, bot, int(time.time()) + days * 86400)
            note = f"Турнир запущен на {days} дн." if started else "Турнир уже идёт."
        elif action == "end":
            current = await db.active_tournament()
            if current:
                await tour.finish(cfg, db, bot, current)
                note = "Турнир завершён, итоги отправлены."
        elif action == "table":
            current = await db.active_tournament()
            if current:
                standings = await db.standings(current["id"])
                lines = ["📊 <b>Таблица турнира</b>"] + [
                    f"{tour.place_mark(i)} {escape(e['name'])} — {e['balance']} ({e['bets_count']} ст.)"
                    + ("" if tour.is_eligible(cfg, e, current) else " · пока не в призах")
                    for i, e in enumerate(standings[:20])
                ]
                await bot.send_message(query.from_user.id, "\n".join(lines) if standings else "Пока никто не вступил.")
        elif action == "cards":
            await db.set_state("card_every", parts[2])
            note = f"Карточки: {cards.frequency_label(int(parts[2]))}"
        elif action == "invite":
            main_chat = await db.get_state("main_chat")
            if not main_chat:
                note = "Сначала напишите /setchat в нужной группе."
            else:
                msg = await bot.send_message(
                    int(main_chat), invite_text(cfg, await db.active_tournament()),
                    reply_markup=await tour.join_keyboard(bot),
                )
                try:
                    await bot.pin_chat_message(int(main_chat), msg.message_id, disable_notification=True)
                    note = "Приглашение отправлено и закреплено."
                except Exception:
                    note = "Приглашение отправлено. Закрепить не вышло — дайте боту право закреплять сообщения."

        await query.answer(note or "")
        text, kb = await panel(cfg, db, bot)
        try:
            await query.message.edit_text(text, reply_markup=kb)
        except Exception as e:  # панель не изменилась
            log.debug("panel edit skipped: %s", e)

    return router
