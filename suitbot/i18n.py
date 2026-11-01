"""Тексты для игроков на русском и узбекском (латиница).

Язык общий для всего бота: хранится в базе (state "lang") и переключается
в /admin. Панель админа не переводится — ею пользуется только владелец.
Тексты на узбекском лучше показать носителю языка и поправить здесь.
"""

LANGS = {"ru": "Русский", "uz": "O'zbekcha"}
LANG = "ru"
# В режиме пенальти тексты с ключом "<key>@pen" заменяют обычные.
GAME = "baccarat"


def set_lang(lang: str) -> None:
    global LANG
    LANG = lang if lang in LANGS else "ru"


def set_game(game: str) -> None:
    global GAME
    GAME = game


SUIT_KEYS = {"♠": "S", "♣": "C", "♥": "H", "♦": "D"}


def suit_label(suit: str) -> str:
    """Масть с названием: «♠ Пики» / «♠ Qarg'a»."""
    return f"{suit}{'\ufe0f'} {t(f'suit_{SUIT_KEYS[suit]}')}"


def t(key: str, **kwargs) -> str:
    if GAME == "penalty" and f"{key}@pen" in TEXTS:
        key = f"{key}@pen"
    ru, uz = TEXTS[key]
    text = uz if LANG == "uz" else ru
    return text.format(**kwargs) if kwargs else text


def variants(key: str) -> set[str]:
    """Текст на всех языках — чтобы кнопки старой клавиатуры работали после смены языка."""
    return set(TEXTS[key])


