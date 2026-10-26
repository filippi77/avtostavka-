"""Магазин за фишки в личке с ботом.

Товары: значок у имени во всех сообщениях бота (навсегда), звание в чате на
SHOP_TITLE_DAYS дней (готовое или своё), VIP на SHOP_VIP_DAYS дней (ставки до
VIP_MAX_BET) и лишняя попытка крутилки. Покупка — выбор товара и кнопка
«Купить» на экране с ценой. Ничего из магазина нельзя обменять обратно на
фишки или звёзды.

Звание в чате — это подпись администратора, которую Telegram показывает рядом
с именем. Бот назначает игрока админом только с правом приглашать по ссылке
и снимает права, когда срок вышел. Для этого боту нужно право назначать
админов в чате.
"""

import asyncio
import logging
import time
from datetime import datetime
from html import escape

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import tournament as tour
from .config import Config
from .db import DB
from .i18n import t, variants

log = logging.getLogger(__name__)

TITLE_MAX = 16  # ограничение Telegram на подпись админа
TITLE_ALLOWED_PUNCT = " -_.!?'"
CUSTOM_TITLE_WAIT = 300  # сколько секунд ждём текст своего звания


def ready_titles() -> list[str]:
    return t("shop_titles").split("|")


def valid_title(text: str) -> bool:
    # Telegram не разрешает эмодзи в подписи админа; ссылки и упоминания не пускаем сами.
    text = text.strip()
    return (0 < len(text) <= TITLE_MAX and "@" not in text and "http" not in text.lower()
            and all(ch.isalnum() or ch in TITLE_ALLOWED_PUNCT for ch in text))


def _until(cfg: Config, ts: int) -> str:
    return datetime.fromtimestamp(ts, tour.zone(cfg.tournament_tz)).strftime("%d.%m %H:%M")


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")


async def shop_on(cfg: Config, db: DB) -> bool:
    return await db.get_state("shop_enabled", "1" if cfg.shop_enabled else "0") == "1"


async def owned_lines(cfg: Config, db: DB, user) -> list[str]:
    lines = []
    now = time.time()
    if user["badge"]:
        lines.append(t("shop_own_badge", badge=user["badge"]))
    main_chat = await db.get_state("main_chat")
    title = await db.get_title(int(main_chat), user["id"]) if main_chat else None
    if title:
        lines.append(t("shop_own_title", title=escape(title["title"]), until=_until(cfg, title["until"])))
    if user["vip_until"] > now:
        lines.append(t("shop_own_vip", until=_until(cfg, user["vip_until"])))
    if user["extra_spins"]:
        lines.append(t("shop_own_spins", n=user["extra_spins"]))
    return lines


async def menu(cfg: Config, db: DB, user) -> tuple[str, InlineKeyboardMarkup]:
    lines = [t("shop_title", balance=_fmt(user["balance"])), "",
             t("shop_item_badge", price=_fmt(cfg.shop_badge_price)),
             t("shop_item_title", price=_fmt(cfg.shop_title_price), custom=_fmt(cfg.shop_custom_title_price),
               days=cfg.shop_title_days),
             t("shop_item_vip", price=_fmt(cfg.shop_vip_price), days=cfg.shop_vip_days, max=_fmt(cfg.vip_max_bet)),
             t("shop_item_spin", price=_fmt(cfg.shop_spin_price))]
    owned = await owned_lines(cfg, db, user)
    if owned:
        lines += ["", t("shop_owned"), *owned]
    lines += ["", t("shop_footer")]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("shop_btn_badge", price=_fmt(cfg.shop_badge_price)), callback_data="shop:badge")],
        [InlineKeyboardButton(text=t("shop_btn_title", price=_fmt(cfg.shop_title_price)), callback_data="shop:title")],
        [InlineKeyboardButton(text=t("shop_btn_vip", price=_fmt(cfg.shop_vip_price)), callback_data="shop:q:vip")],
        [InlineKeyboardButton(text=t("shop_btn_spin", price=_fmt(cfg.shop_spin_price)), callback_data="shop:q:spin")],
    ])
    return "\n".join(lines), kb


def _back() -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=t("shop_back"), callback_data="shop:menu")]


