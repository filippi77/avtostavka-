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

from . import activity, admin, betting, cards, duels, i18n, penalty, quick, rating, shop
from . import tournament as tour
from .access import SubscriptionChecker
from .betting import describe_pick
from .config import Config
from .db import DB
from .i18n import t, variants
from .parser import bet_wins, parse_game, parse_game_number, parse_pick, suit_emoji

log = logging.getLogger(__name__)

# Значения анимированного слота Telegram (1–64): три барабана по 4 символа.
SLOT_SYMBOLS = ("BAR", "🍇", "🍋", "7️⃣")


def menu() -> ReplyKeyboardMarkup:
    """Кнопки кабинета в личке с ботом — на текущем языке."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=t("btn_balance")), KeyboardButton(text=t("btn_bonus"))],
            [KeyboardButton(text=t("btn_rating")), KeyboardButton(text=t("btn_tournament"))],
            [KeyboardButton(text=t("btn_spin")), KeyboardButton(text=t("btn_shop"))],
            [KeyboardButton(text=t("btn_buy")), KeyboardButton(text=t("btn_active"))],
            [KeyboardButton(text=t("btn_help"))],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def display_name(user: User) -> str:
    return user.full_name or (f"@{user.username}" if user.username else str(user.id))


def format_wait(seconds: int) -> str:
    d, rest = divmod(seconds, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    return (f"{d} {t('unit_d')} " if d else "") + (f"{h} {t('unit_h')} " if h or d else "") + f"{m} {t('unit_m')}"


def build_router(cfg: Config, db: DB, subs: SubscriptionChecker) -> Router:
    router = Router()
    bonus_period = cfg.bonus_period_days * 86400

    async def user_row(user: User):
        return await db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username)

    def menu_for(message: Message):
        return menu() if message.chat.type == ChatType.PRIVATE else None

    async def require_sub(message: Message, bot: Bot) -> bool:
        if await subs.is_subscribed(bot, message.from_user.id):
            return True
        text, kb = subs.prompt()
        await message.reply(text, reply_markup=kb)
        return False

    async def cabinet_text(user) -> str:
        lines = [
            f"👤 <b>{escape((user['badge'] + ' ' if user['badge'] else '') + user['name'])}</b>",
            t("cab_chips", balance=user["balance"], rank=await db.user_rank(user["id"])),
        ]
        current = await db.active_tournament() if cfg.tournament_enabled else None
        entry = await db.get_entry(current["id"], user["id"]) if current else None
        if entry:
            lines.append(t("cab_tour", balance=entry["balance"], bets=entry["bets_count"], min_bets=cfg.tournament_min_bets))
        elif current:
            lines.append(t("cab_tour_join", ends=tour.format_ends(cfg, current["ends_at"]), button=t("btn_tournament")))
        wait = user["last_bonus"] + bonus_period - int(time.time())
        lines.append(t("cab_bonus_ready") if wait <= 0 else t("cab_bonus_wait", wait=format_wait(wait)))
        spin_wait = user["last_spin"] + 86400 - int(time.time())
        lines.append(t("cab_spin_ready") if spin_wait <= 0 else t("cab_spin_wait", wait=format_wait(spin_wait)))
        lines += await shop.owned_lines(cfg, db, user)
        points, place = await db.activity_of(activity.week_of(cfg), user["id"])
        if place:
            lines.append(t("cab_active", points=points, place=place))
        w, l, d = await db.duel_stats(user["id"])
        if w or l or d:
            lines.append(t("cab_duels", w=w, l=l) + (t("cab_duels_draws", d=d) if d else ""))
        bets = await db.user_open_bets(user["id"])
        if bets:
            lines.append(t("cab_open_bets"))
            lines += [
                f"  {'🏆 ' if b['wallet'] == 'tour' else ''}#N{b['game']} · "
                f"{describe_pick(b['kind'], b['pick'])} · {b['amount']} ×{b['coef']:g}"
                for b in bets
            ]
        return "\n".join(lines)

    def help_text(duels_on: bool = True) -> str:
        duel_line = t("help_duel", options=", ".join(map(str, cfg.duel_game_options))) if duels_on else ""
        period = t("period_week") if cfg.bonus_period_days == 7 else t("period_days", days=cfg.bonus_period_days)
        return t(
            "help", suit=f"{cfg.payout_suit:g}", p=f"{cfg.payout_player:g}", b=f"{cfg.payout_banker:g}",
            t=f"{cfg.payout_tie:g}", jackpot=cfg.spin_prizes[0], duel_line=duel_line + t("help_active") + shop.help_line(cfg),
            bonus_line=t("help_bonus", amount=cfg.bonus_amount, period=period),
        )

    # --- панель игрока --------------------------------------------------------

    @router.message(CommandStart())
    async def cmd_start(message: Message, command: CommandObject, bot: Bot) -> None:
        # Регистрация — это просто первое обращение к боту: аккаунт со стартовыми
        # фишками создаётся автоматически (здесь, по команде или по кнопке в чате).
        user = await user_row(message.from_user)
        if command.args and command.args[:1] == "g" and command.args[1:].isdigit():
            # Кнопка «🎯 Сделать ставку» под карточкой игры: личный выбор ставки.
            if not await require_sub(message, bot):
                return
            await cards.send_picker(cfg, db, bot, message.chat.id, int(command.args[1:]))
            return
        if command.args == "help":
            await message.answer(help_text(await duels.enabled(cfg, db)), reply_markup=menu_for(message))
            return
        if command.args == "shop" and await shop.shop_on(cfg, db):
            # Ссылка из анонса в чате ведёт сразу в магазин; клавиатуру кабинета тоже показываем.
            await message.answer(t("welcome"), reply_markup=menu_for(message))
            text, kb = await shop.menu(cfg, db, user)
            await message.answer(text, reply_markup=kb)
            return
        await message.answer(
            f"{t('welcome')}\n\n{await cabinet_text(user)}",
            reply_markup=menu_for(message),
        )
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if current and command.args == "join" and await require_sub(message, bot):
            await show_tournament(message)

    @router.message(Command("help"))
    @router.message(F.text.in_(variants("btn_help")))
    async def cmd_help(message: Message) -> None:
        await user_row(message.from_user)
        await message.answer(help_text(await duels.enabled(cfg, db)), reply_markup=menu_for(message))

    @router.message(Command("id"))
    async def cmd_id(message: Message) -> None:
        """Подсказка для настройки: id пользователя (для ADMINS) и чата."""
        await message.reply(t("id_info", user=message.from_user.id, chat=message.chat.id))

    @router.message(Command("balance", "menu"))
    @router.message(F.text.in_(variants("btn_balance")))
    async def cmd_balance(message: Message) -> None:
        user = await user_row(message.from_user)
        await message.reply(await cabinet_text(user), reply_markup=menu_for(message))

    @router.message(Command("bonus"))
    @router.message(F.text.in_(variants("btn_bonus")))
    async def cmd_bonus(message: Message, bot: Bot) -> None:
        await user_row(message.from_user)
        if not await require_sub(message, bot):
            return
        wait = await db.claim_bonus(message.from_user.id, cfg.bonus_amount, bonus_period)
        if wait:
            await message.reply(t("bonus_wait", wait=format_wait(wait)))
        else:
            user = await db.get_user(message.from_user.id)
            await message.reply(t("bonus_ok", amount=cfg.bonus_amount, balance=user["balance"]))

    @router.message(Command("spin"))
    @router.message(F.text.in_(variants("btn_spin")))
    async def cmd_spin(message: Message, bot: Bot) -> None:
        await user_row(message.from_user)
        if message.chat.type != ChatType.PRIVATE:
            me = await bot.me()
            await message.reply(t("spin_in_dm", bot=me.username))
            return
        if not await require_sub(message, bot):
            return
        wait = await db.claim_spin(message.from_user.id)
        if wait:
            await message.answer(t("spin_wait", wait=format_wait(wait)))
            return
        # Результат выбирает сам Telegram — ни бот, ни админ не могут на него повлиять.
        dice = await bot.send_dice(message.chat.id, emoji="🎰")
        reels = [SLOT_SYMBOLS[((dice.dice.value - 1) >> (2 * i)) & 3] for i in range(3)]
        same = max(reels.count(x) for x in reels)
        jackpot, triple, double, miss = cfg.spin_prizes
        if reels == ["7️⃣"] * 3:
            prize, title = jackpot, t("spin_jackpot")
        elif same == 3:
            prize, title = triple, t("spin_triple", symbol=reels[0])
        elif same == 2:
            prize, title = double, t("spin_double")
        else:
            prize, title = miss, t("spin_miss")
        await db.add_balance(message.from_user.id, prize)
        await asyncio.sleep(2.5)  # дождаться, пока барабаны остановятся
        user = await db.get_user(message.from_user.id)
        await message.answer(t("spin_result", title=title, prize=prize, balance=user["balance"]))

    @router.message(Command("top", "rating"))
    @router.message(F.text.in_(variants("btn_rating")))
    async def cmd_top(message: Message) -> None:
        await user_row(message.from_user)
        await message.reply(await rating.full_text(cfg, db, message.from_user.id))

    @router.callback_query(F.data == "sub:check")
    async def cb_sub_check(query: CallbackQuery, bot: Bot) -> None:
        if await subs.is_subscribed(bot, query.from_user.id):
            await query.answer(t("sub_ok_alert"), show_alert=True)
            if query.message:
                await query.message.edit_text(t("sub_ok"))
        else:
            await query.answer(t("sub_missing"), show_alert=True)

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
        usage = t("bet_usage", cmd=name)
        if len(args) != 3 or not args[0].lstrip("#Nn").isdigit() or not args[2].isdigit():
            await message.reply(usage)
            return
        game, amount = int(args[0].lstrip("#Nn")), int(args[2])
        parsed = penalty.parse_pick(args[1]) if cfg.game == "penalty" else parse_pick(args[1])
        if not parsed:
            await message.reply(t("bet_bad_pick") + usage)
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
        await activity.add(cfg, db, message.from_user.id, activity.POINTS_BET)
        await message.reply(text)

    # --- турнир -------------------------------------------------------------

    @router.message(Command("tournament", "tour"))
    @router.message(F.text.in_(variants("btn_tournament")))
    async def cmd_tournament(message: Message, bot: Bot) -> None:
        current = await db.active_tournament() if cfg.tournament_enabled else None
        if not current:
            await message.reply(t("tour_none"))
            return
        await user_row(message.from_user)
        if await require_sub(message, bot):
            await show_tournament(message)

    async def show_tournament(message: Message) -> None:
        current = await db.active_tournament()
        user = await db.get_user(message.from_user.id)
        entry, joined = await db.join_tournament(current["id"], user["id"], cfg.tournament_start_chips)
        standings = await db.standings(current["id"])

        lines = [t("tour_title", ends=tour.format_ends(cfg, current["ends_at"]))]
        if joined:
            lines.append(t("tour_joined", chips=cfg.tournament_start_chips))
        lines += ["", tour.rules_text(cfg), "", t("tour_prizes"), tour.prizes_text(cfg), "", t("tour_table")]
        for i, e in enumerate(standings[:10]):
            note = "" if tour.is_eligible(cfg, e, current) else t("tour_not_eligible")
            lines.append(t("tour_row", mark=tour.place_mark(i), name=escape(e["name"]), balance=e["balance"],
                           bets=e["bets_count"], note=note))
        place = next(i for i, e in enumerate(standings) if e["user_id"] == user["id"]) + 1
        me = standings[place - 1]
        lines.append(t("tour_me", place=place, balance=me["balance"], bets=me["bets_count"], min_bets=cfg.tournament_min_bets))
        await message.reply("\n".join(lines))

    # --- результаты из канала ----------------------------------------------

    def from_results_source(message: Message) -> bool:
        if not cfg.result_sources:
            return True
        source = message.sender_chat or message.chat
        if source is None:
            return False
        return source.id in cfg.result_sources or (source.username or "").lower() in cfg.result_sources

    def since() -> int:
        return int(time.time()) - cfg.bet_ttl_hours * 3600

    async def mark_started(number: int, bot: Bot) -> bool:
        return await start_game(cfg, db, bot, number)

    async def handle_result_post(message: Message, bot: Bot) -> None:
        text = message.text or message.caption
        number = parse_game_number(text)
        if number is None or not from_results_source(message):
            return
        if cfg.game == "penalty":
            await handle_penalty_post(message, bot, text)
            return
        # Пост игры N: закрываем ставки на N и сразу открываем карточку на N+1.
        if await mark_started(number, bot):
            await post_next_card(message, bot, number)

        result = parse_game(text)
        if result and result.finished:
            player = " ".join(r + suit_emoji(s) for r, s in result.player_cards)
            banker = " ".join(r + suit_emoji(s) for r, s in result.banker_cards)
            header = t("result_header", game=result.number, pp=result.player_points, pc=player,
                       bp=result.banker_points, bc=banker)
            await settle(result.number, header, lambda kind, pick: bet_wins(kind, pick, result), bot)
            await duels.on_game_result(cfg, db, bot, result.number, result.player_suits)

    async def handle_penalty_post(message: Message, bot: Bot, text: str) -> None:
        post = penalty.parse_post(text)
        if not post:
            return
        if not post.started:
            # Канал публикует серию заранее: запоминаем команды и коэффициенты, выкладываем карточку.
            await db.save_penalty_game(post.number, post.home, post.away, post.odds, post.line)
            if await db.last_game() is None:
                await db.set_state("last_game", str(post.number - 1))
            existing = await db.open_cards_for_game(post.number, since())
            for card in existing:
                await cards.refresh(cfg, db, bot, post.number, card["chat_id"])  # коэффициенты могли измениться
            if not existing:
                await post_next_card(message, bot, post.number)
            return
        await mark_started(post.number, bot)
        if post.finished:
            header = t("pen_result", game=post.number, home=escape(post.home), away=escape(post.away),
                       a=post.score[0], b=post.score[1])
            await settle(post.number, header, lambda kind, pick: penalty.bet_wins(kind, pick, post), bot)
            await duels.on_game_result(cfg, db, bot, post.number, {post.winner} if post.winner else set())
            next_game = post.number % cfg.game_number_wrap + 1
            if cfg.penalty_close_on_prev_finish:
                await mark_started(next_game, bot)
            elif cfg.penalty_start_delay:
                # Следующая серия начнётся минуты через четыре — закроем ставки на неё заранее.
                await db.set_state("pen_close", f"{next_game}:{int(time.time()) + cfg.penalty_start_delay}")

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

    async def settle(number: int, header: str, wins, bot: Bot) -> None:
        bets = await db.open_bets_for_game(number)
        if not bets:
            return
        info = await db.get_penalty_game(number, since()) if cfg.game == "penalty" else None

        # Несколько ставок одного игрока на одно и то же суммируются в одну запись.
        merged: dict[int, dict[tuple, list[int]]] = defaultdict(dict)
        for bet in bets:
            won = wins(bet["kind"], bet["pick"])
            payout = int(bet["amount"] * bet["coef"]) if won else 0
            if not await db.settle_bet(bet["id"], won, payout):
                continue  # уже рассчитана (например, повторное редактирование поста)
            key = (bet["name"], bet["wallet"] == "tour", describe_pick(bet["kind"], bet["pick"], info), won)
            acc = merged[bet["chat_id"]].setdefault(key, [0, 0])
            acc[0] += payout if won else bet["amount"]
            acc[1] += 1

        reports: dict[int, list[str]] = defaultdict(list)
        for chat_id, items in merged.items():
            for (name, tour, pick, won), (total, n) in items.items():
                if won:
                    mark = f"✅ +{total}" + (" 🔥" if total >= 1000 else "")
                else:
                    mark = f"❌ −{total}"
                cup = "🏆" if tour else ""
                reports[chat_id].append(f"{cup}{escape(name)} {pick} {mark}" + (f" (×{n})" if n > 1 else ""))

        for chat_id, lines in reports.items():
            try:
                # Одна строка на всех: кто на что ставил и чем кончилось.
                await bot.send_message(chat_id, f"{header}\n{' · '.join(lines)}")
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
    @router.message(F.text.in_(variants("btn_buy")))
    async def cmd_buy(message: Message, bot: Bot) -> None:
        if message.chat.type != ChatType.PRIVATE:
            me = await bot.me()
            await message.reply(t("buy_in_dm", bot=me.username))
            return
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=t("buy_pack", stars=s, chips=s * cfg.chips_per_star), callback_data=f"buy:{s}")]
                for s in cfg.star_packs
            ]
        )
        await message.answer(t("buy_choose"), reply_markup=kb)

    @router.callback_query(F.data.startswith("buy:"))
    async def cb_buy(query: CallbackQuery, bot: Bot) -> None:
        stars = int(query.data.split(":")[1])
        if stars not in cfg.star_packs:
            await query.answer()
            return
        chips = stars * cfg.chips_per_star
        await bot.send_invoice(
            chat_id=query.from_user.id,
            title=t("buy_title", chips=chips),
            description=t("buy_desc", chips=chips),
            payload=f"chips:{stars}",
            currency="XTR",
            prices=[LabeledPrice(label=t("buy_title", chips=chips), amount=stars)],
        )
        await query.answer()

    @router.pre_checkout_query()
    async def pre_checkout(query: PreCheckoutQuery) -> None:
        ok = query.currency == "XTR" and query.invoice_payload == f"chips:{query.total_amount}"
        await query.answer(ok=ok, error_message=None if ok else t("buy_bad"))

    @router.message(F.successful_payment)
    async def on_payment(message: Message) -> None:
        payment = message.successful_payment
        await user_row(message.from_user)
        chips = payment.total_amount * cfg.chips_per_star
        if await db.record_payment(payment.telegram_payment_charge_id, message.from_user.id, payment.total_amount, chips):
            user = await db.get_user(message.from_user.id)
            await message.answer(t("buy_ok", chips=chips, balance=user["balance"]))

    @router.message(Command("paysupport"))
    async def cmd_paysupport(message: Message) -> None:
        await message.answer(t("paysupport", contact=escape(cfg.support_contact or t("paysupport_default"))))

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


async def start_game(cfg: Config, db: DB, bot: Bot, number: int) -> bool:
    """Игра началась: закрываем ставки на неё. True — если узнали об этом впервые."""
    since = int(time.time()) - cfg.bet_ttl_hours * 3600
    first = not await db.game_seen_since(number, since)
    await db.mark_game_seen(number, fresh_after=since, wrap=cfg.game_number_wrap)
    await cards.close_for_game(cfg, db, bot, number)
    if first:
        await duels.on_game_started(cfg, db, bot, number)
    return first


async def penalty_close_loop(cfg: Config, db: DB, bot: Bot) -> None:
    """Пенальти: закрывает ставки на следующую серию по таймеру после конца предыдущей."""
    while True:
        try:
            planned = await db.get_state("pen_close", "")
            if planned:
                number, at = map(int, planned.split(":"))
                if time.time() >= at:
                    await db.set_state("pen_close", "")
                    await start_game(cfg, db, bot, number)
        except Exception:
            log.exception("penalty close loop failed")
        await asyncio.sleep(2)


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
    i18n.set_lang(await db.get_state("lang", cfg.lang))
    i18n.set_game(cfg.game)
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
    dp.include_router(duels.build_router(
        cfg, db, lambda user: db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username), subs
    ))
    dp.include_router(quick.build_router(
        cfg, db, lambda user: db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username), subs
    ))
    dp.include_router(shop.build_router(
        cfg, db, lambda user: db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username)
    ))
    dp.include_router(build_router(cfg, db, subs))
    # Последним: ловит обычные сообщения в чате для «Актива недели».
    dp.include_router(activity.build_router(
        cfg, db, lambda user: db.ensure_user(user.id, display_name(user), cfg.start_balance, user.username), subs
    ))
    tasks = [
        asyncio.create_task(activity.loop(cfg, db, bot)),
        asyncio.create_task(shop.loop(cfg, db, bot)),
        asyncio.create_task(refund_loop(cfg, db)),
        asyncio.create_task(cards.window_loop(cfg, db, bot)),
        asyncio.create_task(duels.loop(cfg, db, bot)),
    ]
    if cfg.game == "penalty":
        tasks.append(asyncio.create_task(penalty_close_loop(cfg, db, bot)))
    if cfg.tournament_enabled:
        tasks.append(asyncio.create_task(tour.loop(cfg, db, bot)))
    await quick.set_commands(cfg, bot)
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        for task in tasks:
            task.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