TEXTS: dict[str, tuple[str, str]] = {
    # --- кабинет и меню ---
    "btn_balance": ("💰 Мой баланс", "💰 Balansim"),
    "btn_bonus": ("🎁 Бонус", "🎁 Bonus"),
    "btn_rating": ("📊 Рейтинг", "📊 Reyting"),
    "btn_tournament": ("🏆 Турнир", "🏆 Turnir"),
    "btn_buy": ("⭐ Купить фишки", "⭐ Fishka sotib olish"),
    "btn_help": ("❓ Как играть", "❓ Qanday o'ynash"),
    "btn_spin": ("🎰 Крутить", "🎰 Aylantirish"),
    "unit_d": ("дн", "kun"),
    "unit_h": ("ч", "soat"),
    "unit_m": ("мин", "daq"),
    "welcome": (
        "👋 Привет! Это игра в прогнозы на масти. Кнопки внизу — ваш кабинет.",
        "👋 Salom! Bu kartalar masti bo'yicha bashorat o'yini. Pastdagi tugmalar — sizning kabinetingiz.",
    ),
    "cab_chips": ("💰 Фишки: <b>{balance}</b> · {rank} место в рейтинге",
                  "💰 Fishkalar: <b>{balance}</b> · reytingda {rank}-o'rin"),
    "cab_tour": ("🏆 Турнирные: <b>{balance}</b> · ставок {bets}/{min_bets}",
                 "🏆 Turnir fishkalari: <b>{balance}</b> · stavkalar {bets}/{min_bets}"),
    "cab_tour_join": ("🏆 Идёт турнир до {ends} — нажмите «{button}»",
                      "🏆 Turnir {ends} gacha davom etmoqda — «{button}» tugmasini bosing"),
    "cab_bonus_ready": ("🎁 Бонус: можно забрать!", "🎁 Bonus: olish mumkin!"),
    "cab_bonus_wait": ("🎁 Бонус: через {wait}", "🎁 Bonus: {wait} dan keyin"),
    "cab_spin_ready": ("🎰 Крутилка: можно крутить!", "🎰 Aylantirish: hozir mumkin!"),
    "cab_spin_wait": ("🎰 Крутилка: через {wait}", "🎰 Aylantirish: {wait} dan keyin"),
    "cab_duels": ("⚔️ Дуэли: побед {w} · поражений {l}", "⚔️ Duellar: g'alaba {w} · mag'lubiyat {l}"),
    "cab_duels_draws": (" · ничьих {d}", " · durrang {d}"),
    "cab_open_bets": ("\nОткрытые ставки:", "\nOchiq stavkalar:"),
    "id_info": ("Ваш id: <code>{user}</code>\nЭтот чат: <code>{chat}</code>",
                "Sizning id: <code>{user}</code>\nUshbu chat: <code>{chat}</code>"),

    # --- справка ---
    "help": (
        "<b>Как играть</b>\n\n"
        "В чате после каждой игры выходит карточка следующей игры с кнопками. "
        "Выберите сумму 💰 (и 🏆 Турнир, если идёт турнир), затем масть или исход. "
        "Ставки принимаются, пока идёт предыдущая игра, и закрываются, как только начинается игра карточки.\n\n"
        "<b>На что ставить:</b>\n"
        "♠️ ♣️ ♥️ ♦️ — эта масть будет в картах игрока, ×{suit}\n"
        "Игрок / Банкир — кто выиграет раздачу, ×{p} / ×{b}\n"
        "Ничья — ×{t}\n\n"
        "Можно и командой: <code>/bet 208 ♥ 50</code>, <code>/bet 208 игрок 50</code>, "
        "турнирная — <code>/tbet 208 ♥ 50</code>\n\n"
        "{duel_line}"
        "🎰 Раз в сутки — бесплатная крутилка в кабинете: 777 → +{jackpot} фишек.\n"
        "{bonus_line}\n"
        "Фишки — игровая валюта: их нельзя вывести или обменять на Stars.",
        "<b>Qanday o'ynash</b>\n\n"
        "Chatda har bir o'yindan keyin keyingi o'yin kartochkasi tugmalar bilan chiqadi. "
        "Summani 💰 tanlang (turnir bo'lsa — 🏆 Turnir ham), keyin mast yoki natijani bosing. "
        "Stavkalar oldingi o'yin davomida qabul qilinadi va kartochkadagi o'yin boshlanishi bilan yopiladi.\n\n"
        "<b>Nimaga tikish mumkin:</b>\n"
        "♠️ ♣️ ♥️ ♦️ — o'yinchi kartalarida shu mast bo'ladi, ×{suit}\n"
        "O'yinchi / Bankir — raundda kim yutadi, ×{p} / ×{b}\n"
        "Durrang — ×{t}\n\n"
        "Buyruq bilan ham bo'ladi: <code>/bet 208 ♥ 50</code>, <code>/bet 208 o'yinchi 50</code>, "
        "turnir uchun — <code>/tbet 208 ♥ 50</code>\n\n"
        "{duel_line}"
        "🎰 Kuniga bir marta — kabinetda bepul aylantirish: 777 → +{jackpot} fishka.\n"
        "{bonus_line}\n"
        "Fishkalar — o'yin valyutasi: ularni yechib olish yoki Stars'ga almashtirish mumkin emas.",
    ),
    "help_duel": (
        "⚔️ Дуэль: ответьте сопернику в чате <code>/duel 500</code> — на {options} игр, "
        "кто угадал больше масть игрока, забирает обе ставки.\n",
        "⚔️ Duel: chatda raqibingiz xabariga <code>/duel 500</code> deb javob bering — {options} o'yin, "
        "kim ko'proq mastni topsa, ikkala stavkani oladi.\n",
    ),
    "help_bonus": ("🎁 Бонус {amount} фишек {period}. Рейтинг — кнопка 📊 на карточке или в меню.",
                   "🎁 Bonus {amount} fishka {period}. Reyting — kartochkada yoki menyuda 📊 tugmasi."),
    "period_week": ("раз в неделю", "haftada bir marta"),
    "period_days": ("раз в {days} дн.", "{days} kunda bir marta"),

    # --- бонус и крутилка ---
    "bonus_wait": ("Бонус уже получен. Следующий через {wait}.", "Bonus allaqachon olingan. Keyingisi {wait} dan keyin."),
    "bonus_ok": ("🎁 +{amount} фишек! Баланс: {balance}", "🎁 +{amount} fishka! Balans: {balance}"),
    "spin_in_dm": ("Крутилка — в личке с ботом: @{bot}", "Aylantirish — bot bilan shaxsiy chatda: @{bot}"),
    "spin_wait": ("Сегодня уже крутили. Следующая попытка через {wait}.",
                  "Bugun allaqachon aylantirdingiz. Keyingi urinish {wait} dan keyin."),
    "spin_jackpot": ("🎉 ДЖЕКПОТ 7️⃣7️⃣7️⃣!", "🎉 JEKPOT 7️⃣7️⃣7️⃣!"),
    "spin_triple": ("🎉 Три {symbol}!", "🎉 Uchta {symbol}!"),
    "spin_double": ("👍 Две одинаковых!", "👍 Ikkita bir xil!"),
    "spin_miss": ("Не совпало, но держите утешительные", "Mos kelmadi, lekin mana tasalli sovg'asi"),
    "spin_result": ("{title} <b>+{prize} фишек</b>. Баланс: {balance}\nСледующая попытка — через сутки.",
                    "{title} <b>+{prize} fishka</b>. Balans: {balance}\nKeyingi urinish — bir kundan keyin."),

    # --- подписка ---
    "sub_prompt": ("Чтобы играть, подпишитесь на канал со статистикой — там выходят все игры.",
                   "O'ynash uchun statistika kanaliga obuna bo'ling — barcha o'yinlar o'sha yerda chiqadi."),
    "sub_btn": ("📢 Подписаться на канал", "📢 Kanalga obuna bo'lish"),
    "sub_done_btn": ("✅ Я подписался", "✅ Obuna bo'ldim"),
    "sub_alert": ("Чтобы играть, подпишитесь на канал {channel} и нажмите ещё раз.",
                  "O'ynash uchun {channel} kanaliga obuna bo'ling va yana bosing."),
    "sub_ok_alert": ("✅ Подписка есть — можно играть!", "✅ Obuna bor — o'ynashingiz mumkin!"),
    "sub_ok": ("✅ Подписка подтверждена. Удачной игры!", "✅ Obuna tasdiqlandi. Omad!"),
    "sub_missing": ("Подписка пока не видна. Подпишитесь и нажмите ещё раз.",
                    "Obuna hali ko'rinmayapti. Obuna bo'ling va yana bosing."),

    # --- ставки ---
    "side_P": ("игрок", "o'yinchi"),
    "side_B": ("банкир", "bankir"),
    "side_T": ("ничья", "durrang"),
    "bet_usage": ("Формат: <code>/{cmd} 208 ♥ 50</code> (номер игры, масть или игрок/банкир/ничья, сумма)",
                  "Format: <code>/{cmd} 208 ♥ 50</code> (o'yin raqami, mast yoki o'yinchi/bankir/durrang, summa)"),
    "bet_bad_pick": ("Не понял выбор. ", "Tanlov tushunarsiz. "),
    "bet_limits": ("Ставка от {min} до {max} фишек.", "Stavka {min} dan {max} fishkagacha."),
    "bet_limits_vip": (" С 💼 VIP из магазина — до {vip}.", " 🛒 Do'kondagi 💼 VIP bilan — {vip} gacha."),
    "bet_no_tour": ("Сейчас турнира нет.", "Hozir turnir yo'q."),
    "bet_no_games": ("Ещё не видел ни одного поста канала — подождите следующую игру.",
                     "Kanalda hali birorta post ko'rmadim — keyingi o'yinni kuting."),
    "bet_range": ("Последняя игра #N{last}. Ставки принимаются на #N{first}…#N{to}.",
                  "Oxirgi o'yin #N{last}. Stavkalar #N{first}…#N{to} ga qabul qilinadi."),
    "bet_started": ("Игра #N{game} уже началась, ставки закрыты.", "#N{game} o'yini boshlandi, stavkalar yopildi."),
    "bet_window": ("Приём ставок на #N{game} закрыт — ставьте на следующую игру.",
                   "#N{game} ga stavkalar yopildi — keyingi o'yinga tiking."),
    "bet_no_tour_chips": ("Недостаточно турнирных фишек: осталось {balance}. Турнирные фишки не докупаются.",
                          "Turnir fishkalari yetarli emas: {balance} qoldi. Turnir fishkalarini sotib olib bo'lmaydi."),
    "bet_no_chips": ("Недостаточно фишек: на балансе {balance}. /bonus или /buy",
                     "Fishkalar yetarli emas: balansda {balance}. /bonus yoki /buy"),
    "bet_ok": ("✅ Ставка принята: #N{game} · {pick} · {amount} ×{coef} (выигрыш {win}). Осталось {left} фишек",
               "✅ Stavka qabul qilindi: #N{game} · {pick} · {amount} ×{coef} (yutuq {win}). {left} fishka qoldi"),
    "bet_ok_tour": ("🏆 Турнирная ставка принята: #N{game} · {pick} · {amount} ×{coef} (выигрыш {win}). "
                    "Осталось {left} турнирных фишек",
                    "🏆 Turnir stavkasi qabul qilindi: #N{game} · {pick} · {amount} ×{coef} (yutuq {win}). "
                    "{left} turnir fishkasi qoldi"),
    "stake_set": ("Сумма ставки: {stake}", "Stavka summasi: {stake}"),
    "wallet_tour_set": ("Ставлю турнирными фишками 🏆", "Turnir fishkalari bilan tikaman 🏆"),
    "wallet_main_set": ("Ставлю обычными фишками", "Oddiy fishkalar bilan tikaman"),

    # --- карточка игры ---
    "card_open": ("ставки открыты", "stavkalar ochiq"),
    "card_closed": ("ставки закрыты", "stavkalar yopiq"),
    "card_title": ("🎴 <b>Игра #N{game}</b> — {status}", "🎴 <b>O'yin #N{game}</b> — {status}"),
    "card_odds": ("Масть в картах игрока ×{suit} · игрок/банкир ×{p} · ничья ×{t}",
                  "O'yinchi kartalarida mast ×{suit} · o'yinchi/bankir ×{p} · durrang ×{t}"),
    "card_counts": ("Ставок: {picks} | Игрок {P} · Банкир {B} · Ничья {T}",
                    "Stavkalar: {picks} | O'yinchi {P} · Bankir {B} · Durrang {T}"),
    "card_hint": ("Выберите сумму (запоминается), затем масть или исход.",
                  "Summani tanlang (eslab qolinadi), keyin mast yoki natijani."),
    "card_hint_tour": ("Выберите сумму и кошелёк (запоминается), затем масть или исход.",
                       "Summa va hamyonni tanlang (eslab qolinadi), keyin mast yoki natijani."),
    "card_btn_tour": ("🏆 Турнир", "🏆 Turnir"),
    "card_btn_main": ("Обычные фишки", "Oddiy fishkalar"),
    "card_btn_rating": ("📊 Рейтинг", "📊 Reyting"),
    "card_btn_duel": ("⚔️ Дуэль", "⚔️ Duel"),
    "card_btn_cabinet": ("👤 Кабинет", "👤 Kabinet"),

    # --- итоги игры ---
    "result_header": ("🎴 <b>#N{game}</b>: игрок {pp} ({pc}) — банкир {bp} ({bc})",
                      "🎴 <b>#N{game}</b>: o'yinchi {pp} ({pc}) — bankir {bp} ({bc})"),

    # --- рейтинг ---
    "rating_title": ("📊 Рейтинг", "📊 Reyting"),
    "rating_title_tour": ("🏆 Турнир", "🏆 Turnir"),
    "rating_empty": ("{title}: пока никого нет.", "{title}: hozircha hech kim yo'q."),
    "rating_top": ("{title} · топ {n}", "{title} · top {n}"),
    "rating_me": ("Вы: {place} место · {balance}", "Siz: {place}-o'rin · {balance}"),
    "rating_me_full": ("\nВы: <b>{place} место</b> · {balance} фишек", "\nSiz: <b>{place}-o'rin</b> · {balance} fishka"),
    "rating_not_in_tour": ("Вы не в турнире: /tournament", "Siz turnirda emassiz: /tournament"),
    "rating_not_in_tour_full": ("\nВы ещё не в турнире — вступайте: /tournament",
                                "\nSiz hali turnirda emassiz — qo'shiling: /tournament"),
    "rating_first_bet": ("Сделайте первую ставку, чтобы попасть в рейтинг",
                         "Reytingga tushish uchun birinchi stavkani qiling"),

    # --- турнир ---
    "tour_none": ("Сейчас турнира нет. Следите за объявлениями в чате!",
                  "Hozir turnir yo'q. Chatdagi e'lonlarni kuzatib boring!"),
    "tour_title": ("🏆 <b>Турнир</b> · до {ends}", "🏆 <b>Turnir</b> · {ends} gacha"),
    "tour_joined": ("Вы в турнире! Выдано {chips} турнирных фишек.", "Siz turnirdasiz! {chips} turnir fishkasi berildi."),
    "tour_prizes": ("<b>Призы:</b>", "<b>Sovrinlar:</b>"),
    "tour_table": ("<b>Таблица:</b>", "<b>Jadval:</b>"),
    "tour_row": ("{mark} {name} — {balance} ({bets} ст.){note}", "{mark} {name} — {balance} ({bets} st.){note}"),
    "tour_not_eligible": (" · пока не в призах", " · hali sovrinlarda emas"),
    "tour_me": ("\nВы: {place} место · {balance} фишек · ставок {bets}/{min_bets}",
                "\nSiz: {place}-o'rin · {balance} fishka · stavkalar {bets}/{min_bets}"),
    "tour_rules": ("Каждому {chips} турнирных фишек, ставка до {max_bet}. "
                   "Побеждает тот, у кого к концу турнира больше всего турнирных фишек. "
                   "Их нельзя купить — у всех равные шансы.\n"
                   "Для приза нужно сделать минимум {min_bets} ставок",
                   "Har kimga {chips} turnir fishkasi, stavka {max_bet} gacha. "
                   "Turnir oxirida eng ko'p turnir fishkasiga ega bo'lgan g'olib bo'ladi. "
                   "Ularni sotib olib bo'lmaydi — hammada imkoniyat teng.\n"
                   "Sovrin uchun kamida {min_bets} ta stavka qilish kerak"),
    "tour_rules_days": (" и быть в боте не меньше {days} дн.", " va botda kamida {days} kun bo'lish"),
    "tour_start": ("🏆 <b>Турнир начался!</b> До {ends}.\n\n{rules}\n\n<b>Призы:</b>\n{prizes}\n\n"
                   "Ставьте кнопками под карточкой игры (выберите «🏆 Турнир») или командой "
                   "<code>/tbet 209 ♥ 50</code>. Таблица: /tournament",
                   "🏆 <b>Turnir boshlandi!</b> {ends} gacha.\n\n{rules}\n\n<b>Sovrinlar:</b>\n{prizes}\n\n"
                   "O'yin kartochkasidagi tugmalar bilan tiking («🏆 Turnir» ni tanlang) yoki "
                   "<code>/tbet 209 ♥ 50</code> buyrug'i bilan. Jadval: /tournament"),
    "tour_over_none": ("🏁 <b>Турнир окончен.</b> В этот раз никто не выполнил условия для приза.",
                       "🏁 <b>Turnir tugadi.</b> Bu safar hech kim sovrin shartlarini bajarmadi."),
    "tour_over": ("🏁 <b>Турнир окончен!</b>\n", "🏁 <b>Turnir tugadi!</b>\n"),
    "tour_over_footer": ("\nПоздравляем! Призы отправит администратор.", "\nTabriklaymiz! Sovrinlarni administrator yuboradi."),
    "btn_join": ("▶️ Начать играть", "▶️ O'ynashni boshlash"),

    # --- покупка ---
    "buy_in_dm": ("Покупка — в личке: @{bot}", "Sotib olish — shaxsiy chatda: @{bot}"),
    "buy_pack": ("⭐ {stars} → {chips} фишек", "⭐ {stars} → {chips} fishka"),
    "buy_choose": ("Выберите пакет фишек:", "Fishkalar paketini tanlang:"),
    "buy_title": ("{chips} фишек", "{chips} fishka"),
    "buy_desc": ("{chips} игровых фишек для прогнозов. Фишки не выводятся и не обмениваются на Stars.",
                 "Bashoratlar uchun {chips} o'yin fishkasi. Fishkalarni yechib olib yoki Stars'ga almashtirib bo'lmaydi."),
    "buy_bad": ("Неверный счёт, попробуйте ещё раз.", "Noto'g'ri hisob, qayta urinib ko'ring."),
    "buy_ok": ("⭐ Оплата получена: +{chips} фишек. Баланс: {balance}", "⭐ To'lov qabul qilindi: +{chips} fishka. Balans: {balance}"),
    "paysupport": ("По вопросам оплаты напишите {contact}. Укажите дату покупки — возврат Stars делается вручную.",
                   "To'lov bo'yicha savollar uchun {contact} ga yozing. Xarid sanasini ko'rsating — Stars qaytarish qo'lda amalga oshiriladi."),
    "paysupport_default": ("администратору бота", "bot administratoriga"),

    # --- дуэли ---
    "duel_how": ("Ответьте на сообщение соперника командой <code>/duel 500</code> — бот вызовет его на дуэль. "
                 "Число игр можно указать сразу: <code>/duel 500 3</code>, или выбрать кнопками в вызове. "
                 "Без ответа вызов открытый: принять может любой.",
                 "Raqibingiz xabariga <code>/duel 500</code> deb javob bering — bot uni duelga chaqiradi. "
                 "O'yinlar sonini darhol ko'rsatish mumkin: <code>/duel 500 3</code> yoki chaqiruvdagi tugmalar bilan tanlang. "
                 "Javobsiz chaqiruv ochiq bo'ladi: istalgan kishi qabul qilishi mumkin."),
    "duel_help_alert": ("Чтобы вызвать соперника, ответьте на его сообщение: /duel 500. Без ответа — открытый вызов для всех.",
                        "Raqibni chaqirish uchun uning xabariga javob bering: /duel 500. Javobsiz — hamma uchun ochiq chaqiruv."),
    "duel_off": ("Дуэли сейчас выключены.", "Duellar hozir o'chirilgan."),
    "duel_in_chat": ("Дуэли проходят в общем чате. ", "Duellar umumiy chatda o'tadi. "),
    "duel_games_allowed": ("Число игр в дуэли: {options}.", "Dueldagi o'yinlar soni: {options}."),
    "duel_stake_limits": ("Ставка в дуэли — от {min} до {max} фишек.", "Duel stavkasi — {min} dan {max} fishkagacha."),
    "duel_no_chips": ("Недостаточно фишек: на балансе {balance}.", "Fishkalar yetarli emas: balansda {balance}."),
    "duel_busy_self": ("У вас уже есть вызов или идёт дуэль — дождитесь её конца.",
                       "Sizda allaqachon chaqiruv yoki duel bor — tugashini kuting."),
    "duel_busy_other": ("{name} уже участвует в дуэли.", "{name} allaqachon duelda qatnashmoqda."),
    "duel_anyone": ("любого желающего", "istalgan o'yinchini"),
    "duel_challenge": ("⚔️ <b>{c}</b> вызывает <b>{o}</b> на дуэль!\nСтавка {stake} фишек · {games} · угадываем масть игрока",
                       "⚔️ <b>{c}</b> <b>{o}</b> ni duelga chaqiradi!\nStavka {stake} fishka · {games} · o'yinchi mastini topamiz"),
    "duel_pending": ("\n⏳ Вызов действует {minutes} мин. Число игр выбирает {c}.",
                     "\n⏳ Chaqiruv {minutes} daqiqa amal qiladi. O'yinlar sonini {c} tanlaydi."),
    "duel_btn_accept": ("⚔️ Принять", "⚔️ Qabul qilish"),
    "duel_btn_decline": ("Отказаться", "Rad etish"),
    "duel_declined": ("\n❌ Вызов отклонён.", "\n❌ Chaqiruv rad etildi."),
    "duel_expired": ("\n⌛ Вызов никто не принял.", "\n⌛ Chaqiruvni hech kim qabul qilmadi."),
    "duel_board": ("⚔️ <b>{c} vs {o}</b> · ставка {stake} · счёт <b>{sc} : {so}</b>",
                   "⚔️ <b>{c} vs {o}</b> · stavka {stake} · hisob <b>{sc} : {so}</b>"),
    "duel_live": ("#N{game}: игра идёт — {c} {cp} · {o} {op}", "#N{game}: o'yin ketmoqda — {c} {cp} · {o} {op}"),
    "duel_picked": ("✅ выбрал", "✅ tanladi"),
    "duel_thinking": ("⏳ думает", "⏳ o'ylamoqda"),
    "duel_draw": ("\n🤝 <b>Ничья {sc} : {so}</b> — ставки возвращены.", "\n🤝 <b>Durrang {sc} : {so}</b> — stavkalar qaytarildi."),
    "duel_won": ("\n🏆 <b>{winner} победил {a} : {b}</b> и забирает {pot} фишек!",
                 "\n🏆 <b>{winner} {a} : {b} hisobida g'olib</b> va {pot} fishkani oladi!"),
    "duel_left": ("\nОсталось игр: {left}. Выбор соперника скрыт до начала игры.",
                  "\nQolgan o'yinlar: {left}. Raqibning tanlovi o'yin boshlanguncha yashirin."),
    "duel_result_draw": ("🤝 Дуэль {c} vs {o}: ничья {sc} : {so}.", "🤝 Duel {c} vs {o}: durrang {sc} : {so}."),
    "duel_result_won": ("🏆 <b>{name}</b> побеждает в дуэли {a} : {b} и забирает {pot} фишек!",
                        "🏆 <b>{name}</b> duelda {a} : {b} hisobida g'olib bo'ldi va {pot} fishkani oladi!"),
    "duel_stale": ("Вызов уже неактуален.", "Chaqiruv endi amal qilmaydi."),
    "duel_len_owner": ("Число игр выбирает тот, кто вызвал.", "O'yinlar sonini chaqirgan kishi tanlaydi."),
    "duel_len_set": ("Дуэль: {games}", "Duel: {games}"),
    "duel_changed": ("Условия изменились: теперь {games}. Посмотрите и нажмите ещё раз.",
                     "Shartlar o'zgardi: endi {games}. Ko'rib chiqing va yana bosing."),
    "duel_own": ("Нельзя принять свой же вызов.", "O'z chaqiruvingizni qabul qila olmaysiz."),
    "duel_not_you": ("Этот вызов не вам.", "Bu chaqiruv sizga emas."),
    "duel_busy_alert": ("У вас уже есть вызов или идёт дуэль.", "Sizda allaqachon chaqiruv yoki duel bor."),
    "duel_wait_post": ("Подождите первый пост канала.", "Kanalning birinchi postini kuting."),
    "duel_no_funds": ("Не хватает фишек: нужно {stake} у обоих.", "Fishkalar yetarli emas: ikkalasida ham {stake} kerak."),
    "duel_started": ("⚔️ Дуэль началась! Выбирайте масть на ближайшую игру.", "⚔️ Duel boshlandi! Eng yaqin o'yin uchun mastni tanlang."),
    "duel_decline_who": ("Отказаться может только тот, кого вызвали.", "Faqat chaqirilgan kishi rad etishi mumkin."),
    "duel_cancelled": ("Вызов отменён.", "Chaqiruv bekor qilindi."),
    "duel_over": ("Дуэль уже закончилась.", "Duel allaqachon tugagan."),
    "duel_foreign": ("Это чужая дуэль — вызовите кого-нибудь сами: /duel 500", "Bu boshqalarning dueli — o'zingiz kimnidir chaqiring: /duel 500"),
    "duel_pick_late": ("Игра #N{game} уже началась — выбирайте на следующую.", "#N{game} o'yini boshlandi — keyingisiga tanlang."),
    "duel_pick_ok": ("Вы выбрали {suit} на #N{game} — соперник не видит до начала игры.",
                     "Siz #N{game} uchun {suit} ni tanladingiz — raqib o'yin boshlanguncha ko'rmaydi."),
    "duel_news": ("⚔️ <b>Новинка: дуэли!</b>\n\n"
                  "Вызовите любого игрока чата один на один:\n"
                  "1. Ответьте на его сообщение командой <code>/duel 500</code> (ставка от {min} до {max} фишек). "
                  "Без ответа — открытый вызов, принять может любой.\n"
                  "2. Соперник жмёт «⚔️ Принять» — у обоих замораживается ставка.\n"
                  "3. Вызывающий выбирает длину: {options} игр. Каждую игру оба выбирают масть игрока кнопками под дуэлью. "
                  "Выбор соперника скрыт до начала игры.\n"
                  "4. Кто угадал больше — забирает обе ставки. Ничья — ставки возвращаются.\n\n"
                  "Дуэли — на обычных фишках, турнир они не трогают. Удачи! 🍀",
                  "⚔️ <b>Yangilik: duellar!</b>\n\n"
                  "Chatdagi istalgan o'yinchini yakkama-yakka chaqiring:\n"
                  "1. Uning xabariga <code>/duel 500</code> deb javob bering (stavka {min} dan {max} fishkagacha). "
                  "Javobsiz — ochiq chaqiruv, istalgan kishi qabul qilishi mumkin.\n"
                  "2. Raqib «⚔️ Qabul qilish» ni bosadi — ikkalasining stavkasi muzlatiladi.\n"
                  "3. Chaqiruvchi davomiylikni tanlaydi: {options} o'yin. Har o'yinda ikkalasi duel ostidagi tugmalar bilan "
                  "o'yinchi mastini tanlaydi. Raqibning tanlovi o'yin boshlanguncha yashirin.\n"
                  "4. Kim ko'proq topsa — ikkala stavkani oladi. Durrangda stavkalar qaytariladi.\n\n"
                  "Duellar oddiy fishkalarda o'tadi, turnirga ta'sir qilmaydi. Omad! 🍀"),

    # --- объявления в чат ---
    "invite": ("🎴 <b>Прогнозы на масти — игра в чате</b>\n\n"
               "Угадывайте масть в картах игрока и победителя раздачи, копите фишки и поднимайтесь в топ.\n\n"
               "<b>Как начать:</b>\n"
               "1. Нажмите «Начать играть» и затем «Старт» — сразу получите {start} фишек "
               "и кабинет с кнопками: баланс, бонус, рейтинг, турнир.\n"
               "2. После каждой игры здесь выходит карточка следующей игры — выберите сумму и масть. "
               "Ставки принимаются, пока идёт предыдущая игра.\n"
               "3. Забирайте бонус {bonus} фишек раз в {days} дн. и следите за рейтингом 📊.\n",
               "🎴 <b>Mastlar bo'yicha bashorat — chatdagi o'yin</b>\n\n"
               "O'yinchi kartalaridagi mastni va raund g'olibini toping, fishka to'plang va topga chiqing.\n\n"
               "<b>Qanday boshlash:</b>\n"
               "1. «O'ynashni boshlash» va keyin «Start» ni bosing — darhol {start} fishka "
               "va tugmali kabinet olasiz: balans, bonus, reyting, turnir.\n"
               "2. Har o'yindan keyin bu yerda keyingi o'yin kartochkasi chiqadi — summa va mastni tanlang. "
               "Stavkalar oldingi o'yin davomida qabul qilinadi.\n"
               "3. Har {days} kunda {bonus} fishka bonus oling va reytingni kuzating 📊.\n"),
    "invite_tour": ("\n🏆 <b>Идёт турнир</b> до {ends}. Призы:\n{prizes}\nУчастие бесплатное: /tournament\n",
                    "\n🏆 <b>Turnir davom etmoqda</b> {ends} gacha. Sovrinlar:\n{prizes}\nQatnashish bepul: /tournament\n"),
    "invite_footer": ("\nФишки — игровая валюта, их нельзя вывести.", "\nFishkalar — o'yin valyutasi, ularni yechib olib bo'lmaydi."),
    "gift_all": ("🎁 <b>Подарок от админа!</b> Всем +{amount} фишек. Удачи в прогнозах!",
                 "🎁 <b>Admindan sovg'a!</b> Hammaga +{amount} fishka. Bashoratlarda omad!"),
    # --- актив недели и раздачи ---
    "btn_active": ("🔥 Актив", "🔥 Faollik"),
    "cab_active": ("🔥 Актив недели: {points} очков · {place} место", "🔥 Hafta faolligi: {points} ochko · {place}-o'rin"),
    "active_title": ("🔥 <b>Актив недели</b> · до {ends}", "🔥 <b>Hafta faolligi</b> · {ends} gacha"),
    "active_rules": ("Очки: сообщение в чате от {words} слов — 1 (не чаще раза в минуту), ответ другому — ещё 1, "
                     "ставка — 1, дуэль — 3. Для приза нужно минимум {min} очков.",
                     "Ochkolar: chatda {words} so'zdan iborat xabar — 1 (daqiqada bir martadan ko'p emas), "
                     "boshqaga javob — yana 1, stavka — 1, duel — 3. Sovrin uchun kamida {min} ochko kerak."),
    "active_empty": ("Пока никто не набрал очков — будьте первым!", "Hozircha hech kim ochko to'plamadi — birinchi bo'ling!"),
    "active_me": ("Вы: <b>{place} место</b> · {points} очков", "Siz: <b>{place}-o'rin</b> · {points} ochko"),
    "active_me_none": ("У вас пока нет очков на этой неделе.", "Bu hafta sizda hali ochko yo'q."),
    "active_over": ("🔥 <b>Актив недели — итоги!</b>\n", "🔥 <b>Hafta faolligi — natijalar!</b>\n"),
    "active_over_footer": ("\nСпасибо, что вы с нами! Призы отправит администратор. Новая неделя уже началась.",
                           "\nBiz bilan ekaningiz uchun rahmat! Sovrinlarni administrator yuboradi. Yangi hafta boshlandi."),
    "active_over_none": ("🔥 Актив недели окончен: никто не набрал {min} очков. Новая неделя уже началась!",
                         "🔥 Hafta faolligi tugadi: hech kim {min} ochko to'plamadi. Yangi hafta boshlandi!"),
    "help_active": ("🔥 Актив недели: очки за сообщения, ставки и дуэли — лучшим призы. Таблица: /active\n",
                    "🔥 Hafta faolligi: xabarlar, stavkalar va duellar uchun ochkolar — eng faollarga sovrin. Jadval: /active\n"),
    "drop_post": ("🎁 <b>Раздача!</b> Первые {n}, кто нажмёт кнопку, получат по {amount} фишек!",
                  "🎁 <b>Tarqatish!</b> Tugmani birinchi bosgan {n} kishi {amount} fishkadan oladi!"),
    "drop_post_stars": ("⭐ <b>Звёздная раздача!</b> Первый, кто нажмёт кнопку, получит {prize} от администратора!",
                        "⭐ <b>Yulduzli tarqatish!</b> Tugmani birinchi bosgan kishi administratordan {prize} oladi!"),
    "drop_btn": ("🎁 Забрать", "🎁 Olish"),
    "drop_winners": ("Успели: {names}", "Ulgurdi: {names}"),
    "drop_over": ("Раздача окончена — следите за чатом, следующая будет внезапно!",
                  "Tarqatish tugadi — chatni kuzating, keyingisi kutilmaganda bo'ladi!"),
    "drop_ok": ("🎉 Успели! +{amount} фишек. Баланс: {balance}", "🎉 Ulgurdingiz! +{amount} fishka. Balans: {balance}"),
    "drop_ok_stars": ("🎉 Вы первый! {prize} отправит администратор.", "🎉 Siz birinchisiz! {prize} ni administrator yuboradi."),
    "drop_again": ("Вы уже забрали эту раздачу.", "Siz bu tarqatishni allaqachon oldingiz."),
    "drop_late": ("Не успели — раздача уже закончилась. В следующий раз повезёт!",
                  "Ulgurmadingiz — tarqatish tugadi. Keyingi safar omad kulib boqadi!"),

    # --- магазин ---
    "btn_shop": ("🛒 Магазин", "🛒 Do'kon"),
    "shop_in_dm": ("Магазин — в личке с ботом: @{bot}", "Do'kon — bot bilan shaxsiy chatda: @{bot}"),
    "shop_closed": ("Магазин сейчас закрыт.", "Do'kon hozir yopiq."),
    "shop_title": ("🛒 <b>Магазин</b> · у вас {balance} фишек", "🛒 <b>Do'kon</b> · sizda {balance} fishka"),
    "shop_item_badge": ("✨ <b>Значок</b> у имени во всех сообщениях бота — {price}, навсегда",
                        "✨ <b>Belgi</b> — botning barcha xabarlarida ismingiz yonida — {price}, abadiy"),
    "shop_item_title": ("🏷 <b>Звание в чате</b> рядом с именем — {price} (своё — {custom}), на {days} дн.",
                        "🏷 <b>Chatdagi unvon</b> ismingiz yonida — {price} (o'zingizniki — {custom}), {days} kunga"),
    "shop_item_vip": ("💼 <b>VIP</b> — ставки до {max} — {price}, на {days} дн.",
                      "💼 <b>VIP</b> — {max} gacha stavkalar — {price}, {days} kunga"),
    "shop_item_spin": ("🎰 <b>Лишняя попытка крутилки</b> — {price}", "🎰 <b>Qo'shimcha aylantirish</b> — {price}"),
    "shop_owned": ("<b>У вас есть:</b>", "<b>Sizda bor:</b>"),
    "shop_own_badge": ("✨ значок {badge}", "✨ belgi {badge}"),
    "shop_own_title": ("🏷 звание «{title}» до {until}", "🏷 «{title}» unvoni {until} gacha"),
    "shop_own_vip": ("💼 VIP до {until}", "💼 VIP {until} gacha"),
    "shop_own_spins": ("🎰 лишних попыток: {n}", "🎰 qo'shimcha urinishlar: {n}"),
    "shop_footer": ("Покупки нельзя вернуть или обменять на фишки и звёзды.",
                    "Xaridlarni qaytarib yoki fishka va yulduzlarga almashtirib bo'lmaydi."),
    "shop_btn_badge": ("✨ Значок · {price}", "✨ Belgi · {price}"),
    "shop_btn_title": ("🏷 Звание в чате · {price}", "🏷 Chatdagi unvon · {price}"),
    "shop_btn_vip": ("💼 VIP · {price}", "💼 VIP · {price}"),
    "shop_btn_spin": ("🎰 Попытка крутилки · {price}", "🎰 Aylantirish · {price}"),
    "shop_btn_custom": ("✍️ Своё звание · {price}", "✍️ O'z unvoningiz · {price}"),
    "shop_back": ("← Назад", "← Orqaga"),
    "shop_badge_pick": ("✨ Выберите значок — {price} фишек. Он будет рядом с вашим именем в итогах игр, рейтинге, дуэлях.",
                        "✨ Belgini tanlang — {price} fishka. U o'yin natijalari, reyting va duellarda ismingiz yonida bo'ladi."),
    "shop_title_pick": ("🏷 Выберите звание — {price} фишек на {days} дн. Telegram покажет его рядом с вашим именем в чате.",
                        "🏷 Unvonni tanlang — {price} fishka, {days} kunga. Telegram uni chatda ismingiz yonida ko'rsatadi."),
    "shop_titles": ("Прогнозист|Хайроллер|Снайпер|Везунчик|Король масти",
                    "Bashoratchi|Xayroller|Mergan|Omadli|Mast qiroli"),
    "shop_titles@pen": ("Прогнозист|Хайроллер|Снайпер|Везунчик|Король пенальти",
                        "Bashoratchi|Xayroller|Mergan|Omadli|Penalti qiroli"),
    "shop_title_ask": ("✍️ Напишите своё звание одним сообщением: до {max} символов, только буквы, цифры и пробелы "
                       "(эмодзи Telegram в званиях не разрешает).",
                       "✍️ Unvoningizni bitta xabarda yozing: {max} belgigacha, faqat harflar, raqamlar va bo'shliqlar "
                       "(Telegram unvonlarda emojiga ruxsat bermaydi)."),
    "shop_title_bad": ("Такое звание не подойдёт: до {max} символов, без эмодзи, ссылок и @. Нажмите «Своё звание» ещё раз.",
                       "Bunday unvon mos emas: {max} belgigacha, emoji, havola va @ siz. «O'z unvoningiz» ni yana bosing."),
    "shop_title_again": ("Напишите текст звания ещё раз: нажмите «Своё звание».", "Unvon matnini qayta yozing: «O'z unvoningiz» ni bosing."),
    "shop_name_badge": ("значок {badge}", "{badge} belgisi"),
    "shop_name_title": ("звание «{title}» на {days} дн.", "«{title}» unvoni, {days} kunga"),
    "shop_name_vip": ("VIP на {days} дн.", "VIP, {days} kunga"),
    "shop_name_spin": ("попытку крутилки", "aylantirish urinishi"),
    "shop_confirm": ("Купить {name} за {price} фишек?\nНа балансе: {balance}", "{name} ni {price} fishkaga sotib olasizmi?\nBalansda: {balance}"),
    "shop_buy": ("✅ Купить за {price}", "✅ {price} ga sotib olish"),
    "shop_no_chips": ("Не хватает фишек: нужно {price}, у вас {balance}. Пополнить — «⭐ Купить фишки».",
                      "Fishkalar yetarli emas: {price} kerak, sizda {balance}. To'ldirish — «⭐ Fishka sotib olish»."),
    "shop_bought": ("🎉 Готово: {name}!", "🎉 Tayyor: {name}!"),
    "shop_err_no_chat": ("Чат ещё не настроен — звания пока недоступны. Фишки не списаны.",
                         "Chat hali sozlanmagan — unvonlar hozircha mavjud emas. Fishkalar yechilmadi."),
    "shop_err_not_member": ("Сначала вступите в чат — звание выдаётся там. Фишки не списаны.",
                            "Avval chatga qo'shiling — unvon o'sha yerda beriladi. Fishkalar yechilmadi."),
    "shop_err_admin": ("Вы уже администратор чата — звание через магазин выдать нельзя. Фишки не списаны.",
                       "Siz allaqachon chat administratorisiz — do'kon orqali unvon berib bo'lmaydi. Fishkalar yechilmadi."),
    "shop_err_rights": ("Не получилось выдать звание: у бота нет права назначать админов. Фишки вернули.",
                        "Unvon berilmadi: botda adminlarni tayinlash huquqi yo'q. Fishkalar qaytarildi."),
    "shop_open_btn": ("🛒 Открыть магазин", "🛒 Do'konni ochish"),
    "shop_news": ("🛒 <b>Открылся магазин за фишки!</b>\n\n"
                  "Выигранные фишки теперь можно потратить:\n"
                  "✨ <b>Значок</b> у имени во всех сообщениях бота — {badge}, навсегда\n"
                  "🏷 <b>Звание в чате</b> рядом с именем, как у админов — {title} (своё — {custom}), на {days} дн.\n"
                  "💼 <b>VIP</b> — ставки до {vip_max} — {vip}, на {vip_days} дн.\n"
                  "🎰 <b>Лишняя попытка крутилки</b> — {spin}\n\n"
                  "Магазин — в личке с ботом, кнопка «🛒 Магазин». Играйте, копите и покупайте! 🍀",
                  "🛒 <b>Fishka do'koni ochildi!</b>\n\n"
                  "Yutgan fishkalaringizni endi sarflash mumkin:\n"
                  "✨ <b>Belgi</b> — botning barcha xabarlarida ismingiz yonida — {badge}, abadiy\n"
                  "🏷 <b>Chatdagi unvon</b> — adminlardek ismingiz yonida — {title} (o'zingizniki — {custom}), {days} kunga\n"
                  "💼 <b>VIP</b> — {vip_max} gacha stavkalar — {vip}, {vip_days} kunga\n"
                  "🎰 <b>Qo'shimcha aylantirish</b> — {spin}\n\n"
                  "Do'kon — bot bilan shaxsiy chatda, «🛒 Do'kon» tugmasi. O'ynang, to'plang va xarid qiling! 🍀"),
    "invite_shop": ("4. Тратьте фишки в 🛒 магазине: значок у имени, звание в чате, VIP.\n",
                    "4. Fishkalarni 🛒 do'konda sarflang: ism yonidagi belgi, chatdagi unvon, VIP.\n"),
    "help_shop": ("🛒 Магазин в кабинете: значок у имени — {badge}, звание в чате — {title}, VIP — {vip} фишек.\n",
                  "🛒 Kabinetdagi do'kon: ism yonidagi belgi — {badge}, chatdagi unvon — {title}, VIP — {vip} fishka.\n"),
    "shop_title_news": ("🏷 Новое звание в чате: {name} — «{title}» на {days} дн.! Магазин — в личке с ботом.",
                        "🏷 {name} yangi «{title}» unvonini {days} kunga oldi! Do'kon — bot bilan shaxsiy chatda."),

    # --- названия мастей ---
    "suit_S": ("Пики", "Qarg'a"),
    "suit_C": ("Крести", "Chillak"),
    "suit_H": ("Черви", "Chirvo"),
    "suit_D": ("Буби", "G'isht"),

    # --- меню команд «/» ---
    "cmd_spades": ("♠️ Пики у игрока — ставка на ближайшую игру", "♠️ Qarg'a o'yinchida — eng yaqin o'yinga stavka"),
    "cmd_clubs": ("♣️ Крести у игрока — ставка на ближайшую игру", "♣️ Chillak o'yinchida — eng yaqin o'yinga stavka"),
    "cmd_hearts": ("♥️ Черви у игрока — ставка на ближайшую игру", "♥️ Chirvo o'yinchida — eng yaqin o'yinga stavka"),
    "cmd_diamonds": ("♦️ Буби у игрока — ставка на ближайшую игру", "♦️ G'isht o'yinchida — eng yaqin o'yinga stavka"),
    "cmd_player": ("Победа игрока — ставка на ближайшую игру", "O'yinchi g'alabasi — eng yaqin o'yinga stavka"),
    "cmd_banker": ("Победа банкира — ставка на ближайшую игру", "Bankir g'alabasi — eng yaqin o'yinga stavka"),
    "cmd_tie": ("Ничья — ставка на ближайшую игру", "Durrang — eng yaqin o'yinga stavka"),
    "cmd_p1": ("П1 — победа первой команды в ближайшей серии", "P1 — eng yaqin seriyada birinchi jamoa g'alabasi"),
    "cmd_p2": ("П2 — победа второй команды в ближайшей серии", "P2 — eng yaqin seriyada ikkinchi jamoa g'alabasi"),
    "cmd_over": ("ТБ — тотал больше в ближайшей серии", "TB — eng yaqin seriyada total ko'p"),
    "cmd_under": ("ТМ — тотал меньше в ближайшей серии", "TM — eng yaqin seriyada total kam"),
    "cmd_duel": ("⚔️ Дуэль: ответьте сопернику /duel 500", "⚔️ Duel: raqibga /duel 500 deb javob bering"),
    "cmd_top": ("📊 Рейтинг игроков", "📊 O'yinchilar reytingi"),
    "cmd_start": ("Начать играть / кабинет", "O'ynashni boshlash / kabinet"),
    "cmd_balance": ("💰 Мой баланс", "💰 Balansim"),
    "cmd_shop": ("🛒 Магазин", "🛒 Do'kon"),
    "cmd_bonus": ("🎁 Бонус", "🎁 Bonus"),
    "cmd_spin": ("🎰 Крутилка", "🎰 Aylantirish"),
    "cmd_tournament": ("🏆 Турнир", "🏆 Turnir"),
    "cmd_active": ("🔥 Актив недели", "🔥 Hafta faolligi"),
    "cmd_help": ("❓ Как играть", "❓ Qanday o'ynash"),

    # --- режим пенальти ---
    "welcome@pen": (
        "👋 Привет! Это игра в прогнозы на серии пенальти. Кнопки внизу — ваш кабинет.",
        "👋 Salom! Bu penalti seriyalari bo'yicha bashorat o'yini. Pastdagi tugmalar — sizning kabinetingiz.",
    ),
    "help@pen": (
        "<b>Как играть</b>\n\n"
        "Канал публикует серии пенальти на пару игр вперёд — бот сразу выкладывает в чат карточку каждой серии. "
        "Выберите сумму 💰 (и 🏆 Турнир, если идёт турнир), затем исход или тотал. "
        "Ставки принимаются, пока серия не началась.\n\n"
        "<b>На что ставить</b> (коэффициенты — из поста канала):\n"
        "П1 / П2 — какая команда выиграет серию\n"
        "ТБ / ТМ — голов в серии больше / меньше линии (например, 4.5)\n\n"
        "Можно и командой: <code>/bet 45 п1 50</code>, <code>/bet 45 тб 50</code>, "
        "турнирная — <code>/tbet 45 п2 50</code>\n\n"
        "{duel_line}"
        "🎰 Раз в сутки — бесплатная крутилка в кабинете: 777 → +{jackpot} фишек.\n"
        "{bonus_line}\n"
        "Фишки — игровая валюта: их нельзя вывести или обменять на Stars.",
        "<b>Qanday o'ynash</b>\n\n"
        "Kanal penalti seriyalarini bir necha o'yin oldin e'lon qiladi — bot darhol chatga har bir seriya kartochkasini chiqaradi. "
        "Summani 💰 tanlang (turnir bo'lsa — 🏆 Turnir ham), keyin natija yoki totalni bosing. "
        "Stavkalar seriya boshlanguncha qabul qilinadi.\n\n"
        "<b>Nimaga tikish mumkin</b> (koeffitsientlar — kanal postidan):\n"
        "P1 / P2 — qaysi jamoa seriyada yutadi\n"
        "TB / TM — seriyadagi gollar chiziqdan ko'p / kam (masalan, 4.5)\n\n"
        "Buyruq bilan ham bo'ladi: <code>/bet 45 p1 50</code>, <code>/bet 45 tb 50</code>, "
        "turnir uchun — <code>/tbet 45 p2 50</code>\n\n"
        "{duel_line}"
        "🎰 Kuniga bir marta — kabinetda bepul aylantirish: 777 → +{jackpot} fishka.\n"
        "{bonus_line}\n"
        "Fishkalar — o'yin valyutasi: ularni yechib olish yoki Stars'ga almashtirish mumkin emas.",
    ),
    "help_duel@pen": (
        "⚔️ Дуэль: ответьте сопернику в чате <code>/duel 500</code> — на {options} серий, "
        "кто чаще угадает победителя, забирает обе ставки.\n",
        "⚔️ Duel: chatda raqibingiz xabariga <code>/duel 500</code> deb javob bering — {options} seriya, "
        "kim g'olibni ko'proq topsa, ikkala stavkani oladi.\n",
    ),
    "bet_usage@pen": ("Формат: <code>/{cmd} 45 п1 50</code> (номер серии, п1/п2/тб/тм, сумма)",
                      "Format: <code>/{cmd} 45 p1 50</code> (seriya raqami, p1/p2/tb/tm, summa)"),
    "bet_no_odds": ("По серии #N{game} ещё нет коэффициентов на эту ставку.",
                    "#N{game} seriyasi uchun bu stavkaga hali koeffitsient yo'q."),
    "pick_win": ("П{side} {team}", "P{side} {team}"),
    "pick_over": ("ТБ {line}", "TB {line}"),
    "pick_under": ("ТМ {line}", "TM {line}"),
    "duel_p": ("П{side}", "P{side}"),
    "duel_started@pen": ("⚔️ Дуэль началась! Выбирайте победителя ближайшей серии.",
                         "⚔️ Duel boshlandi! Eng yaqin seriya g'olibini tanlang."),
    "pen_card_title": ("⚽️ <b>Серия #N{game}</b> — {status}\n{home} vs {away}",
                       "⚽️ <b>Seriya #N{game}</b> — {status}\n{home} vs {away}"),
    "pen_card_counts": ("Ставок: П1 {w1} · П2 {w2} · ТБ {o} · ТМ {u}", "Stavkalar: P1 {w1} · P2 {w2} · TB {o} · TM {u}"),
    "pen_card_hint": ("Выберите сумму (запоминается), затем исход или тотал.",
                      "Summani tanlang (eslab qolinadi), keyin natija yoki totalni."),
    "pen_card_hint_tour": ("Выберите сумму и кошелёк (запоминается), затем исход или тотал.",
                           "Summa va hamyonni tanlang (eslab qolinadi), keyin natija yoki totalni."),
    "pen_result": ("⚽️ <b>#N{game}</b>: {home} {a}:{b} {away}", "⚽️ <b>#N{game}</b>: {home} {a}:{b} {away}"),
    "duel_challenge@pen": ("⚔️ <b>{c}</b> вызывает <b>{o}</b> на дуэль!\nСтавка {stake} фишек · {games} · угадываем победителя серии",
                           "⚔️ <b>{c}</b> <b>{o}</b> ni duelga chaqiradi!\nStavka {stake} fishka · {games} · seriya g'olibini topamiz"),
    "duel_news@pen": ("⚔️ <b>Новинка: дуэли!</b>\n\n"
                      "Вызовите любого игрока чата один на один:\n"
                      "1. Ответьте на его сообщение командой <code>/duel 500</code> (ставка от {min} до {max} фишек). "
                      "Без ответа — открытый вызов, принять может любой.\n"
                      "2. Соперник жмёт «⚔️ Принять» — у обоих замораживается ставка.\n"
                      "3. Вызывающий выбирает длину: {options} серий. В каждой серии оба выбирают победителя (П1 или П2). "
                      "Выбор соперника скрыт до начала серии.\n"
                      "4. Кто угадал больше — забирает обе ставки. Ничья — ставки возвращаются.\n\n"
                      "Дуэли — на обычных фишках, турнир они не трогают. Удачи! 🍀",
                      "⚔️ <b>Yangilik: duellar!</b>\n\n"
                      "Chatdagi istalgan o'yinchini yakkama-yakka chaqiring:\n"
                      "1. Uning xabariga <code>/duel 500</code> deb javob bering (stavka {min} dan {max} fishkagacha). "
                      "Javobsiz — ochiq chaqiruv, istalgan kishi qabul qilishi mumkin.\n"
                      "2. Raqib «⚔️ Qabul qilish» ni bosadi — ikkalasining stavkasi muzlatiladi.\n"
                      "3. Chaqiruvchi davomiylikni tanlaydi: {options} seriya. Har seriyada ikkalasi g'olibni (P1 yoki P2) tanlaydi. "
                      "Raqibning tanlovi seriya boshlanguncha yashirin.\n"
                      "4. Kim ko'proq topsa — ikkala stavkani oladi. Durrangda stavkalar qaytariladi.\n\n"
                      "Duellar oddiy fishkalarda o'tadi, turnirga ta'sir qilmaydi. Omad! 🍀"),
    "invite@pen": ("⚽️ <b>Прогнозы на пенальти — игра в чате</b>\n\n"
                   "Угадывайте победителя серии и тотал голов, копите фишки и поднимайтесь в топ.\n\n"
                   "<b>Как начать:</b>\n"
                   "1. Нажмите «Начать играть» и затем «Старт» — сразу получите {start} фишек "
                   "и кабинет с кнопками: баланс, бонус, рейтинг, турнир.\n"
                   "2. Здесь выходит карточка каждой серии — выберите сумму и П1/П2 или ТБ/ТМ. "
                   "Ставки принимаются, пока серия не началась.\n"
                   "3. Забирайте бонус {bonus} фишек раз в {days} дн. и следите за рейтингом 📊.\n",
                   "⚽️ <b>Penalti bo'yicha bashorat — chatdagi o'yin</b>\n\n"
                   "Seriya g'olibini va gollar totalini toping, fishka to'plang va topga chiqing.\n\n"
                   "<b>Qanday boshlash:</b>\n"
                   "1. «O'ynashni boshlash» va keyin «Start» ni bosing — darhol {start} fishka "
                   "va tugmali kabinet olasiz: balans, bonus, reyting, turnir.\n"
                   "2. Bu yerda har bir seriya kartochkasi chiqadi — summani va P1/P2 yoki TB/TM ni tanlang. "
                   "Stavkalar seriya boshlanguncha qabul qilinadi.\n"
                   "3. Har {days} kunda {bonus} fishka bonus oling va reytingni kuzating 📊.\n"),
    "tour_start@pen": ("🏆 <b>Турнир начался!</b> До {ends}.\n\n{rules}\n\n<b>Призы:</b>\n{prizes}\n\n"
                       "Ставьте кнопками под карточкой серии (выберите «🏆 Турнир») или командой "
                       "<code>/tbet 45 п1 50</code>. Таблица: /tournament",
                       "🏆 <b>Turnir boshlandi!</b> {ends} gacha.\n\n{rules}\n\n<b>Sovrinlar:</b>\n{prizes}\n\n"
                       "Seriya kartochkasidagi tugmalar bilan tiking («🏆 Turnir» ni tanlang) yoki "
                       "<code>/tbet 45 p1 50</code> buyrug'i bilan. Jadval: /tournament"),
    "gift_tour": ("🎁 <b>Подарок от админа!</b> Всем участникам турнира +{amount} турнирных фишек. Удачи!",
                  "🎁 <b>Admindan sovg'a!</b> Barcha turnir ishtirokchilariga +{amount} turnir fishkasi. Omad!"),
}
