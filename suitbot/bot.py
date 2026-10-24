import asyncio
import logging
import time
from collections import defaultdict
from html import escape

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ParseMode
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    KeyboardButton,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
    User,
)

from . import admin, betting, cards, rating
from . import tournament as tour
from .access import SubscriptionChecker
from .betting import describe_pick
from .config import Config
from .db import DB
from .parser import bet_wins, parse_game, parse_game_number, parse_pick, suit_emoji

log = logging.getLogger(__name__)

# Кнопки панели игрока в личке с ботом.
BTN_BALANCE = "💰 Мой баланс"
BTN_BONUS = "🎁 Бонус"
BTN_RATING = "📊 Рейтинг"
BTN_TOURNAMENT = "🏆 Турнир"
BTN_BUY = "⭐ Купить фишки"
BTN_HELP = "❓ Как играть"

MENU = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text=BTN_BALANCE), KeyboardButton(text=BTN_BONUS)],
        [KeyboardButton(text=BTN_RATING), KeyboardButton(text=BTN_TOURNAMENT)],
        [KeyboardButton(text=BTN_BUY), KeyboardButton(text=BTN_HELP)],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

HELP = (
    "<b>Как играть</b>\n\n"
    "В чате после каждой игры выходит карточка следующей игры с кнопками. "
    "Выберите сумму 💰 (и 🏆 Турнир, если идёт турнир), затем масть или исход. "
    "Ставки принимаются, пока идёт предыдущая игра, и закрываются, как только начинается игра карточки.\n\n"
    "<b>На что ставить:</b>\n"
    "♠️ ♣️ ♥️ ♦️ — эта масть будет в картах игрока, ×{suit:g}\n"
    "Игрок / Банкир — кто выиграет раздачу, ×{p:g} / ×{b:g}\n"
    "Ничья — ×{t:g}\n\n"
    "Можно и командой: <code>/bet 208 ♥ 50</code>, <code>/bet 208 игрок 50</code>, "
    "турнирная — <code>/tbet 208 ♥ 50</code>\n\n"
    "{bonus_line}\n"
    "Фишки — игровая валюта: их нельзя вывести или обменять на Stars."
)


def display_name(user: User) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def format_wait(seconds: int) -> str:
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    return (f"{d} дн " if d else "") + (f"{h} ч " if h or d else "") + f"{m} мин"