def badge_menu(cfg: Config) -> tuple[str, InlineKeyboardMarkup]:
    badges = list(cfg.shop_badges)
    rows = [[InlineKeyboardButton(text=b, callback_data=f"shop:q:badge:{i}") for i, b in enumerate(badges[j:j + 4], j)]
            for j in range(0, len(badges), 4)]
    return t("shop_badge_pick", price=_fmt(cfg.shop_badge_price)), InlineKeyboardMarkup(inline_keyboard=[*rows, _back()])


def title_menu(cfg: Config) -> tuple[str, InlineKeyboardMarkup]:
    rows = [[InlineKeyboardButton(text=title, callback_data=f"shop:q:title:{i}")] for i, title in enumerate(ready_titles())]
    rows.append([InlineKeyboardButton(text=t("shop_btn_custom", price=_fmt(cfg.shop_custom_title_price)),
                                      callback_data="shop:custom")])
    text = t("shop_title_pick", price=_fmt(cfg.shop_title_price), days=cfg.shop_title_days)
    return text, InlineKeyboardMarkup(inline_keyboard=[*rows, _back()])


def describe(cfg: Config, item: str, arg: str | None) -> tuple[str, int]:
    """Название товара для экрана подтверждения и цена."""
    if item == "badge":
        return t("shop_name_badge", badge=cfg.shop_badges[int(arg)]), cfg.shop_badge_price
    if item == "title":
        return t("shop_name_title", title=ready_titles()[int(arg)], days=cfg.shop_title_days), cfg.shop_title_price
    if item == "ctitle":
        return t("shop_name_title", title=escape(arg), days=cfg.shop_title_days), cfg.shop_custom_title_price
    if item == "vip":
        return t("shop_name_vip", days=cfg.shop_vip_days), cfg.shop_vip_price
    return t("shop_name_spin"), cfg.shop_spin_price


def confirm(cfg: Config, user, item: str, arg: str | None) -> tuple[str, InlineKeyboardMarkup]:
    name, price = describe(cfg, item, arg)
    code = item if item in ("vip", "spin", "ctitle") else f"{item}:{arg}"
    text = t("shop_confirm", name=name, price=_fmt(price), balance=_fmt(user["balance"]))
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t("shop_buy", price=_fmt(price)), callback_data=f"shop:buy:{code}")], _back(),
    ])
    return text, kb


async def give_title(cfg: Config, db: DB, bot: Bot, user, title: str) -> str | None:
    """Назначает звание в основном чате. Возвращает текст ошибки или None."""
    main_chat = await db.get_state("main_chat")
    if not main_chat:
        return t("shop_err_no_chat")
    chat_id = int(main_chat)
    try:
        member = await bot.get_chat_member(chat_id, user["id"])
    except Exception:
        log.exception("get_chat_member failed")
        return t("shop_err_rights")
    ours = await db.get_title(chat_id, user["id"])
    if member.status in ("left", "kicked"):
        return t("shop_err_not_member")
    if member.status == "creator" or (member.status == "administrator" and not ours):
        return t("shop_err_admin")
    try:
        if member.status != "administrator":
            await bot.promote_chat_member(chat_id, user["id"], can_invite_users=True)
        await bot.set_chat_administrator_custom_title(chat_id, user["id"], title)
    except Exception:
        log.exception("promote for title failed")
        return t("shop_err_rights")
    start = max(ours["until"], int(time.time())) if ours else int(time.time())
    until = start + cfg.shop_title_days * 86400
    await db.set_title(chat_id, user["id"], title, until)
    try:
        await bot.send_message(chat_id, t("shop_title_news", name=escape(user["name"]), title=escape(title),
                                          days=cfg.shop_title_days))
    except Exception:
        log.exception("title announce failed")
    return None


async def loop(cfg: Config, db: DB, bot: Bot) -> None:
    """Снимает звания, срок которых вышел."""
    while True:
        try:
            for row in await db.expired_titles(int(time.time())):
                try:
                    member = await bot.get_chat_member(row["chat_id"], row["user_id"])
                    # Снимаем только то, что выдали сами: подпись совпадает с проданной.
                    if member.status == "administrator" and getattr(member, "custom_title", None) == row["title"]:
                        await bot.promote_chat_member(row["chat_id"], row["user_id"], can_invite_users=False)
                except Exception:
                    log.exception("failed to remove title")
                await db.delete_title(row["chat_id"], row["user_id"])
        except Exception:
            log.exception("shop loop failed")
        await asyncio.sleep(60)


