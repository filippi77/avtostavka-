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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    User,
)

from .config import Config
from .db import DB, InsufficientFunds
from .parser import bet_wins, parse_game, parse_game_number, parse_pick

log = logging.getLogger(__name__)

STAR_PACKS = (50, 100, 250, 500)
SIDE_NAMES = {"P": "игрок", "B": "банкир", "T": "ничья"}

HELP = (
    "<b>Прогнозы на баккару</b>\n\n"
    "Ставка: <code>/bet НОМЕР ВЫБОР СУММА</code>\n"
    "  <code>/bet 208 ♥ 50</code> — в картах игрока будет черва\n"
    "  <code>/bet 208 пики 50</code> — масти: ♠ пики, ♣ крести, ♥ черви, ♦ буби\n"
    "  <code>/bet 208 игрок 50</code> — победа игрока / банкир / ничья\n\n"
    "Коэффициенты: масть ×{suit}, игрок ×{p}, банкир ×{b}, ничья ×{t}\n"
    "Ставки на игру закрываются, как только в канале появился её пост.\n\n"
    "/balance — баланс и открытые ставки\n"
    "/bonus — ежедневный бонус {bonus} фишек\n"
    "/top — таблица лидеров\n"
    "/buy — купить фишки за Telegram Stars (в личке с ботом)\n\n"
    "Фишки — игровая валюта: их нельзя вывести или обменять на Stars."
)


def display_name(user: User) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def describe_pick(kind: str, pick: str) -> str:
    return pick if kind == "suit" else SIDE_NAMES[pick]


def build_router(cfg: Config, db: DB) -> Router:
    router = Router()

    async def user_row(user: User):
        return await db.ensure_user(user.id, display_name(user), cfg.start_balance)

    # --- общие команды ------------------------------------------------------

    @router.message(CommandStart())
    @router.message(Command("help"))
    async def cmd_help(message: Message) -> None:
        await user_row(message.from_user)
        await message.answer(
            HELP.format(
                suit=cfg.payout_suit, p=cfg.payout_player, b=cfg.payout_banker,
                t=cfg.payout_tie, bonus=cfg.daily_bonus,
            )
        )

    @router.message(Command("balance"))
    async def cmd_balance(message: Message) -> None:
        user = await user_row(message.from_user)
        lines = [f"💰 {escape(user['name'])}: <b>{user['balance']}</b> фишек"]
        bets = await db.user_open_bets(user["id"])
        if bets:
            lines.append("\nОткрытые ставки:")
            lines += [
                f"  #N{b['game']} · {describe_pick(b['kind'], b['pick'])} · {b['amount']} ×{b['coef']:g}"
                for b in bets
            ]
        await message.reply("\n".join(lines))

    @router.message(Command("bonus"))
    async def cmd_bonus(message: Message) -> None:
        await user_row(message.from_user)
        wait = await db.claim_bonus(message.from_user.id, cfg.daily_bonus)
        if wait:
            h, m = divmod(wait // 60, 60)
            await message.reply(f"Бонус уже получен. Следующий через {h} ч {m} мин.")
        else:
            await message.reply(f"🎁 +{cfg.daily_bonus} фишек!")

    @router.message(Command("top"))
    async def cmd_top(message: Message) -> None:
        rows = await db.top()
        if not rows:
            await message.reply("Пока никого нет.")
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = ["🏆 <b>Топ игроков</b>"]
        for i, row in enumerate(rows):
            mark = medals[i] if i < len(medals) else f"{i + 1}."
            lines.append(f"{mark} {escape(row['name'])} — {row['balance']}")
        await message.reply("\n".join(lines))

    # --- ставки -------------------------------------------------------------

    @router.message(Command("bet", "s"))
    async def cmd_bet(message: Message, command: CommandObject) -> None:
        args = (command.args or "").split()
        usage = "Формат: <code>/bet 208 ♥ 50</code> (номер игры, масть или игрок/банкир/ничья, сумма)"
        if len(args) != 3 or not args[0].lstrip("#Nn").isdigit() or not args[2].isdigit():
            await message.reply(usage)
            return
        game, amount = int(args[0].lstrip("#Nn")), int(args[2])
        parsed = parse_pick(args[1])
        if not parsed:
            await message.reply("Не понял выбор. " + usage)
            return
        kind, pick = parsed

        if not cfg.min_bet <= amount <= cfg.max_bet:
            await message.reply(f"Ставка от {cfg.min_bet} до {cfg.max_bet} фишек.")
            return

        last = await db.last_game()
        if last is None:
            await message.reply("Ещё не видел ни одного поста канала — подождите следующую игру.")
            return
        ahead = (game - last) % cfg.game_number_wrap
        if not 1 <= ahead <= cfg.max_games_ahead:
            await message.reply(
                f"Последняя игра #N{last}. Ставки принимаются на #N{last + 1}…#N{last + cfg.max_games_ahead}."
            )
            return
        if await db.game_seen_since(game, int(time.time()) - cfg.bet_ttl_hours * 3600):
            await message.reply(f"Игра #N{game} уже началась, ставки закрыты.")
            return

        await user_row(message.from_user)
        coef = cfg.payout(kind, pick)
        try:
            await db.place_bet(message.from_user.id, message.chat.id, game, kind, pick, amount, coef)
        except InsufficientFunds:
            user = await db.get_user(message.from_user.id)
            await message.reply(f"Недостаточно фишек: на балансе {user['balance']}. /bonus или /buy")
            return
        await message.reply(
            f"✅ Ставка принята: #N{game} · {describe_pick(kind, pick)} · {amount} ×{coef:g} "
            f"(выигрыш {int(amount * coef)})"
        )

    # --- результаты из канала ----------------------------------------------

    def from_results_source(message: Message) -> bool:
        if not cfg.result_sources:
            return True
        source = message.sender_chat or message.chat
        return source is not None and source.id in cfg.result_sources

    async def handle_result_post(message: Message, bot: Bot) -> None:
        text = message.text or message.caption
        number = parse_game_number(text)
        if number is None or not from_results_source(message):
            return
        await db.mark_game_seen(number, fresh_after=int(time.time()) - cfg.bet_ttl_hours * 3600)

        result = parse_game(text)
        if not result or not result.finished:
            return
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
            reports[bet["chat_id"]].append(
                f"{escape(bet['name'])}: {describe_pick(bet['kind'], bet['pick'])} {mark}"
            )

        player = " ".join(r + s for r, s in result.player_cards)
        banker = " ".join(r + s for r, s in result.banker_cards)
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
    async def cmd_buy(message: Message, bot: Bot) -> None:
        if message.chat.type != ChatType.PRIVATE:
            me = await bot.me()
            await message.reply(f"Покупка — в личке: @{me.username}")
            return
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"⭐ {s} → {s * cfg.chips_per_star} фишек", callback_data=f"buy:{s}")]
                for s in STAR_PACKS
            ]
        )
        await message.answer("Выберите пакет фишек:", reply_markup=kb)

    @router.callback_query(F.data.startswith("buy:"))
    async def cb_buy(query: CallbackQuery, bot: Bot) -> None:
        stars = int(query.data.split(":")[1])
        if stars not in STAR_PACKS:
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
        await message.answer(
            "По вопросам оплаты напишите администратору бота. "
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
    db = DB(cfg.db_path)
    await db.open()
    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(build_router(cfg, db))
    refunds = asyncio.create_task(refund_loop(cfg, db))
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        refunds.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