def build_router(cfg: Config, db: DB, subs: SubscriptionChecker) -> Router:
    router = Router()
    bonus_period = cfg.bonus_period_days * 86400

    async def user_row(user: User):
        return await db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username)

    def menu_for(message: Message):
        return MENU if message.chat.type == ChatType.PRIVATE else None

    async def require_sub(message: Message, bot: Bot) -> bool:
        if await subs.is_subscribed(bot, message.from_user.id):
            return True
        text, kb = subs.prompt()
        await message.reply(text, reply_markup=kb)
        return False

    async def cabinet_text(user) -> str:
        lines = [
            f"👤 <b>{escape(user['name'])}</b>",
            f"💰 Фишки: <b>{user['balance']}</b> · {await db.user_rank(user['id'])} место в рейтинге",
        ]
        current = await db.active_tournament() if cfg.tournament_enabled else None
        entry = await db.get_entry(current["id"], user["id"]) if current else None
        if entry:
            lines.append(f"🏆 Турнирные: <b>{entry['balance']}</b> · ставок {entry['bets_count']}/{cfg.tournament_min_bets}")
        elif current:
            lines.append(f"🏆 Идёт турнир до {tour.format_ends(cfg, current['ends_at'])} — нажмите «{BTN_TOURNAMENT}»")
        wait = user["last_bonus"] + bonus_period - int(time.time())
        lines.append(f"🎁 Бонус: {'можно забрать!' if wait <= 0 else 'через ' + format_wait(wait)}")
        bets = await db.user_open_bets(user["id"])
        if bets:
            lines.append("\nОткрытые ставки:")
            lines += [
                f"  {'🏆 ' if b['wallet'] == 'tour' else ''}#N{b['game']} · "
                f"{describe_pick(b['kind'], b['pick'])} · {b['amount']} ×{b['coef']:g}"
                for b in bets
            ]
        return "\n".join(lines)

    def help_text() -> str:
        period = "раз в неделю" if cfg.bonus_period_days == 7 else f"раз в {cfg.bonus_period_days} дн."
        return HELP.format(
            suit=cfg.payout_suit, p=cfg.payout_player, b=cfg.payout_banker, t=cfg.payout_tie,
            bonus_line=f"🎁 Бонус {cfg.bonus_amount} фишек {period}. Рейтинг — кнопка 📊 на карточке или в меню.",
        )

    # --- панель игрока --------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
        # Регистрация — это просто первое обращение к боту: аккаунт со стартовыми
        # фишками создаётся автоматически (здесь, по команде или по кнопке в чате).
        user = await user_row(message.from_user)
        if command.args == "help":
            await message.answer(help_text(), reply_markup=menu_for(message))
            return
        await message.answer(
            f"👋 Привет! Это игра в прогнозы на масти. Кнопки внизу — ваш кабинет.\n\n{await cabinet_text(user)}",
            reply_markup=menu_for(message),
        )
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if current and command.args == "join" and await require_sub(message, bot):
            await show_tournament(message)

    @router.message(Command("help"))
    @router.message(F.text == BTN_HELP)
    async def cmd_help(message: Message) -> None:
        await user_row(message.from_user)
        await message.answer(help_text(), reply_markup=menu_for(message))

    @router.message(Command("id"))
    async def cmd_id(message: Message) -> None:
        """Подсказка для настройки: id пользователя (для ADMINS) и чата."""
        await message.reply(f"Ваш id: <code>{message.from_user.id}</code>\nЭтот чат: <code>{message.chat.id}</code>")

    @router.message(Command("balance", "menu"))
    @router.message(F.text == BTN_BALANCE)
    async def cmd_balance(message: Message) -> None:
        user = await user_row(message.from_user)
        await message.reply(await cabinet_text(user), reply_markup=menu_for(message))

    @router.message(Command("bonus"))
    @router.message(F.text == BTN_BONUS)
    async def cmd_bonus(message: Message, bot: Bot) -> None:
        await user_row(message.from_user)
        if not await require_sub(message, bot):
            return
        wait = await db.claim_bonus(message.from_user.id, cfg.bonus_amount, bonus_period)
        if wait:
            await message.reply(f"Бонус уже получен. Следующий через {format_wait(wait)}.")
        else:
            user = await db.get_user(message.from_user.id)
            await message.reply(f"🎁 +{cfg.bonus_amount} фишек! Баланс: {user['balance']}")

    @router.message(Command("top", "rating"))
    @router.message(F.text == BTN_RATING)
    async def cmd_top(message: Message) -> None:
        await user_row(message.from_user)
        await message.reply(await rating.full_text(cfg, db, message.from_user.id))

    @router.callback_query(F.data == "sub:check")
    async def cb_sub_check(query: CallbackQuery, bot: Bot) -> None:
        if await subs.is_subscribed(bot, query.from_user.id):
            await query.answer("✅ Подписка есть — можно играть!", show_alert=True)
            if query.message:
                await query.message.edit_text("✅ Подписка подтверждена. Удачной игры!")
        else:
            await query.answer("Подписка пока не видна. Подпишитесь и нажмите ещё раз.", show_alert=True)

    # --- ставки -------------------------------------------------------------

    @router.message(Command("bet", "s"))
    async def cmd_bet(message: Message, command: CommandObject, bot: Bot) -> None:
        await place_bet(message, command, bot, tournament_bet=False)

    @router.message(Command("tbet", "t"))
    async def cmd_tbet(message: Message, command: CommandObject, bot: Bot) -> None:
        await place_bet(message, command, bot, tournament_bet=True)

    async def place_bet(message: Message, command: CommandObject, bot: Bot, tournament_bet: bool) -> None:
        args = (command.args or "").split()
        name = "tbet" if tournament_bet else "bet"
        usage = f"Формат: <code>/{name} 208 ♥ 50</code> (номер игры, масть или игрок/банкир/ничья, сумма)"
        if len(args) != 3 or not args[0].lstrip("#Nn").isdigit() or not args[2].isdigit():
            await message.reply(usage)
            return
        game, amount = int(args[0].lstrip("#Nn")), int(args[2])
        parsed = parse_pick(args[1])
        if not parsed:
            await message.reply("Не понял выбор. " + usage)
            return
        kind, pick = parsed
        await user_row(message.from_user)
        if not await require_sub(message, bot):
            return
        try:
            text = await betting.place(
                cfg, db, message.from_user.id, message.chat.id, game, kind, pick, amount, tournament_bet
            )
        except betting.BetError as e:
            await message.reply(str(e))
            return
        await message.reply(text)

    # --- турнир -------------------------------------------------------------

    @router.message(Command("tournament", "tour"))
    @router.message(F.text == BTN_TOURNAMENT)
    async def cmd_tournament(message: Message, bot: Bot) -> None:
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if not current:
            await message.reply("Сейчас турнира нет. Следите за объявлениями в чате!")
            return
        await user_row(message.from_user)
        if await require_sub(message, bot):
            await show_tournament(message)

    async def show_tournament(message: Message) -> None:
        current = await db.active_tournament()
        user = await db.get_user(message.from_user.id)
        entry, joined = await db.join_tournament(current["id"], user["id"], cfg.tournament_start_chips)
        standings = await db.standings(current["id"])

        lines = [f"🏆 <b>Турнир</b> · до {tour.format_ends(cfg, current['ends_at'])}"]
        if joined:
            lines.append(f"Вы в турнире! Выдано {cfg.tournament_start_chips} турнирных фишек.")
        lines += ["", tour.rules_text(cfg), "", "<b>Призы:</b>", tour.prizes_text(cfg), "", "<b>Таблица:</b>"]
        for i, e in enumerate(standings[:10]):
            mark = tour.MEDALS[i] if i < 3 else f"{i + 1}."
            note = "" if tour.is_eligible(cfg, e, current) else " · пока не в призах"
            lines.append(f"{mark} {escape(e['name'])} — {e['balance']} ({e['bets_count']} ст.){note}")
        place = next(i for i, e in enumerate(standings) if e["user_id"] == user["id"]) + 1
        me = standings[place - 1]
        lines.append(f"\nВы: {place} место · {me['balance']} фишек · ставок {me['bets_count']}/{cfg.tournament_min_bets}")
        await message.reply("\n".join(lines))

    # --- результаты из канала ----------------------------------------------

    def from_results_source(message: Message) -> bool:
        if not cfg.result_sources:
            return True
        source = message.sender_chat or message.chat
        if source is None:
            return False
        return source.id in cfg.result_sources or (source.username or "").lower() in cfg.result_sources

    async def handle_result_post(message: Message, bot: Bot) -> None:
        text = message.text or message.caption
        number = parse_game_number(text)
        if number is None or not from_results_source(message):
            return
        since = int(time.time()) - cfg.bet_ttl_hours * 3600
        first_post = not await db.game_seen_since(number, since)
        await db.mark_game_seen(number, fresh_after=since)
        # Пост игры N: закрываем ставки на N и сразу открываем карточку на N+1.
        await cards.close_for_game(cfg, db, bot, number)
        if first_post:
            await post_next_card(message, bot, number)

        result = parse_game(text)
        if result and result.finished:
            await settle(result, bot)

    async def post_next_card(message: Message, bot: Bot, number: int) -> None:
        main_chat = await db.get_state("main_chat")
        if main_chat:
            card_chat = int(main_chat)
        elif message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            # Первая группа, куда приходят посты канала, становится основным чатом —
            # туда же пойдут объявления турнира и приглашение. /setchat может это сменить.
            card_chat = message.chat.id
            await db.set_state("main_chat", str(card_chat))
        else:
            return
        try:
            await cards.maybe_post(cfg, db, bot, number, card_chat)
        except Exception:
            log.exception("failed to post game card to %s", card_chat)

    async def settle(result, bot: Bot) -> None:
        bets = await db.open_bets_for_game(result.number)
        if not bets:
            return

        reports: dict[int, list[str]] = defaultdict(list)
        for bet in bets:
            won = bet_wins(bet["kind"], bet["pick"], result)
            payout = int(bet["amount"] * bet["coef"]) if won else 0
            if not await db.settle_bet(bet["id"], won, payout):
                continue  # уже рассчитана (например, повторное редактирование поста)
            mark = f"✅ +{payout}" if won else f"❌ −{bet['amount']}"
            cup = "🏆 " if bet["wallet"] == "tour" else ""
            reports[bet["chat_id"]].append(
                f"{cup}{escape(bet['name'])}: {describe_pick(bet['kind'], bet['pick'])} {mark}"
            )

        player = " ".join(r + suit_emoji(s) for r, s in result.player_cards)
        banker = " ".join(r + suit_emoji(s) for r, s in result.banker_cards)
        header = (
            f"🎴 <b>#N{result.number}</b>: игрок {result.player_points} ({player}) — "
            f"банкир {result.banker_points} ({banker})"
        )
        for chat_id, lines in reports.items():
            try:
                await bot.send_message(chat_id, "\n".join([header, *lines]))
            except Exception:
                log.exception("failed to post results to %s", chat_id)

    # Посты канала приходят в привязанную группу как автопересылка (нужен
    # выключенный privacy mode или права админа), а если бот админ канала —
    # ещё и напрямую. Итог игры канал дописывает редактированием поста.
    router.channel_post.register(handle_result_post)
    router.edited_channel_post.register(handle_result_post)
    router.edited_message.register(handle_result_post, F.is_automatic_forward | F.sender_chat)
    router.message.register(handle_result_post, F.is_automatic_forward | F.sender_chat)

    # --- покупка фишек за Stars ---------------------------------------------

    @router.message(Command("buy"))
    @router.message(F.text == BTN_BUY)
    async def cmd_buy(message: Message, bot: Bot) -> None:
        if message.chat.type != ChatType.PRIVATE:
            me = await bot.me()
            await message.reply(f"Покупка — в личке: @{me.username}")
            return
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ {s} → {s * cfg.chips_per_star} фишек", callback_data=f"buy:{s}")]
                for s in cfg.star_packs
            ]
        )
        await message.answer("Выберите пакет фишек:", reply_markup=kb)

    @router.callback_query(F.data.startswith("buy:"))
    async def cb_buy(query: CallbackQuery, bot: Bot) -> None:
        stars = int(query.data.split(":")[1])
        if stars not in cfg.star_packs:
            await query.answer()
            return
        chips = stars * cfg.chips_per_star
        await bot.send_invoice(
            chat_id=query.from_user.id,
            title=f"{chips} фишек",
            description=f"{chips} игровых фишек для прогнозов. Фишки не выводятся и не обмениваются на Stars.",
            payload=f"chips:{stars}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{chips} фишек", amount=stars)],
        )
        await query.answer()

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery) -> None:
        ok = query.currency == "XTR" and query.invoice_payload == f"chips:{query.total_amount}"
        await query.answer(ok=ok, error_message=None if ok else "Неверный счёт, попробуйте ещё раз.")

    @router.message(F.successful_payment)
    async def on_payment(message: Message) -> None:
        payment = message.successful_payment
        await user_row(message.from_user)
        chips = payment.total_amount * cfg.chips_per_star
        if await db.record_payment(payment.telegram_payment_charge_id, message.from_user.id, payment.total_amount, chips):
            user = await db.get_user(message.from_user.id)
            await message.answer(f"⭐ Оплата получена: +{chips} фишек. Баланс: {user['balance']}")

    @router.message(Command("paysupport"))
    async def cmd_paysupport(message: Message) -> None:
        contact = cfg.support_contact or "администратору бота"
        await message.answer(
            f"По вопросам оплаты напишите {escape(contact)}. "
            "Укажите дату покупки — возврат Stars делается вручную."
        )

    # --- админ --------------------------------------------------------------

    @router.message(Command("give"), F.from_user.id.in_(cfg.admins))
    async def cmd_give(message: Message, command: CommandObject) -> None:
        """/give СУММА — ответом на сообщение игрока (сумма может быть отрицательной)."""
        target = message.reply_to_message.from_user if message.reply_to_message else None
        arg = (command.args or "").strip()
        if not target or not arg.lstrip("-").isdigit():
            await message.reply("Ответьте на сообщение игрока: /give 500")
            return
        await user_row(target)
        await db.add_balance(target.id, int(arg))
        user = await db.get_user(target.id)
        await message.reply(f"{escape(user['name'])}: баланс {user['balance']}")

    return router


