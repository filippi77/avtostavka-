"""Панель управления в личке с ботом: /admin (только для ADMINS)."""

import logging
import time
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import cards
from . import tournament as tour
from .config import Config
from .db import DB

log = logging.getLogger(__name__)

TOURNAMENT_DAYS = (1, 3, 7)


def invite_text(cfg: Config, tournament=None) -> str:
    text = (
        "🎴 <b>Прогнозы на масти — игра в чате</b>\n\n"
        "Угадывайте масть в картах игрока и победителя раздачи, копите фишки и поднимайтесь в топ.\n\n"
        "<b>Как начать:</b>\n"
        f"1. Нажмите «Начать играть» и затем «Старт» — сразу получите {cfg.start_balance} фишек "
        "и кабинет с кнопками: баланс, бонус, рейтинг, турнир.\n"
        "2. После каждой игры здесь выходит карточка следующей игры — выберите сумму и масть. "
        "Ставки принимаются, пока идёт предыдущая игра.\n"
        f"3. Забирайте бонус {cfg.bonus_amount} фишек раз в {cfg.bonus_period_days} дн. и следите за рейтингом 📊.\n"
    )
    if tournament:
        text += (
            f"\n🏆 <b>Идёт турнир</b> до {tour.format_ends(cfg, tournament['ends_at'])}. Призы:\n"
            f"{tour.prizes_text(cfg)}\nУчастие бесплатное: /tournament\n"
        )
    return text + "\nФишки — игровая валюта, их нельзя вывести."


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
    rows.append([InlineKeyboardButton(text="📢 Приглашение в чат (и закрепить)", callback_data="adm:invite")])
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="adm:refresh")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


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

    @router.message(Command("setchat"), is_admin, F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP}))
    async def cmd_setchat(message: Message) -> None:
        await db.set_state("main_chat", str(message.chat.id))
        await message.reply("✅ Этот чат выбран основным: сюда будут приходить карточки игр и объявления турнира.")

    @router.callback_query(F.data.startswith("adm:"), is_admin)
    async def on_admin(query: CallbackQuery, bot: Bot) -> None:
        parts = query.data.split(":")
        action = parts[1]
        note = None

        if action == "start":
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