def build_router(cfg: Config, db: DB, ensure_user) -> Router:
    router = Router()
    waiting_title: dict[int, float] = {}  # кто сейчас пишет своё звание и до какого времени ждём
    # Текст своего звания не влезает в данные кнопки — храним его до нажатия «Купить».
    custom_titles: dict[int, str] = {}

    async def show(target: Message, user, edit: bool = False) -> None:
        text, kb = await menu(cfg, db, user)
        await (target.edit_text(text, reply_markup=kb) if edit else target.answer(text, reply_markup=kb))

    @router.message(Command("shop"))
    @router.message(F.text.in_(variants("btn_shop")))
    async def cmd_shop(message: Message, bot: Bot) -> None:
        user = await ensure_user(message.from_user)
        if message.chat.type != ChatType.PRIVATE:
            me = await bot.me()
            await message.reply(t("shop_in_dm", bot=me.username))
            return
        if not await shop_on(cfg, db):
            await message.answer(t("shop_closed"))
            return
        await show(message, user)

    @router.message(F.chat.type == ChatType.PRIVATE, F.text,
                    F.from_user.id.func(lambda uid: waiting_title.get(uid, 0) > time.time()))
    async def on_custom_title(message: Message) -> None:
        waiting_title.pop(message.from_user.id, None)
        title = message.text.strip()
        if not valid_title(title):
            await message.answer(t("shop_title_bad", max=TITLE_MAX))
            return
        user = await ensure_user(message.from_user)
        text, kb = confirm(cfg, user, "ctitle", title)
        custom_titles[user["id"]] = title
        await message.answer(text, reply_markup=kb)

    @router.callback_query(F.data.startswith("shop:"))
    async def on_shop(query: CallbackQuery, bot: Bot) -> None:
        parts = query.data.split(":")
        user = await ensure_user(query.from_user)
        action = parts[1]
        if action == "menu":
            await query.answer()
            await show(query.message, user, edit=True)
        elif action == "badge":
            await query.answer()
            text, kb = badge_menu(cfg)
            await query.message.edit_text(text, reply_markup=kb)
        elif action == "title":
            await query.answer()
            text, kb = title_menu(cfg)
            await query.message.edit_text(text, reply_markup=kb)
        elif action == "custom":
            waiting_title[user["id"]] = time.time() + CUSTOM_TITLE_WAIT
            await query.answer()
            await query.message.answer(t("shop_title_ask", max=TITLE_MAX))
        elif action == "q":
            await query.answer()
            text, kb = confirm(cfg, user, parts[2], parts[3] if len(parts) > 3 else None)
            await query.message.edit_text(text, reply_markup=kb)
        elif action == "buy":
            await buy(query, bot, user, parts[2], parts[3] if len(parts) > 3 else None)

    async def buy(query: CallbackQuery, bot: Bot, user, item: str, arg: str | None) -> None:
        if not await shop_on(cfg, db):
            await query.answer(t("shop_closed"), show_alert=True)
            return
        if item == "ctitle":
            arg = custom_titles.pop(user["id"], None)
            if not arg:
                await query.answer(t("shop_title_again"), show_alert=True)
                return
        name, price = describe(cfg, item, arg)
        if not await db.spend(user["id"], price, f"{item}:{arg or ''}"):
            await query.answer(t("shop_no_chips", price=_fmt(price), balance=_fmt(user["balance"])), show_alert=True)
            return
        if item == "badge":
            await db.set_badge(user["id"], cfg.shop_badges[int(arg)])
        elif item == "vip":
            await db.extend_vip(user["id"], cfg.shop_vip_days * 86400)
        elif item == "spin":
            await db.add_extra_spin(user["id"])
        elif item in ("title", "ctitle"):
            title = ready_titles()[int(arg)] if item == "title" else arg
            error = await give_title(cfg, db, bot, user, title)
            if error:
                await db.refund_purchase(user["id"], price, f"{item}:{arg}")
                await query.answer(error, show_alert=True)
                return
        await query.answer(t("shop_bought", name=name), show_alert=True)
        await show(query.message, await db.get_user(user["id"]), edit=True)

    return router