async def refund_loop(cfg: Config, db: DB) -> None:
    while True:
        await asyncio.sleep(600)
        try:
            stale = await db.refund_stale_bets(int(time.time()) - cfg.bet_ttl_hours * 3600)
            for bet in stale:
                log.info("refunded stale bet %s (game %s)", bet["id"], bet["game"])
        except Exception:
            log.exception("refund loop failed")


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    cfg = Config()
    log.info("admins: %s, result sources: %s, required channel: %s",
             sorted(cfg.admins) or "не заданы", cfg.result_sources or "любые", cfg.required_channel or "нет")
    db = DB(cfg.db_path)
    await db.open()
    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    subs = SubscriptionChecker(cfg)

    @dp.errors()
    async def on_error(event: ErrorEvent, bot: Bot) -> None:
        # Любой сбой обработчика пишем в лог, а админу — ещё и в личку, чтобы не гадать, почему бот молчит.
        log.error("handler failed", exc_info=event.exception)
        update = event.update
        user = (update.message and update.message.from_user) or (
            update.callback_query and update.callback_query.from_user
        )
        if user and user.id in cfg.admins:
            error = f"{type(event.exception).__name__}: {event.exception}"
            try:
                await bot.send_message(user.id, f"⚠️ Ошибка в боте:\n<code>{escape(error[:800])}</code>")
            except Exception:
                log.exception("failed to report error to admin")
    dp.include_router(admin.build_router(cfg, db))
    dp.include_router(cards.build_router(
        cfg, db, lambda user: db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username), subs
    ))
    dp.include_router(build_router(cfg, db, subs))
    tasks = [asyncio.create_task(refund_loop(cfg, db)), asyncio.create_task(cards.window_loop(cfg, db, bot))]
    if cfg.tournament_enabled:
        tasks.append(asyncio.create_task(tour.loop(cfg, db, bot)))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in tasks:
            task.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
