# Алекс — отдельный ИИ-персонаж для чатов «21 классик» / «21 очко»
# Один бот: комментирует посты канала статистики, ведёт столбик прогнозов мастей
# с догоном ×2, отвечает на «какая масть в N игре» и на ответы людей.
# Управление кнопками в личке с ботом: /panel
# Установка: pip install pyTelegramBotAPI anthropic

import json
import os
import random
import re
import threading
import time
from collections import deque, defaultdict

import telebot
from telebot import types
import anthropic
import socket
import sys

# Защита от второй копии: если бот уже запущен (PyCharm + менеджер, двойной клик),
# вторая копия сразу закрывается — иначе обе делят посты канала и путают сигналы.
import os as _os
# файл-замок рядом со скриптом: пока бот работает, вторая копия не стартует
# (раньше был порт 47392, но Windows иногда резервирует порты — бот «падал» без причины)
_LOCK_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(globals().get("__file__", sys.argv[0]))),
                           "alex_21_bot.lock")
try:
    _lock_f = open(_LOCK_PATH, "a+")
    if _os.name == "nt":
        import msvcrt
        _lock_f.seek(0)
        msvcrt.locking(_lock_f.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(_lock_f, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("⛔ alex_21_bot.py уже запущен — вторая копия не стартует. "
          "Закрой старую (Диспетчер задач → python) и запусти заново.")
    sys.exit(1)

CLAUDE_API_KEY = os.environ.get("ALEX_CLAUDE_API_KEY", "")  # секрет — не в git
MODEL = "claude-haiku-5-5"

# Твой Telegram ID (узнать: написать @userinfobot). Только эти люди видят панель
ADMIN_IDS = [384557004]

# ---------- персонажи: здесь только токены и стартовые значения ----------
# Имена и характеры потом меняются кнопками в панели
PERSONAS = [
    {"token": os.environ.get("ALEX_BOT_TOKEN", ""), "name": "Алекс",
     "character": "спокойный игрок в 21, считает очки и перебор, говорит коротко "
                  "«ещё карту было лишнее», «дилер опять набрал», без крика, "
                  "иногда подкалывает чат по прогнозам",
     "game": "all"},
]
# "game" у персонажа: "baccara" — только баккара, "21" — только 21 очко, "all" — везде.
# Без поля — "baccara". Меняется кнопкой «🎲 Игра» в панели персонажа.
DEFAULT_GAME = "all"
GAME_NAMES = {"baccara": "Баккара", "21": "21 очко", "all": "Все чаты"}
# Чат считается чатом «21 очко», если в его названии есть одно из этих слов
GAME_21_WORDS = ("21", "очко", "blackjack", "блэкджек", "блекджек")

DEFAULT_TOPIC = "определи сам по постам канала и сообщениям в чате"
TOPIC_21 = ("21 классик / 21 очко (как блэкджек): сумма очков игрока и дилера, перебор, "
            "«ещё карту», масти карт игрока, догон по мастям")

# ---------- настройки по умолчанию (меняются кнопками и сохраняются) ----------
SETTINGS_FILE = "alex21_settings.json"
DEFAULTS = {
    "enabled": True,          # персонажи вообще работают
    "dialog_chance": 0.25,    # шанс разговора под постом
    "cooldown": 300,          # минимум секунд между разговорами (в каждой группе)
    "auto_quiet": True,       # реже болтать, когда активны живые люди
    "user_reply": True,       # отвечать людям, которые ответили персонажу
    "joke_chance": 0.3,       # шанс, что разговор/ответ будет с шутками
    "sticker_chance": 0.3,    # шанс, что в разговоре/ответе будут стикеры
    "sticker_sets": [],       # названия стикерпаков, из которых берутся стикеры
    "learn_stickers": False,  # сами добавлять паки стикеров, которые шлют люди в группах
    "forecasts": True,        # отвечать на вопросы «какая масть в N игре»
    "auto_column": True,      # сами начинают столбик после постов канала
    "off": [],                # выключенные персонажи (номера)
    # ----- финансы столбика -----
    "fin_on": True,           # показывать банк и суммы в столбике
    "start_bank": 10000,      # банк, с которого начинается самый первый пост
    "flat_pct": 1.0,          # динамический флэт: ставка = % от текущего банка персонажа
    "marathon": False,        # режим «Марафон»: весь банк делится на 3 ставки догона
    "mar_start": 1000,        # стартовый банк каждого марафона
    "mar_len": 15,            # сколько цепочек в марафоне
    "mar": {},                # состояние марафонов: {"chat_id:ключ": {...}}
    "mar_stats": {},
    # ----- режим «нет масти N игр» -----
    "dr_on": False,           # ставка только когда масти не было у Игрока N игр подряд
    "dr_suit_n": 3,           # N: 2, 3, 4, 5, 6          # сколько марафонов зашло/слито: {"chat_id:ключ": {"ok": n, "fail": n}}
    "loss_up_pct": 0.0,       # на сколько % повышать ставку после каждого проигрыша (0 = не повышать)
    "loss_streak": {},        # проигрышей подряд у персонажа в чате: {"chat_id:ключ": число}
    "stake": 100,             # (старое) фиксированная ставка — не используется во флэте
    "dogon_mult": 2.5,        # множитель догона: 100 → 250 → 625
    "odds": 1.7,              # коэффициент на масть
    "bank": {},               # банк каждого персонажа в каждом чате: {"chat_id:ключ": сумма}
    "personas": {},           # изменённые имена/характеры: {"0": {"name":..., "character":...}}
    "topics": {},             # темы групп: {"chat_id": "тема"}
    "groups": {},             # известные группы: {"chat_id": "название"}
}
MIN_MSGS, MAX_MSGS = 2, 5     # сколько реплик в одном разговоре
PAUSE_MIN, PAUSE_MAX = 8, 40  # пауза между репликами (сек)
USER_REPLY_CHANCE = 0.9
HISTORY_SIZE = 30             # сколько последних сообщений группы помнить

ACTIVE_WINDOW = 3600          # активность людей считаем за последний час
QUIET_LEVELS = [              # (сообщений людей за час, множитель шанса)
    (60, 0.0),
    (30, 0.25),
    (10, 0.5),
]


# ---------- настройки ----------
def load_settings():
    data = json.loads(json.dumps(DEFAULTS))   # глубокая копия
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data.update(json.load(f))
        except Exception:
            pass
    return data


cfg = load_settings()
cfg_lock = threading.Lock()


def save_settings():
    with cfg_lock:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=1)


# ---------- запуск ботов ----------
ai = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
for i, p in enumerate(PERSONAS):
    p["key"] = str(i)
    p["bot"] = telebot.TeleBot(p["token"])
    p["id"] = p["bot"].get_me().id
BY_KEY = {p["key"]: p for p in PERSONAS}
BY_ID = {p["id"]: p for p in PERSONAS}
listener = PERSONAS[0]["bot"]   # читает группы и показывает панель


def pname(p):
    return cfg["personas"].get(p["key"], {}).get("name", p["name"])


def pchar(p):
    return cfg["personas"].get(p["key"], {}).get("character", p["character"])


def pgame(p):
    return cfg["personas"].get(p["key"], {}).get("game", p.get("game", DEFAULT_GAME))


def chat_game(chat_id):
    """Игра чата по его названию: «Чат 21 очко» → "21", остальные → "baccara"."""
    title = (cfg["groups"].get(str(chat_id)) or "").lower()
    return "21" if any(w in title for w in GAME_21_WORDS) else "baccara"


def persona_fits(p, chat_id):
    g = pgame(p)
    return g == "all" or g == chat_game(chat_id)


def topic_of(chat_id):
    t = cfg["topics"].get(str(chat_id))
    if t:
        return t
    return TOPIC_21


def system_prompt(chat_id):
    return (
        "Ты пишешь реплики живых людей из Telegram-чата про ставки и игры. "
        "Это не стендап и не детский чат — обычный игровой чат. "
        f"Тема: {topic_of(chat_id)}. "
        "Стиль: коротко (до 20 слов), разговорно, с опечатками иногда ок, "
        "как в WhatsApp/Telegram, без красивых предложений. "
        "Говори про пост, кэфы, счёт, масти, догон, «залетело/слил», банк. "
        "Подхватывай слова из недавнего чата. "
        "ЖЁСТКО ЗАПРЕЩЕНО (это звучит как бот): "
        "шутки про кошек, собак, чай/кофе на клавиатуре, «как ИИ», "
        "«нейросеть», философские приколы, анекдоты не по теме, "
        "«доброе утро, друзья», канцелярит, морали. "
        "Шутки только из жизни ставок: слив банка, серия минусов, "
        "кэф упал, «думал зайдёт», подкол друга по прогнозу. "
        "Не оскорбляй людей жёстко. Политика — нет."
        + slang_rule(chat_id) + repeat_rule(chat_id)
    )


# ---------- жаргон чата: бот учится у живых людей и не повторяет сам себя ----------
SLANG_FILE = SETTINGS_FILE.replace(".json", "_slang.json")
SLANG_STOP = set("""и в во не что он на я с со как а то все всё она так его но да ты к у же вы за бы по только
ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до
вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем
была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним
здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об
другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо
свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между это просто очень
игра игры игре игру масть масти ставка ставку""".split())
slang_lock = threading.Lock()
try:
    with open(SLANG_FILE, "r", encoding="utf-8") as _f:
        slang = json.load(_f)
except Exception:
    slang = {}
_slang_dirty = [0]


def learn_slang(chat_id, text):
    """Запоминаем словечки и короткие фразы живых людей этого чата."""
    if not cfg.get("slang_on", True) or not text or text.startswith("/"):
        return
    t = text.strip()
    if "http" in t or "@" in t or len(t) > 120:
        return
    if not any("а" <= ch.lower() <= "я" or ch.lower() == "ё" for ch in t):
        return                                   # только русские/украинские сообщения
    with slang_lock:
        d = slang.setdefault(str(chat_id), {"words": {}, "phrases": []})
        for w in re.findall(r"[a-zа-яёіїєґ]{3,}", t.lower()):
            if w not in SLANG_STOP:
                d["words"][w] = d["words"].get(w, 0) + 1
        if len(d["words"]) > 400:                # держим только частые
            d["words"] = dict(sorted(d["words"].items(), key=lambda x: -x[1])[:250])
        n = len(t.split())
        if 2 <= n <= 8 and t not in d["phrases"]:
            d["phrases"] = (d["phrases"] + [t])[-40:]
        _slang_dirty[0] += 1
        if _slang_dirty[0] >= 10:
            _slang_dirty[0] = 0
            try:
                with open(SLANG_FILE, "w", encoding="utf-8") as f:
                    json.dump(slang, f, ensure_ascii=False)
            except Exception as e:
                print("жаргон:", e)


def slang_rule(chat_id):
    if not cfg.get("slang_on", True):
        return ""
    d = slang.get(str(chat_id))
    if not d:
        return ""
    top = [w for w, c in sorted(d["words"].items(), key=lambda x: -x[1]) if c >= 2][:20]
    ph = random.sample(d["phrases"], min(6, len(d["phrases"])))
    if not top and not ph:
        return ""
    return (" Жаргон ЭТОГО чата (так пишут живые люди здесь): "
            + (", ".join(top) + ". " if top else "")
            + ("Их фразы: " + " | ".join(f"«{x}»" for x in ph) + ". " if ph else "")
            + "Иногда, к месту, вставляй одно такое словечко или похожий оборот — "
              "не в каждой реплике и не копируй фразы целиком.")


def repeat_rule(chat_id):
    """Последние реплики персонажей — чтобы не повторялись и не шутили одинаково."""
    mine = [txt for who, txt in list(history[chat_id]) if isinstance(who, dict)][-10:]
    if not mine:
        return ""
    return (" Уже сказано персонажами (НЕ повторяй эти фразы, шутки и начала реплик, "
            "придумай по-другому): " + " | ".join(f"«{x[:60]}»" for x in mine) + ".")


# Всё раздельно для каждой группы, чтобы темы не смешивались
history = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))
user_times = defaultdict(deque)
chat_state = defaultdict(lambda: {"last_dialog": 0, "busy": False})
state = {"last_post": None}   # последний пост в любой группе (для кнопки "сейчас")
stats = {"day": time.strftime("%Y-%m-%d"), "dialogs": 0, "sent": 0, "errors": 0}
lock = threading.Lock()
pending = {}                  # admin_id -> (что вводим, ключ) — ожидание текста


def bump(key):
    today = time.strftime("%Y-%m-%d")
    if stats["day"] != today:
        stats.update(day=today, dialogs=0, sent=0, errors=0)
    stats[key] += 1


def remember_group(chat):
    cid = str(chat.id)
    title = chat.title or cid
    if cfg["groups"].get(cid) != title:
        cfg["groups"][cid] = title
        save_settings()


membership = {}   # (chat_id, persona_key) -> (может писать?, время проверки)


def can_post(p, chat_id):
    """Есть ли персонаж в этой группе и может ли писать (проверка раз в час).
    Персонаж пишет только в чатах своей игры (баккара / 21 очко)."""
    if not persona_fits(p, chat_id):
        return False
    k = (chat_id, p["key"])
    v = membership.get(k)
    if v and time.time() - v[1] < 3600:
        return v[0]
    try:
        m = p["bot"].get_chat_member(chat_id, p["id"])
        ok = (m.status in ("member", "administrator", "creator")
              or (m.status == "restricted" and getattr(m, "can_send_messages", False)))
    except Exception:
        ok = False
    membership[k] = (ok, time.time())
    if not ok:
        print(f"{pname(p)} не состоит в группе «{cfg['groups'].get(str(chat_id), chat_id)}» "
              f"или не может там писать — добавь его туда")
    return ok


def active_personas():
    return [p for p in PERSONAS if p["key"] not in cfg["off"]]


def users_last_hour(chat_id):
    q = user_times[chat_id]
    now = time.time()
    while q and now - q[0] > ACTIVE_WINDOW:
        q.popleft()
    return len(q)


def dialog_chance(chat_id):
    if not cfg["auto_quiet"]:
        return cfg["dialog_chance"]
    n = users_last_hour(chat_id)
    for limit, factor in QUIET_LEVELS:
        if n >= limit:
            return cfg["dialog_chance"] * factor
    return cfg["dialog_chance"]


def history_text(chat_id):
    # Персонажи хранятся в истории как объекты, а имя подставляется текущее,
    # поэтому после переименования старые имена в разговор не попадают
    lines = []
    for who, txt in history[chat_id]:
        if isinstance(who, dict) and who["key"] in cfg["off"]:
            continue   # реплики выключенных персонажей не показываем, чтобы к ним не обращались
        name = pname(who) if isinstance(who, dict) else who
        lines.append(f"{name}: {txt}")
    return "\n".join(lines) or "(пусто)"


def names_rule(chat_id=None):
    active = active_personas()
    if chat_id is not None:
        active = [p for p in active if persona_fits(p, chat_id)]
    names = ", ".join(pname(p) for p in active) or "никого"
    rule = (f"Из персонажей сейчас в чате есть ТОЛЬКО: {names}. Других персонажей "
            f"в чате нет — не обращайся к ним, не упоминай их и не жди от них ответа.")
    if len(active) == 1:
        rule += (" Персонаж в чате один: пиши от себя или обращайся к живым "
                 "участникам, а не к другим персонажам.")
    return rule


REFUSAL_MARKERS = ("не буду писать", "не могу помочь", "не могу написать", "могу помочь с другим",
                   "реплик", "персонаж", "сценари", "как ии", "языков", "я не буду")


def clean_reply(text):
    """Отсекает отказы/служебные ответы ИИ, чтобы они не попали в чат"""
    t = (text or "").strip()
    low = t.lower()
    if len(t) > 400 or any(k in low for k in REFUSAL_MARKERS):
        if t:
            print("ИИ ответил не репликой, в чат не отправлено:", t[:120].replace("\n", " "))
        return ""
    return t


def ask_ai(chat_id, prompt, max_tokens):
    # Модель может сначала "подумать" (блок thinking), поэтому запас токенов
    # побольше, а из ответа берём только текстовые блоки
    r = ai.messages.create(model=MODEL, max_tokens=max_tokens + 1500,
                           system=system_prompt(chat_id),
                           messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    if not text.strip():
        raise ValueError("ИИ вернул пустой ответ")
    return text.strip()


def send_as(p, chat_id, text, reply_to=None):
    bot = p["bot"]
    try:
        bot.send_chat_action(chat_id, "typing")
        time.sleep(min(2 + len(text) / 15, 7))
        kw = {}
        if reply_to:
            kw["reply_to_message_id"] = reply_to
        try:
            sent = bot.send_message(chat_id, text, **kw)
        except Exception as e:
            if "replied not found" not in str(e):
                raise
            print(f"{pname(p)} не видит сообщение для ответа — включи ему "
                  f"админку или отключи privacy в BotFather")
            sent = bot.send_message(
                chat_id, text, allow_sending_without_reply=True, **kw
            )
        history[chat_id].append((p, text))
        bump("sent")
        return sent.message_id
    except Exception as e:
        print(f"Ошибка отправки ({pname(p)}):", e)
        if "chat not found" in str(e) or "not a member" in str(e):
            membership[(chat_id, p["key"])] = (False, time.time())
        bump("errors")
        return None


# ---------- стикеры ----------
# file_id стикера у каждого бота свой, поэтому каждый бот сам загружает паки по названию
sticker_cache = {}   # persona_key -> (tuple(паков), [(эмодзи, file_id), ...])


def bot_stickers(p):
    sets = tuple(cfg["sticker_sets"])
    cached = sticker_cache.get(p["key"])
    if cached and cached[0] == sets:
        return cached[1]
    items = []
    for name in sets:
        try:
            for st in p["bot"].get_sticker_set(name).stickers:
                items.append((st.emoji or "", st.file_id))
        except Exception as e:
            print(f"Не удалось загрузить стикерпак {name} для {pname(p)}:", e)
    sticker_cache[p["key"]] = (sets, items)
    return items


def sticker_emojis():
    """Какие эмодзи есть в стикерах — их показываем ИИ на выбор"""
    if not cfg["sticker_sets"]:
        return []
    return sorted({e for e, _ in bot_stickers(PERSONAS[0]) if e})[:40]


def sticker_rule(single=False):
    """С шансом sticker_chance разрешает ИИ вставлять стикеры"""
    emojis = sticker_emojis()
    if not emojis or random.random() >= cfg.get("sticker_chance", 0):
        return ""
    lst = " ".join(emojis)
    if single:
        return (f"\nМожешь в конце добавить стикер-реакцию: напиши [sticker:эмодзи], "
                f"эмодзи выбери из: {lst}. Добавляй только если к месту.\n")
    return (f"\nВ этом разговоре 1–2 реплики могут быть стикером-реакцией (смешной, к месту). "
            f"Для этого добавь в реплику поле \"sticker\" с одним эмодзи из списка: {lst}. "
            f"Если реплика — только стикер, поле \"text\" оставь пустым.\n")


def send_sticker_as(p, chat_id, emoji, reply_to):
    items = bot_stickers(p)
    if not items:
        return None
    match = [f for e, f in items if emoji and (emoji in e or e in emoji)]
    file_id = random.choice(match or [f for _, f in items])
    bot = p["bot"]
    try:
        bot.send_chat_action(chat_id, "choose_sticker")
        time.sleep(random.uniform(1.5, 4))
        try:
            sent = bot.send_sticker(chat_id, file_id, reply_to_message_id=reply_to)
        except Exception as e:
            if "replied not found" not in str(e):
                raise
            sent = bot.send_sticker(chat_id, file_id, reply_to_message_id=reply_to,
                                    allow_sending_without_reply=True)
        history[chat_id].append((p, f"[стикер {emoji}]"))
        bump("sent")
        return sent.message_id
    except Exception as e:
        print(f"Ошибка стикера ({pname(p)}):", e)
        bump("errors")
        return None


# ---------- шутки ----------
JOKE_STYLES = [
    "один хвастается залётом, второй напоминает про вчерашний слив",
    "подкалывают чей прогноз снова мимо",
    "ноют что кэф уже не тот / линия ушла",
    "коротко: «ну всё, банк плачет» / «держи карман шире»",
    "спорят «рандом» vs «я же говорил»",
    "шутят что догон сегодня до зарплаты",
]


def joke_rule():
    """С шансом joke_chance добавляет к запросу указание пошутить"""
    if random.random() >= cfg.get("joke_chance", 0):
        return ""
    return (
        "\nВ этот раз с лёгким подколом: " + random.choice(JOKE_STYLES) + ". "
        "Только юмор про ставки/игру из поста. "
        "Никаких кошек, чая, клавиатуры, анекдотов «вообще». "
        "1–2 коротких фразы, как в реальном чате.\n"
    )


# ---------- разговор под постом ----------
def make_dialog(chat_id, post_text, members, n):
    roles = "\n".join(f"- {pname(p)}: {pchar(p)}" for p in members)
    prompt = (
        f"Персонажи (пиши ИМЕННО их голосом):\n{roles}\n{names_rule(chat_id)}\n\n"
        f"Недавний чат (подхвати тон и слова):\n{history_text(chat_id)}\n\n"
        f"Новый пост:\n{post_text}\n\n"
        f"Разговор из {n} коротких реплик под постом. "
        f"Чередуй говорящих, никто не пишет два раза подряд. "
        f"Каждая реплика — про ЭТОТ пост (счёт, кэф, исход, масть), не оффтоп. "
        f"{joke_rule()}"
        f"{sticker_rule()}"
        f"Запрещены шаблонные ИИ-шутки. "
        f"Ответь ТОЛЬКО JSON: "
        f'[{{"who": "Имя", "text": "реплика"}}]'
    )
    raw = ask_ai(chat_id, prompt, 600)
    m = re.search(r"\[.*\]", raw, re.S)
    data = json.loads(m.group(0)) if m else []
    by_name = {pname(p): p for p in members}
    out = []
    for d in data:
        if d.get("who") not in by_name:
            continue
        text = clean_reply(d.get("text") or "")
        sticker = (d.get("sticker") or "").strip()
        if text or sticker:
            out.append((by_name[d["who"]], text, sticker))
    return out


def solo_comment(p, chat_id, post_id, post_text):
    """Если активен только один персонаж — он просто комментирует пост сам"""
    prompt = (
        f"Ты — {pname(p)} ({pchar(p)}), пишешь в игровой чат.\n"
        f"{names_rule(chat_id)}\n\n"
        f"Недавний чат:\n{history_text(chat_id)}\n\n"
        f"Пост:\n{post_text}\n\n"
        f"{joke_rule()}"
        f"{sticker_rule(single=True)}"
        f"Одна короткая реплика по посту (счёт/кэф/исход), как живой игрок. "
        f"Без ИИ-шуток про кошек и чай. Только текст."
    )
    bump("dialogs")
    raw = ask_ai(chat_id, prompt, 120)
    m = re.search(r"\[sticker:\s*([^\]]+)\]", raw)
    text = clean_reply(re.sub(r"\[sticker:[^\]]*\]", "", raw))
    time.sleep(random.randint(PAUSE_MIN, PAUSE_MAX))
    msg_id = send_as(p, chat_id, text, post_id) if text else None
    if m:
        send_sticker_as(p, chat_id, m.group(1).strip(), msg_id or post_id)


def run_dialog(chat_id, post_id, post_text):
    try:
        pool = [p for p in active_personas() if can_post(p, chat_id)]
        if not pool:
            return
        if len(pool) == 1:
            solo_comment(pool[0], chat_id, post_id, post_text)
            return
        members = random.sample(pool, k=random.randint(2, min(3, len(pool))))
        lines = make_dialog(chat_id, post_text, members,
                            random.randint(MIN_MSGS, MAX_MSGS))
        bump("dialogs")
        reply_to = post_id
        last_speaker = None
        for p, text, sticker in lines:
            if not cfg["enabled"]:
                break             # выключили посреди разговора — замолкаем
            if p is last_speaker:
                continue          # не даём персонажу отвечать самому себе
            time.sleep(random.randint(PAUSE_MIN, PAUSE_MAX))
            msg_id = None
            if text:
                msg_id = send_as(p, chat_id, text, reply_to)
            if sticker and (msg_id or not text):
                st_id = send_sticker_as(p, chat_id, sticker, msg_id or reply_to)
                msg_id = msg_id or st_id
            if not msg_id:
                # реплика не ушла — дальше разговор потеряет смысл, обрываем
                print(f"Разговор прерван: {pname(p)} не смог написать")
                break
            reply_to = msg_id
            last_speaker = p
    except Exception as e:
        print("Ошибка разговора:", e)
        bump("errors")
    finally:
        chat_state[chat_id]["busy"] = False


def start_dialog(post, force=False):
    """Запустить разговор под постом. force — без шанса и паузы"""
    if not post:
        return "Ещё не было ни одного поста с момента запуска"
    chat_id = post[0]
    st = chat_state[chat_id]
    with lock:
        now = time.time()
        if st["busy"]:
            return "Персонажи уже разговаривают"
        if not force:
            if not cfg["enabled"] or now - st["last_dialog"] < cfg["cooldown"]:
                return None
            if random.random() > dialog_chance(chat_id):
                return None
        st["busy"] = True
        st["last_dialog"] = now
    threading.Thread(target=run_dialog, args=post, daemon=True).start()
    return "Разговор запущен 🎬"


def in_group(m):
    return m.chat.type in ("group", "supergroup")


@listener.message_handler(func=lambda m: in_group(m) and m.is_automatic_forward,
                          content_types=["text", "photo"])
def on_post(m):
    remember_group(m.chat)
    text = m.text or m.caption or ""
    posts[m.chat.id][m.message_id] = text
    history[m.chat.id].append(("Пост канала", text[:300]))
    post = (m.chat.id, m.message_id, text)
    state["last_post"] = post
    start_dialog(post)
    # Столбик: проверка захода + новый прогноз, публикация только по итогу игры
    threading.Thread(target=process_column_post, args=(m.chat.id, text), daemon=True).start()


# ---------- ответ живым людям ----------
def answer_user(p, chat_id, user_name, user_text, reply_to):
    time.sleep(random.randint(5, 20))
    try:
        prompt = (
            f"Ты пишешь реплику персонажа {pname(p)} ({pchar(p)}).\n"
            f"{names_rule(chat_id)}\n\n"
            f"Недавний чат:\n{history_text(chat_id)}\n\n"
            f"Участник {user_name} ответил тебе: {user_text}\n"
            f"Отвечай именно {user_name}, по сути его сообщения.\n\n"
            f"{joke_rule()}"
            f"{sticker_rule(single=True)}"
            f"Напиши ответ {pname(p)}. Только текст реплики."
        )
        raw = ask_ai(chat_id, prompt, 120)
        m = re.search(r"\[sticker:\s*([^\]]+)\]", raw)
        text = clean_reply(re.sub(r"\[sticker:[^\]]*\]", "", raw))
        msg_id = send_as(p, chat_id, text, reply_to) if text else None
        if m:
            send_sticker_as(p, chat_id, m.group(1).strip(), msg_id or reply_to)
    except Exception as e:
        print("Ошибка ответа:", e)
        bump("errors")


# ---------- конкурс прогнозов: «какая масть в N игре» ----------
SUIT_SYMBOLS = {"♠": "♠️", "♣": "♣️", "♥": "♥️", "❤": "♥️", "♦": "♦️"}
FORECAST_COOLDOWN = 45                     # не чаще раза в 45 сек в одной группе
posts = defaultdict(lambda: OrderedLimited())   # chat_id -> {message_id: текст поста}
last_forecast = defaultdict(float)
# Столбики: chat_id -> persona_key -> [{game, cur_game, suit, status, step}]
# status: "⏳" (ждём) | "✅" | "❌"
# Одна строка = один прогноз. В ЭТОЙ ЖЕ строке идёт её догон:
#   446♦️ → мимо → 446♦️1️⃣ (ждём 447) → мимо → 446♦️2️⃣ (ждём 448) → ✅ или ❌
# Новые строки появляются через одну игру: 446, 448, 450... и ведут свой догон сами.
columns = defaultdict(lambda: defaultdict(list))
COLUMN_MAX = 15   # строк в одном посте; 16-я строка начинает НОВЫЙ пост
# Старые (заполненные) посты, в которых ещё идут догоны:
# (chat_id, persona_key) -> [{"rows": [...], "msg_id": id}, ...]
column_archive = defaultdict(list)
DOGON_STEPS = 1  # без догона: одна игра на прогноз, мимо — сразу ❌
# Прогноз с запасом: закончилась 444 → прогноз на 446 (444 + LEAD), чтобы сервер успевал.
LEAD = 2
# Новая строка не чаще, чем раз в LINE_GAP игр: 446, 448, 450...
LINE_GAP = 2
# Догон внутри строки идёт на следующую игру: 446 → 447 → 448
DOGON_GAP = 1
# Последнее сообщение-столбик: chat_id -> persona_key -> message_id (чтобы редактировать)
column_msg_ids = defaultdict(dict)
# Защита от повторной публикации прогноза на одну и ту же игру
auto_prediction_posted = defaultdict(dict)   # marker -> {номер игры: время прогноза}
DUP_WINDOW = 30 * 60      # повторный прогноз на тот же номер блокируем только 30 мин
STALE_SEC = 10 * 60       # строка ждёт итог дольше 10 мин — считаем игру несыгранной ⚪


class OrderedLimited(dict):
    """Словарь последних 60 постов (старые удаляются)"""
    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        while len(self) > 60:
            del self[next(iter(self))]


def game_no_from_post(text):
    m = re.search(r"#N(\d+)", text or "", re.I)
    return m.group(1) if m else None


def game_is_finished(text):
    """Определяет опубликованный итог игры по меткам Baccarat или финальному счёту."""
    t = text or ""
    # Игра ещё идёт: ▶ / ⏰ / ⏳ (и в баккаре, и в 21 очко)
    if re.search(r"▶️|▶|⏳|⌛|⏰", t):
        return False
    if re.search(r"идёт|идет\s*раздач", t, re.I):
        return False
    # Готовые игры: #R #X #O #G (21 очко ставит #X/#O/#G) или тег суммы #T38
    if re.search(r"(?<!\w)#(?:R|X|O|G)\b", t, re.I):
        return True
    if re.search(r"(?<!\w)#T\d+", t, re.I):
        return True
    if re.search(r"✅\s*\d", t):
        return True
    if re.search(r"\d+\([^)]*\)\s*[-–]\s*✅", t):
        return True
    return False


# ---------- финансы ----------
column_start = {}   # (chat_id, persona_key) -> банк в начале текущего поста


def money(v):
    v = round(v, 2)
    txt = f"{v:,.2f}".replace(",", " ").replace(".00", "")
    return txt


def bank_key(chat_id, persona_key):
    return f"{chat_id}:{persona_key}"


def get_bank(chat_id, persona_key):
    b = cfg["bank"]
    k = bank_key(chat_id, persona_key)
    if k not in b and str(chat_id) in b:      # банк из прошлой версии (ключ = чат)
        b[k] = b.pop(str(chat_id))
    return float(b.get(k, cfg["start_bank"]))


def stake_for(step):
    return round(cfg["stake"] * cfg["dogon_mult"] ** (step - 1), 2)


# ---------- марафон ----------
MAR_STEPS = 3                      # основная ставка + 2 догона
KEYCAP = {1: "0⃣", 2: "1⃣", 3: "2⃣"}


def marathon_on():
    return bool(cfg.get("marathon"))


def new_marathon():
    v = float(cfg.get("mar_start", 1000))
    return {"start": v, "bank": v, "n": 0, "wins": 0, "new_post": True}


def mar_state(chat_id, persona_key):
    return cfg.setdefault("mar", {}).setdefault(bank_key(chat_id, persona_key), new_marathon())


MAR_ROUND = 10   # ставки марафона кратны 10: 130~280~590


def mar_stakes(bank):
    """Делит банк на 3 ровные ставки (кратные 10): каждый догон отбивает прошлые
    ставки и даёт ту же прибыль, что и первая. Сумма трёх ставок ≤ банк."""
    import math
    k = cfg["odds"]
    w = [1.0]
    for _ in range(MAR_STEPS - 1):
        w.append((sum(w) + (k - 1)) / (k - 1))
    s1 = int(round(bank / sum(w) / MAR_ROUND)) * MAR_ROUND
    while s1 > MAR_ROUND:
        st = [s1]
        profit = s1 * (k - 1)
        for _ in range(MAR_STEPS - 1):
            need = (sum(st) + profit) / (k - 1)
            st.append(int(math.ceil(need / MAR_ROUND - 1e-9)) * MAR_ROUND)
        if sum(st) <= bank:
            return st
        s1 -= MAR_ROUND
    # банк слишком мал для ровных ставок — без округления
    x = bank / sum(w)
    return [max(1, int(x * wi)) for wi in w]


def mar_result(row):
    step = int(row.get("step", 1))
    st = row["stakes"]
    spent = sum(st[:step])
    if row["status"] == "✅":
        return round(st[step - 1] * cfg["odds"] - spent, 2)
    return -float(spent)


def flat_stake(chat_id, persona_key):
    """Ставка: flat_pct % от текущего банка, после каждого проигрыша подряд
    увеличивается на loss_up_pct %. После захода — снова базовая."""
    base = get_bank(chat_id, persona_key) * cfg.get("flat_pct", 1.0) / 100
    streak = int(cfg.get("loss_streak", {}).get(bank_key(chat_id, persona_key), 0))
    up = 1 + cfg.get("loss_up_pct", 0.0) / 100
    stake = base * (up ** streak)
    # ставка не больше банка
    stake = min(stake, get_bank(chat_id, persona_key))
    return max(1.0, round(stake, 2))


def row_result(row):
    """Плюс/минус закрытой строки."""
    if "stake" in row:   # динамический флэт, одна ставка на строку
        if row["status"] == "✅":
            return round(row["stake"] * (cfg["odds"] - 1), 2)
        if row["status"] == "❌":
            return -row["stake"]
        return 0.0
    step = int(row.get("step", 1))
    spent = sum(stake_for(i) for i in range(1, step + 1))
    if row["status"] == "✅":
        return round(stake_for(step) * cfg["odds"] - spent, 2)
    if row["status"] == "❌":
        return -round(spent, 2)
    return 0.0


def close_row_money(chat_id, persona_key, row):
    """Записывает результат строки в банк (один раз)."""
    if "result" in row:
        return
    if row.get("mar"):
        st = mar_state(chat_id, persona_key)
        row["result"] = mar_result(row)
        st["bank"] = round(st["bank"] + row["result"], 2)
        st["n"] += 1
        if row["status"] == "✅":
            st["wins"] += 1
        row["bank_after"] = st["bank"]
        failed = row["status"] == "❌" or st["bank"] < 1
        if failed or st["n"] >= int(cfg.get("mar_len", 15)):
            ms = cfg.setdefault("mar_stats", {}).setdefault(bank_key(chat_id, persona_key),
                                                            {"ok": 0, "fail": 0})
            ms["fail" if failed else "ok"] += 1
            net = round(st["bank"] - st["start"], 2)          # чистыми за этот марафон
            if net >= 0:
                ms["won"] = round(ms.get("won", 0) + net, 2)
            else:
                ms["lost"] = round(ms.get("lost", 0) - net, 2)
            row["mar_end"] = {"start": st["start"], "end": st["bank"], "wins": st["wins"],
                              "n": st["n"], "ok": not failed, "net": net,
                              "tot_ok": ms["ok"], "tot_fail": ms["fail"],
                              "tot_won": ms.get("won", 0), "tot_lost": ms.get("lost", 0)}
            cfg["mar"][bank_key(chat_id, persona_key)] = new_marathon()   # следующий — новым постом
        save_settings()
        return
    row["result"] = row_result(row)
    k = bank_key(chat_id, persona_key)
    cfg["bank"][k] = round(get_bank(chat_id, persona_key) + row["result"], 2)
    # серия проигрышей: ❌ → +1, ✅ → сброс к базовой ставке
    ls = cfg.setdefault("loss_streak", {})
    ls[k] = 0 if row["status"] == "✅" else int(ls.get(k, 0)) + 1
    save_settings()


def add_column_picks(chat_id, persona_key, game_no, suits, step=None):
    """Начинает НОВУЮ строку прогноза на игру game_no.
    Новая строка — не раньше чем через LINE_GAP игр после предыдущей (446, 448, 450...).
    Догоны новых строк не создают — они идут внутри своей строки."""
    col = columns[chat_id][persona_key]
    try:
        gn = int(game_no)
    except ValueError:
        return False
    old_rows = [r for b in column_archive[(chat_id, persona_key)] for r in b["rows"]]
    for x in old_rows + col:
        if time.time() - x.get("ts", 0) > DUP_WINDOW:
            continue              # старая строка (например, до сброса номеров) не мешает
        try:
            if gn - int(x["game"]) < (1 if _NO_GAP[0] else LINE_GAP) and gn >= int(x["game"]):
                return False   # строка на эту или слишком близкую игру уже есть
        except ValueError:
            continue
    mar = marathon_on()
    mst = mar_state(chat_id, persona_key) if mar else None
    if mar and any(r["status"] == "⏳" for r in col):
        return False   # в марафоне цепочки идут строго по одной
    need_roll = len(col) >= COLUMN_MAX
    if col and bool(col[-1].get("mar")) != mar:
        need_roll = True          # сменили режим — начинаем новый пост
    if mar and mst.get("new_post") and col:
        need_roll = True          # новый марафон — новый пост
    if mar:
        mst["new_post"] = False
    if need_roll:
        # Пост заполнен (15 строк) — откладываем его в архив и начинаем новый пост.
        old_msg = column_msg_ids.get(chat_id, {}).pop(persona_key, None)
        column_last_text.pop((chat_id, persona_key), None)
        # Незакрытые строки (идёт догон) переносим в новый пост, в старом
        # остаются только закрытые — его итог окончательный.
        done = [r for r in col if r["status"] != "⏳"]
        carry = [r for r in col if r["status"] == "⏳"]
        if old_msg and done:
            column_archive[(chat_id, persona_key)].append(
                {"rows": done, "msg_id": old_msg, "fresh": True,
                 "start": column_start.get((chat_id, persona_key), get_bank(chat_id, persona_key))})
        col = columns[chat_id][persona_key] = carry
        # стартовый банк нового поста = итог предыдущего
        column_start[(chat_id, persona_key)] = get_bank(chat_id, persona_key)
    if not col:
        column_start[(chat_id, persona_key)] = get_bank(chat_id, persona_key)
    col.append({
        "game": str(gn),        # номер игры строки (не меняется)
        "cur_game": str(gn),    # игра, итог которой сейчас ждёт строка
        "suit": suits[0],
        "status": "⏳",
        "miss": 0,
        "step": 1,
        # динамический флэт: % от банка персонажа в момент прогноза
        "stake": flat_stake(chat_id, persona_key),
        "ts": time.time(),        # когда начали ждать итог
    })
    if mar:
        row = col[-1]
        row.pop("stake", None)
        row["mar"] = True
        row["mar_start"] = mst["start"]
        row["mar_key"] = bank_key(chat_id, persona_key)
        row["stakes"] = mar_stakes(mst["bank"])
        row["max_steps"] = MAR_STEPS
    return True


def update_columns_from_post(chat_id, text):
    """Сверяет масть игрока №1 с каждой строкой, которая ждёт эту игру.
    Заход → ✅. Промах → в той же строке цифра догона +1 и ждём следующую игру.
    Промах на 2-м догоне → ❌ в той же строке.
    Повторная правка того же поста строку второй раз не трогает (cur_game уже сдвинут)."""
    if not game_is_finished(text):
        return set()
    g = game_no_from_post(text)
    if not g:
        return set()
    try:
        next_game = str(int(g) + DOGON_GAP)
    except ValueError:
        return set()

    actual = set(player_suits(text))
    if not actual:
        return set()

    changed = set()
    targets = [(pkey, col) for pkey, col in list(columns[chat_id].items())]
    for (cid, pkey), blocks in list(column_archive.items()):
        if cid != chat_id:
            continue
        for i, b in enumerate(blocks):
            targets.append((("arch", pkey, id(b)), b["rows"]))
    for pkey, col in targets:
        for row in col:
            if row.get("status") != "⏳":
                continue
            if str(row.get("cur_game", row.get("game"))) != str(g):
                continue
            step = int(row.get("step", 1))
            if row.get("suit") in actual:
                row["status"] = "✅"
                close_row_money(chat_id, pkey[1] if isinstance(pkey, tuple) else pkey, row)
                if not isinstance(pkey, tuple):
                    column_hits.add((chat_id, pkey))   # заход → столбик новым постом (и в марафоне)
            elif step < int(row.get("max_steps", DOGON_STEPS)):
                row["step"] = step + 1
                row["miss"] = step
                row["cur_game"] = next_game
                row["ts"] = time.time()
            else:
                row["status"] = "❌"
                row["miss"] = step
                close_row_money(chat_id, pkey[1] if isinstance(pkey, tuple) else pkey, row)
            changed.add(pkey)
    return changed


# ---------- публикация столбика: только когда проверен заход ----------
column_last_text = {}          # (chat_id, persona_key) -> последний опубликованный текст
column_dirty = set()           # не вышло из-за лимита Telegram — повторим со следующим итогом
column_lock = threading.Lock()
column_hits = set()            # (chat_id, persona_key), где только что был заход
# После захода столбик публикуется НОВЫМ сообщением внизу чата.
# True — старое сообщение со столбиком удаляется, чтобы не было дублей.
DELETE_OLD_ON_REPOST = False


def _do_publish_column(chat_id, persona_key, as_new=False):
    """Правит сообщение-столбик. as_new=True — шлёт столбик новым сообщением вниз
    (после захода), старое удаляет."""
    p = BY_KEY.get(persona_key)
    if not p:
        return
    if as_new:
        old = column_msg_ids.get(chat_id, {}).pop(persona_key, None)
        column_last_text.pop((chat_id, persona_key), None)
        if old and DELETE_OLD_ON_REPOST:
            try:
                p["bot"].delete_message(chat_id, old)
            except Exception as e:
                print(f"Не удалось удалить старый столбик {persona_key}: {e}")
    col_text = format_column(chat_id, persona_key, title=pname(p))
    if not col_text:
        return
    k = (chat_id, persona_key)
    if column_last_text.get(k) == col_text and column_msg_ids.get(chat_id, {}).get(persona_key):
        return   # ничего не изменилось — не трогаем Telegram
    msg_id = column_msg_ids.get(chat_id, {}).get(persona_key)
    if msg_id:
        try:
            p["bot"].edit_message_text(col_text, chat_id, msg_id, parse_mode="HTML")
            column_last_text[k] = col_text
            return
        except Exception as e:
            err = str(e).lower()
            if "message is not modified" in err:
                column_last_text[k] = col_text
                return
            if "too many requests" in err or "retry after" in err:
                print(f"Telegram просит подождать со столбиком {persona_key}: {e}")
                column_dirty.add(k)
                return
            # сообщение удалили или оно недоступно — создадим новое
            print(f"Не удалось отредактировать столбик {persona_key}: {e}")
            column_msg_ids[chat_id].pop(persona_key, None)
    try:
        sent = p["bot"].send_message(chat_id, col_text, parse_mode="HTML")
        column_msg_ids[chat_id][persona_key] = sent.message_id
        column_last_text[k] = col_text
    except Exception as e:
        print(f"Ошибка отправки столбика {persona_key}: {e}")


def _edit_archived(chat_id, persona_key, block_id):
    """Дописывает результат догона в старый (заполненный) пост."""
    blocks = column_archive.get((chat_id, persona_key)) or []
    b = next((x for x in blocks if id(x) == block_id), None)
    p = BY_KEY.get(persona_key)
    if not b or not p:
        return
    # конец марафона — итог новым сообщением внизу чата
    if b["rows"] and b["rows"][-1].get("mar_end") and not b.get("final_sent"):
        b["final_sent"] = True
        try:
            p["bot"].send_message(chat_id, format_rows(b["rows"], pname(p)), parse_mode="HTML")
        except Exception as e:
            print(f"Не удалось отправить итог марафона {persona_key}: {e}")
        if not any(r["status"] == "⏳" for r in b["rows"]):
            blocks.remove(b)
        return
    try:
        end = b.get("start", 0) + sum(r.get("result", 0) for r in b["rows"])
        p["bot"].edit_message_text(format_rows(b["rows"], pname(p), b.get("start"), end), chat_id,
                                   b["msg_id"], parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e).lower():
            print(f"Не удалось дописать старый столбик {persona_key}: {e}")
    if not any(r["status"] == "⏳" for r in b["rows"]):
        blocks.remove(b)   # все догоны в старом посте закрыты — больше его не трогаем


def refresh_column_message(chat_id, persona_key):
    _do_publish_column(chat_id, persona_key)


def publish_column(p, chat_id, force_new=False):
    _do_publish_column(chat_id, p["key"])


def void_stale_rows(chat_id, text):
    """Строка ждёт игру, итог которой уже не придёт: прошло больше STALE_SEC,
    или номера игр сбросились / ушли далеко вперёд. Такую строку закрываем ⚪
    без изменения банка, чтобы прогнозы не вставали."""
    try:
        g = int(game_no_from_post(text) or 0)
    except ValueError:
        g = 0
    now = time.time()
    keys = set()
    targets = [(pk, col) for pk, col in list(columns[chat_id].items())]
    for (cid, pk), blocks in list(column_archive.items()):
        if cid == chat_id:
            for b in blocks:
                targets.append((("arch", pk, id(b)), b["rows"]))
    for pk, col in targets:
        for row in col:
            if row.get("status") != "⏳":
                continue
            try:
                wait = int(row.get("cur_game", row.get("game")))
            except ValueError:
                continue
            old = now - row.get("ts", now) > STALE_SEC
            jumped = g and (g < wait - 20 or g > wait + 1)
            if old or jumped:
                row["status"] = "⚪"
                row["result"] = 0.0
                keys.add(pk)
                print(f"Строка {row['game']}{row['suit']} закрыта как несыгранная "
                      f"(ждала игру {wait}, пришла {g})")
    return keys


# ================= СИГНАЛ «21GROX» (всегда включён) =================
# Масти нет у Игрока 4 игры подряд (любая из 4) → сигнал 21GROX.
# Сразу 3 отдельные линии, каждая — догон до 5 игр до захода:
#   🤝 ничья:            100-200-300-400-500
#   21 (у кого-то 21):   100-200-400-800-1200
#   🥇AA Голд (два туза): 100-200-300-400-500
GROX_NEED = 4        # по умолчанию: игр подряд без масти у Игрока (кнопки 2/3/4/5)
DIAM_LEAD = 2        # «Стратегия бубна»: сигнал через N игр после комбинации
GROX_LEAD = 2        # условие на #N → ставки с #N+2


def grox_need():
    return int(cfg.get("grox_n", GROX_NEED))


def diam_on():
    """Стратегия бубна: сигнал 21GROX по комбинации карт с ♦️."""
    return bool(cfg.get("diam_on", False))


FIVE_NEED = 5   # сигнал «Пять»: N игр подряд без X/O/G/R
five_streak = {}  # chat_id -> сколько чистых игр подряд


def grox_parallel():
    """Дублировать сигналы: новый стартует, даже если старый ещё в догоне."""
    return bool(cfg.get("grox_parallel", False))


def drought_on():
    """Обычный сигнал 21GROX: масти нет у Игрока N игр подряд."""
    return bool(cfg.get("drought_on", True))


def five_on():
    """Сигнал «Пять»: 5 игр подряд без ничьи, 21 и 4 карт у Игрока."""
    return bool(cfg.get("five_on", False))


def five_is_clean(text):
    """У Алекса «Пять»: в игре не было ничьи, 21 и 4 карт у Игрока."""
    t = text or ""
    return not (grox_hit("x", t) or grox_hit("o", t) or grox_hit("c4", t))



GROX_STOP_KEYS = {"x", "g", "c4", "r"}  # стоп; «21» (o) не останавливает


def grox_stop_mode():
    """Стоп при заходе: off | real (гасим догоны) | virt (не гасим, только считаем)."""
    m = cfg.get("grox_stop_mode")
    if m in ("off", "real", "virt"):
        return m
    return "real" if cfg.get("grox_stop_hit") else "off"


def grox_stop_on_hit():
    return grox_stop_mode() == "real"


def grox_stop_label():
    return {"off": "ВЫКЛ", "real": "РЕАЛЬНЫЙ", "virt": "ВИРТУАЛЬНЫЙ"}.get(grox_stop_mode(), "ВЫКЛ")


_CARD_FULL_RE = re.compile(r"(10|[2-9JQKA])\s*([♠♣♥❤♦])")
_SUIT_MAP = {"♠": "♠️", "♣": "♣️", "♥": "♥️", "❤": "♥️", "♦": "♦️"}


def hand_suits_ordered(text):
    parts = re.findall(r"\(([^)]*)\)", text or "")[:2]
    return [[_SUIT_MAP[s] for _, s in _CARD_FULL_RE.findall(p)] for p in parts]


def diamond_pattern(text):
    """1) последняя Игрока ♦️ + первая Дилера ♦️
       2) первая Игрока ♦️ + последняя Дилера ♦️"""
    hands = hand_suits_ordered(text)
    if len(hands) < 2 or not hands[0] or not hands[1]:
        return False
    pl, dl = hands[0], hands[1]
    if pl[-1] == "♦️" and dl[0] == "♦️":
        return True
    if pl[0] == "♦️" and dl[-1] == "♦️":
        return True
    return False


GROX_LINES = [       # (ключ, значок, ставки, КФ по умолчанию)
    ("x", "🤝", [100, 200, 300, 400, 500], 14.2),
    ("o", "21", [100, 200, 400, 800, 1200], 4.8),   # 21 очко
    ("g", "🥇AA", [100, 200, 300, 400, 500], 52.0),  # золотое очко
    ("c4", "🃏4", [100, 200, 300, 400, 500], 7.0),   # 4 карты
    ("b", "💥", [100, 210, 430, 880, 1790], 2.3),    # перебор (у кого угодно)
    ("pb", "🙋", [100, 200, 300, 400, 500], 4.5),     # перебор у Игрока
    ("p21", "🎯И", [100, 200, 300, 400, 500], 9.0),   # Игрок получит 21 очко
]
GROX_NAMES = {"x": "Ничья", "o": "21 очко", "g": "Голд (2 туза)", "c4": "4 карты Игроку", "b": "Перебор",
              "pb": "Перебор игрока", "p21": "Игрок получит 21"}
GROX_STEP = {1: "", 2: "1️⃣", 3: "2️⃣", 4: "3️⃣", 5: "4️⃣", 6: "5️⃣", 7: "6️⃣",
             8: "7️⃣", 9: "8️⃣", 10: "9️⃣"}
GROX_STEPS_CHOICES = (3, 5, 7, 10)
GROX_MAX = 15
grox_last = {}
grox_done = {}


def grox_odds(key):
    d = {k: o for k, _, _, o in GROX_LINES}
    return float(cfg.setdefault("grox_odds", {}).get(key, d[key]))


def grox_steps(key):
    return int(cfg.setdefault("grox_steps", {}).get(key, 10 if key in ("b", "pb", "p21") else 5))


def _grox_base_stakes(n, key="g"):
    if key == "b":
        k = grox_odds("b")
        out, profit = [100], 100 * (k - 1)
        while len(out) < n:
            need = (sum(out) + profit) / (k - 1)
            out.append(int(-(-need // 10)) * 10)
        return out
    m = cfg.get("grox_mult")
    if m:
        return [max(10, int(round(100 * float(m) ** i / 10)) * 10) for i in range(n)]
    if key == "o":
        out = [100, 200, 400, 800, 1200]
        while len(out) < n:
            out.append(out[-1] + 400)
        return out[:n]
    return [100 * i for i in range(1, n + 1)]


def grox_auto_dog():
    return bool(cfg.get("grox_auto_dog", True))


# Суммы автоставки 21 Классики (как G21K_LADDERS в autobet_bot.py): Алекс считает
# посты и «Всего» по тем же ставкам, что реально ставит бот, а не по своим.
AUTO21K_LADDERS = {
    "g": [20, 30, 50, 80, 120, 170, 260, 390, 590, 880],
    "c4": [260, 390, 590, 890, 1330, 2000, 2990, 4490, 6730, 10100],
    "x": [140, 190, 280, 410, 600, 880, 1300, 1940, 2890, 4310],  # уравнена с 4 картами
    "pb": [450, 720, 1160, 1840, 2860, 4450, 6850, 10520, 16080, 24530],  # уравнена с 4 картами
    "p21": [200, 280, 420, 620, 920, 1370, 2040, 3040, 4540, 6800],  # уравнена с 4 картами
}


def grox_stakes(key):
    n = grox_steps(key)
    if AUTO21K_CHANNEL and key in AUTO21K_LADDERS:
        return AUTO21K_LADDERS[key][:n]
    base = _grox_base_stakes(n, key)
    if key in ("g", "b") or not grox_auto_dog():
        return base
    g_base = _grox_base_stakes(n, "g")
    g_odds = grox_odds("g")
    k_odds = grox_odds(key)
    g_net = g_base[-1] * g_odds - sum(g_base)
    denom = base[-1] * k_odds - sum(base)
    if denom <= 1 or g_net <= 0:
        return base
    f = g_net / denom
    return [max(10, int(round(s * f / 10.0)) * 10) for s in base]


def grox_enabled(key):
    return bool(cfg.setdefault("grox_on", {}).get(key, True))


def grox_state(chat_id):
    st = cfg.setdefault("grox", {}).setdefault(str(chat_id), {})
    st.pop("sig", None)
    st.setdefault("rows", [])
    st["rows"] = [r for r in st["rows"] if isinstance(r, dict) and "stakes" in r and "key" in r]
    st.setdefault("msg_id", None)
    st.setdefault("bank", 0.0)
    st.setdefault("start", st["bank"])
    st.setdefault("stats", {})
    st.setdefault("mprofit", {})
    st.setdefault("mprofit_since", time.strftime("%d.%m"))
    st.setdefault("virt_bank", 0.0)
    st.setdefault("src_profit", {"diam": 0.0, "five": 0.0, "drought": 0.0})
    st.setdefault("src_stats", {"diam": [0, 0], "five": [0, 0], "drought": [0, 0]})
    st.setdefault("virt_n", 0)
    st.setdefault("virt_done", [])
    st.setdefault("virt_full_bank", 0.0)
    st.setdefault("virt_full_n", 0)
    st.setdefault("virt_cont", [])
    for k, _, _, _ in GROX_LINES:
        st["stats"].setdefault(k, [0, 0])
        st["mprofit"].setdefault(k, 0.0)
    return st


def grox_hit(key, text):
    t = text or ""
    pts = [int(x) for x in re.findall(r"(\d+)\s*\(", t)[:2]]
    def _tag(letter):
        return bool(re.search(rf"(?<!\w)#{letter}(?![A-Za-z0-9_])", t, re.I))
    if key == "g":
        return _tag("G")
    if key == "b":
        return any(v > 21 for v in pts)
    if key == "pb":   # перебор у Игрока (первые очки в посте)
        return bool(pts) and pts[0] > 21
    if key == "p21":  # у Игрока ровно 21 очко
        return bool(pts) and pts[0] == 21
    if key == "c4":
        parts = re.findall(r"\(([^)]*)\)", t)[:1]
        return bool(parts) and sum(1 for ch in parts[0] if ch in "♠♣♥❤♦") == 4
    if key == "x":
        return _tag("X") or (len(pts) == 2 and pts[0] == pts[1])
    # 21 очко: #O / сумма 21 / золотое очко (#G — два туза = 21)
    return _tag("O") or _tag("G") or 21 in pts


GROX_WHAT = [("o", "21"), ("g", "G"), ("x", "X"), ("c4", "4к"), ("b", "💥"), ("pb", "🙋"), ("p21", "И21")]


def grox_what(text):
    out = []
    have = {k for k, _, _, _ in GROX_LINES}
    for k, lab in GROX_WHAT:
        if k not in have:
            continue
        try:
            if grox_hit(k, text):
                out.append(lab)
        except Exception:
            pass
    return " ".join(out)


GROX_LABEL = {"x": "🤝 Ничья", "o": "🎯 21 очко", "g": "🥇 Голд", "c4": "🃏 4 карты",
              "b": "💥 Перебор", "pb": "🙋 Перебор игрока",
              "p21": "🎯 Игрок 21"}


def grox_text(chat_id, start):
    st = grox_state(chat_id)
    rows = [r for r in st["rows"] if r["start"] == start]
    if not rows:
        return None
    sg = lambda v: ("+" if v >= 0 else "−") + money(abs(v))
    src = next((r.get("src") for r in rows if r.get("src")), "drought")
    src_name = {"diam": "♦️ Бубна", "five": "5️⃣ Пятёрка", "drought": "🃏 Нет масти"}.get(src, src)
    lines = ["<b>🎰 21GROX</b>",
             f"<i>Сигнал: {src_name}</i>",
             "",
             f"<b>▶️ Ставим с игры #{start}</b>"]
    for i, r in enumerate(rows):
        tree = "└" if i == len(rows) - 1 else "├"
        name = GROX_LABEL.get(r["key"], r["em"])
        total = len(r["stakes"])
        if r["status"] == "✅":
            what = f" · {r['what']}" if r.get("what") else ""
            lines.append(f"{tree} {name} — ✅ #{r.get('game', '?')} ({r['n']}-я игра){what} "
                         f"<b>{sg(r['result'])}</b>")
        elif r["status"] == "❌":
            lines.append(f"{tree} {name} — ❌ {total} игр мимо <b>{sg(r['result'])}</b>")
        elif r["status"] == "➖":
            if r.get("stop_hit"):
                lines.append(f"{tree} {name} — 🛑 стоп (другое зашло) <b>{sg(r.get('result', 0))}</b>")
            else:
                lines.append(f"{tree} {name} — ➖ нет итога")
        else:
            lines.append(f"{tree} {name} — ⏳ ставка <b>{money(r['stakes'][r['n']])}</b> "
                         f"на #{start + r['n']} ({r['n'] + 1}/{total})")
    lines.append("")
    if all(r["status"] != "⏳" for r in rows):
        tot = sum(r.get("result", 0) for r in rows)
        lines.append(f"🏁 Итог сигнала: <b>{sg(tot)}</b>")
    vpl = next((r.get("virt_stop_pl") for r in rows if r.get("virt_stop_pl") is not None), None)
    if vpl is not None:
        mode = grox_stop_mode()
        if mode == "virt":
            lines.append(f"📐 Вирт. «если бы стоп»: <b>{sg(vpl)}</b>")
        elif mode == "real":
            lines.append(f"📐 Вирт. «стоп на ✅» (фикс.): <b>{sg(vpl)}</b>")
    shadows = [v for v in (st.get("virt_cont") or []) if v.get("start") == start]
    if shadows:
        lines.append(f"📐 Вирт. «без стопа»: ещё считает {len(shadows)} лин. …")
    lines.append(f"💰 Всего: <b>{sg(st['bank'])}</b>")
    # рейтинг по типам сигналов
    sp = st.get("src_profit") or {}
    ss = st.get("src_stats") or {}
    rank = []
    for sk, lab in (("diam", "♦️ Бубна"), ("five", "5️⃣ Пятёрка"), ("drought", "🃏 Нет масти")):
        pr = float(sp.get(sk, 0) or 0)
        w, l = (ss.get(sk) or [0, 0])[:2]
        if pr or w or l:
            rank.append((pr, f"{lab}: {int(w)}✅/{int(l)}❌ · <b>{sg(pr)}</b>"))
    if rank:
        rank.sort(key=lambda x: -x[0])
        lines.append("🏆 Рейтинг сигналов:")
        for i, (_, line) in enumerate(rank, 1):
            lines.append(f"{i}. {line}")

    vb, vn = st.get("virt_bank", 0), st.get("virt_n", 0)
    vf, vfn = st.get("virt_full_bank", 0), st.get("virt_full_n", 0)
    if vn:
        lines.append(f"📐 Σ вирт. стоп ({vn}): <b>{sg(vb)}</b>")
    if vfn or st.get("virt_cont"):
        lines.append(f"📐 Σ вирт. без стопа ({vfn} лин.): <b>{sg(vf)}</b>"
                     + (f" · в тени {len(st.get('virt_cont') or [])}" if st.get("virt_cont") else ""))
    mp = st.get("mprofit", {})
    lines.append(f"📊 По рынкам (плюс с {st.get('mprofit_since', time.strftime('%d.%m'))}):")
    for k, _, _, _ in GROX_LINES:
        if not grox_enabled(k):
            continue
        ok, fail = st["stats"][k]
        lines.append(f"{GROX_LABEL.get(k, k)}: {ok}✅/{fail}❌ · <b>{sg(mp.get(k, 0))}</b>")
    return "\n".join(lines)


def grox_publish(chat_id, start, new):
    st = grox_state(chat_id)
    msgs = st.setdefault("msgs", {})
    text = grox_text(chat_id, start)
    pool = [p for p in PERSONAS if can_post(p, chat_id)]
    if not pool or not text:
        return
    p = pool[0]
    mid = msgs.get(str(start))
    if not new and mid:
        try:
            p["bot"].edit_message_text(text, chat_id, mid, parse_mode="HTML")
            return
        except Exception as e:
            if "not modified" in str(e):
                return
            print("21GROX правка:", e)
            return
    try:
        msgs[str(start)] = p["bot"].send_message(chat_id, text, parse_mode="HTML").message_id
        save_settings()
    except Exception as e:
        print("21GROX отправка:", e)


def grox_cleanup(chat_id):
    st = grox_state(chat_id)
    open_starts = {r["start"] for r in st["rows"] if r["status"] == "⏳"}
    st["rows"] = [r for r in st["rows"] if r["start"] in open_starts]
    st["msgs"] = {k: v for k, v in st.get("msgs", {}).items() if int(k) in open_starts}


# ---------- сигналы для автоставки 21 Классика (спецканал) ----------
# Строки AUTO21K BET/RESULT/STOP — формат как у AUTO21 (dbbet/SIGNAL21.md).
# Алекс должен быть админом канала. 0 — не слать.
AUTO21K_CHANNEL = -1003964603024  # «21 классикавто»
# какие линии дублировать в автоставку: ключ линии → код исхода
# Голд, Ничья, 4 карты, Перебор игрока (21 очко и общий Перебор — нет)
AUTO21K_OUT = {"g": "G", "x": "X", "c4": "P4", "pb": "PB", "p21": "P21"}
# сигналы шлём только из чата 21 Классики (Алекс может сидеть и в чате 21 очко)
AUTO21K_CHAT_WORDS = ("klass", "класс", "classic")
_a21k_queue = []
_a21k_lock = threading.Lock()
_a21k_early = set()
_a21k_early_win = set()   # (sid, игра), где заход отправлен по ходу игры
_a21k_stat = {"sent": 0, "errors": 0, "last_ok": "—", "last_err": "", "warned": 0.0}


def a21k_chat_ok(chat_id):
    title = str(cfg.get("groups", {}).get(str(chat_id), "")).lower()
    return any(w in title for w in AUTO21K_CHAT_WORDS)


def a21k_on(chat_id, r):
    return (AUTO21K_CHANNEL and r.get("sid") and r.get("key") in AUTO21K_OUT
            and a21k_chat_ok(chat_id))


def a21k_line(cmd, r, game, **kw):
    extra = " ".join(f"{k}={v}" for k, v in kw.items())
    return (f"AUTO21K {cmd} sig={r['sid']} game={game} out={AUTO21K_OUT[r['key']]} {extra}").strip()


# sid → (номер игры, ключ линии): ставка, отправленная в автоставку и ещё без итога.
# Если линию остановили (стоп при заходе другой линии), бот автоставки уже мог
# поставить на следующую игру — итог этой игры всё равно надо прислать, иначе
# ставка висит в «Открытых».
_a21k_pending = {}
_A21K_KEY_BY_OUT = {v: k for k, v in AUTO21K_OUT.items()}


def a21k_add(line):
    m = re.match(r"AUTO21K (BET|RESULT) sig=(\S+) game=(\d+) out=(\S+)", line)
    if m:
        cmd, sid, game, out = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if cmd == "BET":
            _a21k_pending[sid] = (game, _A21K_KEY_BY_OUT.get(out))
        elif _a21k_pending.get(sid, (None,))[0] == game:
            _a21k_pending.pop(sid, None)
    with _a21k_lock:
        _a21k_queue.append(line)


def a21k_settle_pending(chat_id, g, text, st):
    """Итог игры g для ставок автоставки, чьи линии уже остановлены/закрыты."""
    if not a21k_chat_ok(chat_id):
        return
    live = {r.get("sid") for r in st["rows"] if r.get("status") == "⏳"}
    for sid, (game, key) in list(_a21k_pending.items()):
        if game != g or sid in live or not key:
            continue
        a21k_add(f"AUTO21K RESULT sig={sid} game={g} out={AUTO21K_OUT[key]}"
                 f" win={1 if grox_hit(key, text) else 0}")


def a21k_flush():
    """Шлёт строки по одной, по порядку, в фоне."""
    with _a21k_lock:
        lines = list(_a21k_queue)
        _a21k_queue.clear()
    if not lines or not AUTO21K_CHANNEL or not PERSONAS:
        return

    def worker():
        b = PERSONAS[0].get("bot")
        for line in lines:
            err = None
            for attempt in range(3):
                try:
                    b.send_message(AUTO21K_CHANNEL, line)
                    err = None
                    break
                except Exception as e:
                    err = e
                    print("AUTO21K отправка:", e)
                    time.sleep(2)
            if err is None:
                _a21k_stat["sent"] += 1
                _a21k_stat["last_ok"] = time.strftime("%d.%m %H:%M")
                continue
            _a21k_stat["errors"] += 1
            _a21k_stat["last_err"] = str(err)[:150]
            if time.time() - _a21k_stat["warned"] > 600:
                _a21k_stat["warned"] = time.time()
                for admin in ADMIN_IDS:
                    try:
                        b.send_message(admin, "⚠️ AUTO21K: не могу отправить сигнал в канал"
                                       f" автоставки {AUTO21K_CHANNEL}: {str(err)[:200]}\n"
                                       "Проверь, что Алекс — админ канала с правом публикации.")
                    except Exception:
                        pass
    threading.Thread(target=worker, daemon=True).start()


_A21K_CARD_RE = re.compile(r"(10|[2-9JQKA])\s*[♠♣♥❤♦]")


# (чат, игра) → сколько карт было у Дилера, когда игру увидели впервые: Дилер
# «начал брать», когда карт у него стало больше — значит, Игрок уже закончил.
_a21k_dealer0 = {}


def a21k_lost_early(key, cards, pts, dealer0=None):
    """По ходу игры линия уже точно не заходит — ставку на следующую игру можно
    отправить сразу, не дожидаясь итога (в 21 Классике следующая игра начинается
    почти сразу, по итогу бот не успевает).
    cards — [карты Игрока, карты Дилера], pts — [очки Игрока, очки Дилера]."""
    if len(cards) < 2:
        return False
    pl, dl = cards[0], cards[1]
    p_pts = pts[0] if len(pts) > 0 else 0
    d_pts = pts[1] if len(pts) > 1 else 0
    if key == "g":    # у обоих видны первые две карты, и ни у кого не два туза
        return (len(pl) >= 2 and len(dl) >= 2
                and not any(c[0] == "A" and c[1] == "A" for c in (pl, dl)))
    if key == "c4":   # у Игрока уже 5+ карт, или Игрок закончил (перебор / Дилер
        #             начал брать карты) на 2–3 картах
        dealer_draws = len(dl) >= 3 or (dealer0 is not None and len(dl) > dealer0)
        player_done = p_pts > 21 or dealer_draws
        return len(pl) >= 5 or (player_done and len(pl) != 4)
    if key == "x":    # перебор у одного из них — ничьей уже не будет
        return p_pts > 21 or d_pts > 21
    if key == "pb":   # Игрок закончил (Дилер начал брать карты) без перебора
        dealer_draws = len(dl) >= 3 or (dealer0 is not None and len(dl) > dealer0)
        return dealer_draws and 0 < p_pts <= 21
    if key == "p21":  # у Игрока перебор, или он закончил не на 21
        dealer_draws = len(dl) >= 3 or (dealer0 is not None and len(dl) > dealer0)
        return p_pts > 21 or (dealer_draws and 0 < p_pts < 21)
    return False


def a21k_early(chat_id, text):
    """Игра ещё идёт, а линия уже не зайдёт — сразу RESULT win=0 и ставка на следующую."""
    if not AUTO21K_CHANNEL or not a21k_chat_ok(chat_id):
        return
    try:
        g = int(game_no_from_post(text) or 0)
    except ValueError:
        return
    if not g:
        return
    cards = [_A21K_CARD_RE.findall(h) for h in re.findall(r"\(([^)]*)\)", text or "")[:2]]
    pts = [int(x) for x in re.findall(r"(\d+)\s*\(", text or "")[:2]]
    if len(cards) == 2 and (chat_id, g) not in _a21k_dealer0:
        _a21k_dealer0[(chat_id, g)] = len(cards[1])
        for old in [k for k in _a21k_dealer0 if k[0] == chat_id and abs(k[1] - g) > 20]:
            _a21k_dealer0.pop(old, None)
    dealer0 = _a21k_dealer0.get((chat_id, g))
    with column_lock:
        st = grox_state(chat_id)
        for r in st["rows"]:
            if r["status"] != "⏳" or not a21k_on(chat_id, r):
                continue
            n = g - r["start"] + 1
            if n < 1 or n > len(r["stakes"]) or (r["sid"], g) in _a21k_early:
                continue
            if pts and ((r["key"] == "pb" and pts[0] > 21)
                        or (r["key"] == "p21" and pts[0] == 21)):
                # перебор / 21 у Игрока видны сразу — заход, следующей ставки нет
                _a21k_early.add((r["sid"], g))
                _a21k_early_win.add((r["sid"], g))
                a21k_add(a21k_line("RESULT", r, g, win=1))
                continue
            if not a21k_lost_early(r["key"], cards, pts, dealer0):
                continue
            _a21k_early.add((r["sid"], g))
            a21k_add(a21k_line("RESULT", r, g, win=0))
            if n < len(r["stakes"]):
                a21k_add(a21k_line("BET", r, g + 1, step=n + 1, max=len(r["stakes"]),
                                   kf=format(r["odds"], "g")))
    if len(_a21k_early) > 500:
        _a21k_early.clear()
    a21k_flush()



def grox_add_src_result(st, row):
    """Плюс/минус строки в рейтинг по типу сигнала (бубна / пять / масти)."""
    src = row.get("src") or "drought"
    if src not in ("diam", "five", "drought"):
        src = "drought"
    sp = st.setdefault("src_profit", {"diam": 0.0, "five": 0.0, "drought": 0.0})
    ss = st.setdefault("src_stats", {"diam": [0, 0], "five": [0, 0], "drought": [0, 0]})
    res = float(row.get("result", 0) or 0)
    sp[src] = round(float(sp.get(src, 0)) + res, 2)
    if row.get("status") == "✅":
        ss.setdefault(src, [0, 0])
        ss[src][0] = int(ss[src][0]) + 1
    elif row.get("status") == "❌":
        ss.setdefault(src, [0, 0])
        ss[src][1] = int(ss[src][1]) + 1
    # 🛑 stop_hit — только в profit, без ok/fail


def process_grox(chat_id, text):
    """Вызывается на каждый законченный пост канала 21."""
    try:
        g = int(game_no_from_post(text) or 0)
    except ValueError:
        return []
    if not g:
        return []
    last = grox_last.get(chat_id)
    done = grox_done.setdefault(chat_id, set())
    if g in done:
        return []
    # новая катушка: номер резко упал (например 1200 → 1)
    reset = last is not None and (g < last - 50 or (last > 20 and g < 5 and g < last))
    if reset:
        done.clear()
        print(f"21GROX: новая нумерация {last} → #{g}, сброс done")
    done.add(g)
    if len(done) > 200:
        keep = {x for x in done if x >= g - 80}
        done.clear()
        done.update(keep)
    # после сброса нумерации (#1) last обязан стать новым номером, иначе каждый пост = reset
    if last is None or g > last or reset:
        grox_last[chat_id] = g
    st = grox_state(chat_id)
    changed = {}
    try:
        a21k_settle_pending(chat_id, g, text, st)
    except Exception as e:
        print("AUTO21K итог остановленной ставки:", e)
    # тени «без стопа»
    if st.get("virt_cont"):
        still = []
        for vr in st["virt_cont"]:
            n = g - vr["start"] + 1
            if n < 1:
                still.append(vr)
                continue
            closed = False
            if reset or n < -50 or n > len(vr["stakes"]):
                spent = sum(vr["stakes"][:len(vr["stakes"])])
                st["virt_full_bank"] = round(st.get("virt_full_bank", 0.0) - spent, 2)
                st["virt_full_n"] = int(st.get("virt_full_n", 0)) + 1
                closed = True
            else:
                spent = sum(vr["stakes"][:n])
                if grox_hit(vr["key"], text):
                    res = round(vr["stakes"][n - 1] * vr["odds"] - spent, 2)
                    st["virt_full_bank"] = round(st.get("virt_full_bank", 0.0) + res, 2)
                    st["virt_full_n"] = int(st.get("virt_full_n", 0)) + 1
                    closed = True
                elif n >= len(vr["stakes"]):
                    st["virt_full_bank"] = round(st.get("virt_full_bank", 0.0) - spent, 2)
                    st["virt_full_n"] = int(st.get("virt_full_n", 0)) + 1
                    closed = True
                else:
                    still.append(vr)
            if closed:
                changed[vr["start"]] = False
        st["virt_cont"] = still
    for r in st["rows"]:
        if r["status"] != "⏳":
            continue
        n = g - r["start"] + 1
        if n < -50:
            r["status"] = "drop"
            continue
        if reset or n > len(r["stakes"]):
            r["status"] = "➖"
            changed[r["start"]] = False
            if a21k_on(chat_id, r):
                a21k_add(f"AUTO21K STOP sig={r['sid']}")
            continue
        if n < 1:
            continue
        r["n"] = n
        spent = sum(r["stakes"][:n])
        if grox_hit(r["key"], text):
            r["status"], r["game"] = "✅", g
            r["what"] = grox_what(text)
            r["result"] = round(r["stakes"][n - 1] * r["odds"] - spent, 2)
            st["stats"][r["key"]][0] += 1
        elif n >= len(r["stakes"]):
            r["status"], r["result"] = "❌", -spent
            st["stats"][r["key"]][1] += 1
        if a21k_on(chat_id, r):
            if (r["sid"], g) in _a21k_early:
                if r["status"] == "✅" and (r["sid"], g) not in _a21k_early_win:
                    print(f"AUTO21K: {r['sid']} #{g} — по ходу игры был промах, а в итоге заход")
            else:
                a21k_add(a21k_line("RESULT", r, g, win=1 if r["status"] == "✅" else 0))
                if r["status"] == "⏳":                      # мимо — следующий шаг догона
                    a21k_add(a21k_line("BET", r, g + 1, step=n + 1, max=len(r["stakes"]),
                                       kf=format(r["odds"], "g")))
        if r["status"] in ("✅", "❌"):
            st["bank"] = round(st["bank"] + r["result"], 2)
            grox_add_src_result(st, r)
            mp = st.setdefault("mprofit", {})
            mp[r["key"]] = round(mp.get(r["key"], 0) + r["result"], 2)
            st.setdefault("mprofit_since", time.strftime("%d.%m"))
        changed[r["start"]] = False
    mode = grox_stop_mode()
    # стоп только ничья/голд/4 карты/раздача — заход 21 (o) догоны не гасит
    hit_starts = {r["start"] for r in st["rows"]
                  if r.get("status") == "✅" and r.get("game") == g
                  and r.get("key") in GROX_STOP_KEYS}
    if mode == "real" and hit_starts:
        for r in st["rows"]:
            if r["status"] != "⏳" or r["start"] not in hit_starts:
                continue
            n = max(1, g - r["start"] + 1)
            spent = sum(r["stakes"][:min(n, len(r["stakes"]))])
            r["status"] = "➖"
            r["result"] = -float(spent)
            r["stop_hit"] = True
            if a21k_on(chat_id, r):
                # ставку этой линии на следующую игру ещё не отправили — и не шлём
                with _a21k_lock:
                    before = len(_a21k_queue)
                    _a21k_queue[:] = [x for x in _a21k_queue
                                      if not x.startswith(f"AUTO21K BET sig={r['sid']} ")]
                    dropped = before != len(_a21k_queue)
                if dropped and _a21k_pending.get(r["sid"], (0,))[0] > g:
                    _a21k_pending.pop(r["sid"], None)
                a21k_add(f"AUTO21K STOP sig={r['sid']}")
            st["bank"] = round(st["bank"] + r["result"], 2)
            grox_add_src_result(st, r)
            mp = st.setdefault("mprofit", {})
            mp[r["key"]] = round(mp.get(r["key"], 0) + r["result"], 2)
            st.setdefault("virt_cont", []).append({
                "start": r["start"], "key": r["key"], "em": r.get("em"),
                "stakes": list(r["stakes"]), "odds": r["odds"],
            })
            changed[r["start"]] = False
    if mode in ("real", "virt") and hit_starts:
        done_v = set(st.get("virt_done") or [])
        for start in hit_starts:
            if start in done_v:
                continue
            batch = [r for r in st["rows"] if r["start"] == start]
            virt = 0.0
            for r in batch:
                if r.get("status") == "✅" and r.get("game") == g:
                    virt += float(r.get("result", 0))
                elif r.get("status") == "⏳" or r.get("stop_hit"):
                    n = max(1, g - r["start"] + 1)
                    spent = sum(r["stakes"][:min(n, len(r["stakes"]))])
                    virt -= float(spent)
                elif r.get("status") in ("✅", "❌", "➖") and "result" in r:
                    virt += float(r["result"])
            st["virt_bank"] = round(st.get("virt_bank", 0.0) + virt, 2)
            st["virt_n"] = int(st.get("virt_n", 0)) + 1
            done_v.add(start)
            for r in batch:
                r["virt_stop"] = True
                r["virt_at"] = g
                r["virt_stop_pl"] = virt
            changed[start] = changed.get(start, False)
        st["virt_done"] = list(done_v)[-50:]
    st["rows"] = [r for r in st["rows"] if r.get("status") != "drop"]
    if grox_parallel():
        busy = set()
    else:
        busy = {r["key"] for r in st["rows"] if r["status"] == "⏳"}
    keys = [(k, em, stk) for k, em, stk, _ in GROX_LINES if grox_enabled(k) and k not in busy]
    if keys:
        # Три независимых сигнала — можно включать любой набор
        signals = []  # (start_game, suit, src)
        if diam_on() and diamond_pattern(text):
            signals.append((g + int(cfg.get("grox_lead", GROX_LEAD)), "♦️", "diam"))
        if five_on():
            if five_is_clean(text):
                five_streak[chat_id] = int(five_streak.get(chat_id, 0)) + 1
            else:
                five_streak[chat_id] = 0
            if int(five_streak.get(chat_id, 0)) >= FIVE_NEED:
                signals.append((g + int(cfg.get("grox_lead", GROX_LEAD)), "5️⃣", "five"))
                five_streak[chat_id] = 0
        if drought_on():
            d, total = suit_drought(chat_id)
            need = grox_need()
            fresh = [e for e, v in d.items() if v == need] if total >= need else []
            if fresh:
                signals.append((g + int(cfg.get("grox_lead", GROX_LEAD)), random.choice(fresh), "drought"))
        # дублировать: новый сигнал даже при открытом старом; иначе ждём
        started = set()
        for start_game, suit, src in signals:
            if start_game in started:
                continue
            if any(r["start"] == start_game for r in st["rows"]):
                continue
            if not grox_parallel() and any(r["status"] == "⏳" for r in st["rows"]):
                continue
            started.add(start_game)
            for k, em, stk in keys:
                stakes = grox_stakes(k) if "grox_stakes" in globals() else list(stk)
                row = {"start": start_game, "suit": suit, "key": k, "em": em,
                       "stakes": stakes, "odds": grox_odds(k),
                       "n": 0, "status": "⏳",
                       "sid": time.strftime("%d%m") + f"-{start_game}{k}",
                       "src": src}
                st["rows"].append(row)
                if a21k_on(chat_id, row):
                    a21k_add(a21k_line("BET", row, start_game, step=1, max=len(stakes),
                                       kf=format(row["odds"], "g")))
            changed[start_game] = True
    if changed:
        save_settings()
    a21k_flush()
    return sorted(changed.items())


def a21k_panel_line():
    st = _a21k_stat
    if not AUTO21K_CHANNEL:
        return "📡 Автоставка 21 Классика: канал не задан (AUTO21K_CHANNEL)"
    return (f"📡 Автоставка (канал {AUTO21K_CHANNEL}): отправлено {st['sent']},"
            f" последнее {st['last_ok']}, ошибок {st['errors']}"
            + (f" — {st['last_err']}" if st["last_err"] else ""))


def grox_panel_text():
    lines = ["🥇 <b>21GROX</b> — работает всегда\n",
             a21k_panel_line(),
             f"Догон ставок: {('×' + format(float(cfg['grox_mult']), 'g')) if cfg.get('grox_mult') else 'стандарт'}",
             f"⚖️ Догон автомат: {onoff(grox_auto_dog())}",
             f"5️⃣ Сигнал «Пять»: {onoff(five_on())} "
             f"({FIVE_NEED} игр подряд без ничьи / 21 / 4 карт)",
             f"♦️ Стратегия бубна: {onoff(diam_on())} "
             f"(♦️ комбинация → сигнал через {DIAM_LEAD} игр)",
             f"🛑 Стоп при заходе: <b>{grox_stop_label()}</b> (21 не стопит)",
             "   • РЕАЛЬНЫЙ — гасим догоны; вирт. «если бы не стоп»",
             "   • ВИРТУАЛЬНЫЙ — догоны идут; вирт. «если бы стоп»",
             f"⏭ Старт ставок: через {int(cfg.get('grox_lead', GROX_LEAD))} игр (#{100}→#{102})",
             f"📚 Дублировать сигналы: {onoff(grox_parallel())}",
             f"Сигналы можно включать вместе (1 / 2 / 3):",
             f"  • нет масти {grox_need()} игр: {onoff(drought_on())}",
             f"  • бубна: {onoff(diam_on())}",
             f"  • пять: {onoff(five_on())}"]
    for k, em, stk, _ in GROX_LINES:
        lines.append(f"{'✅' if grox_enabled(k) else '⛔'} {em} {GROX_NAMES[k]}: "
                     f"{grox_steps(k)} игр ({'-'.join(str(x) for x in grox_stakes(k))}), КФ {grox_odds(k):g}")
    for cid, title in cfg["groups"].items():
        st = grox_state(cid) if cid in cfg.get("grox", {}) else None
        b = (st or {}).get("bank", 0)
        vb = (st or {}).get("virt_bank", 0)
        vn = (st or {}).get("virt_n", 0)
        vf = (st or {}).get("virt_full_bank", 0)
        vfn = (st or {}).get("virt_full_n", 0)
        vc = len((st or {}).get("virt_cont") or [])
        lines.append(f"\n<b>{title}</b>: всего {'+' if b >= 0 else ''}{money(b)}")
        if vn:
            lines.append(f"📐 Вирт. «стоп на ✅» ({vn}): {'+' if vb >= 0 else ''}{money(vb)}")
        if vfn or vc:
            lines.append(f"📐 Вирт. «без стопа»: {'+' if vf >= 0 else ''}{money(vf)}"
                         + (f", в тени {vc}" if vc else f", закрыто {vfn}"))
        wait = [r for r in (st or {}).get("rows", []) if r.get("status") == "⏳"]
        if wait:
            lines.append("Сейчас идёт сигнал с игры #" + str(wait[0]["start"]) + ": "
                         + ", ".join(f"{r['em']} шаг {r['n'] + 1}" for r in wait))
        else:
            try:
                d, total = suit_drought(int(cid))
                best = max(d.values()) if d else 0
                lines.append(f"Ждёт сигнал: серия без масти {best}/{grox_need()} (в памяти {total})")
            except Exception:
                pass
    return "\n".join(lines)


def grox_panel_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(btn(f"🃏 Нет масти: {onoff(drought_on())}", "drought:toggle"))
    kb.add(btn(f"5️⃣ Сигнал «Пять»: {onoff(five_on())}", "five:toggle"))
    kb.add(btn(f"♦️ Стратегия бубна: {onoff(diam_on())}", "diam:toggle"))
    kb.add(btn(f"📚 Дублировать сигналы: {onoff(grox_parallel())}", "grox:parallel"))
    kb.add(btn(f"🛑 Стоп при заходе: {grox_stop_label()} (сменить)", "grox:stophit"))
    kb.add(btn(f"⚖️ Догон автомат: {onoff(grox_auto_dog())}", "grox:autodog"))
    kb.add(btn("♻️ Сбросить статистику 21GROX", "grox:statsreset"))
    kb.add(btn("Сколько игр нет масти 👇", "noop"))
    kb.row(*[btn(("✅ " if grox_need() == n else "") + f"{n} игр", f"gxn:{n}") for n in (2, 3, 4, 5)])
    tg = [btn(("✅ " if grox_enabled(k) else "⛔ ") + GROX_NAMES[k].split(" (")[0], f"gxt:{k}")
          for k, _, _, _ in GROX_LINES]
    for i in range(0, len(tg), 3):
        kb.row(*tg[i:i + 3])
    for k, em, _, _ in GROX_LINES:
        step = 1.0 if k == "g" else 0.05 if k == "o" else 0.01 if k == "b" else 0.5
        kb.add(btn("➖", f"gxo:{k}:-{step}"), btn(f"КФ {GROX_NAMES[k]} {grox_odds(k):g}", "noop"),
               btn("➕", f"gxo:{k}:{step}"))
    gm = cfg.get("grox_mult")
    kb.add(btn("Догон — сколько игр 👇", "noop"))
    for k, em, _, _ in GROX_LINES:
        ch = (5, 7, 10, 12) if k == "b" else (3, 5, 7, 10)
        kb.row(btn(em, "noop"), *[btn(("✅" if grox_steps(k) == n else "") + str(n), f"gxs:{k}:{n}")
                                 for n in ch])
    kb.add(btn("Догон ставок 👇", "noop"))
    kb.row(*[btn(("✅ " if (gm or 0) == v else "") + lab, f"gxm:{v}")
             for v, lab in ((0, "стандарт"), (1.5, "×1.5"), (2, "×2"), (2.5, "×2.5"))])
    kb.add(btn("♻️ Сбросить банк", "gxb:reset"), btn("✏️ Ввести банк", "gxb:set"), row_width=2)
    kb.add(back())
    return kb



def process_column_post(chat_id, text):
    """Вызывается на каждый пост/правку канала. Работает ТОЛЬКО когда игра закончилась:
    проверяет заход/незаход по всем строкам, добавляет новый прогноз и публикует
    одной правкой. Посты «идёт раздача» столбик не трогают."""
    if not game_is_finished(text):
        try:
            a21k_early(chat_id, text)       # раздача идёт — быстрый промах для автоставки
        except Exception as e:
            print("AUTO21K по ходу игры:", e)
        return
    with column_lock:
        voided = void_stale_rows(chat_id, text)
        changed = update_columns_from_post(chat_id, text) | voided
        added = auto_column_after_post(chat_id, text)
        keys = set(changed) | set(added)
        for (cid, pk), blocks in list(column_archive.items()):
            if cid != chat_id:
                continue
            for b in blocks:
                if b.pop("fresh", False):
                    keys.add(("arch", pk, id(b)))
        keys |= {k for c, k in column_dirty if c == chat_id}
        # архивные ключи публикуем первыми, чтобы старый пост закрылся до нового
        keys = sorted(keys, key=lambda k: 0 if isinstance(k, tuple) else 1)
        column_dirty.difference_update({(chat_id, k) for k in keys if not isinstance(k, tuple)})
    for pkey in keys:
        try:
            if isinstance(pkey, tuple):
                _edit_archived(chat_id, pkey[1], pkey[2])
                continue
            hit = (chat_id, pkey) in column_hits
            column_hits.discard((chat_id, pkey))
            # новая ставка в режиме «нет масти» или в марафоне — новым сообщением вниз
            col = columns[chat_id].get(pkey) or []
            new_bet = pkey in added and col and (cfg.get("dr_on") or col[-1].get("mar"))
            _do_publish_column(chat_id, pkey, as_new=hit or bool(new_bet))
        except Exception as e:
            print(f"Ошибка обновления столбика {pkey}:", e)
    try:
        process_dbust(chat_id, text)          # «перебор дилера»
    except Exception as e:
        print("Перебор дилера:", e)
    # сигнал 21GROX — работает всегда, независимо от настроек
    try:
        with column_lock:
            acts = process_grox(chat_id, text)
        for start, is_new in acts:
            grox_publish(chat_id, start, is_new)
        if acts:
            with column_lock:
                grox_cleanup(chat_id)
                save_settings()
    except Exception as e:
        print("21GROX:", e)


def format_column(chat_id, persona_key, title=None):
    """Рисует текущий пост-столбик персонажа (до 15 строк, догон x3)"""
    col = columns[chat_id].get(persona_key) or []
    if title is None:
        p = BY_KEY.get(persona_key)
        title = pname(p) if p else "Игрок"
    start = column_start.get((chat_id, persona_key))
    return format_rows(col, title, start, get_bank(chat_id, persona_key))


def mar_sign(v):
    return ("+" if v >= 0 else "−") + str(round(abs(v)))


def format_marathon(col, title):
    """Пост марафона:  42♣️132~278~588 1⃣✅ 1118"""
    def n(v):
        return str(round(v))
    lines = [f"<b>{title}</b> марафон {n(col[0].get('mar_start', 0))}₽"]
    end = None
    for row in col:
        g2 = str(row["game"])[-2:]
        stakes = "~".join(str(x) for x in row["stakes"])
        step = int(row.get("step", 1))
        key = KEYCAP.get(step, str(step))
        if row["status"] == "✅":
            lines.append(f"{g2}{row['suit']}{stakes}{key}✅ {n(row['bank_after'])}")
        elif row["status"] == "❌":
            lines.append(f"{g2}{row['suit']}{stakes}❌ {n(row['bank_after'])}")
        elif row["status"] == "⚪":
            lines.append(f"{g2}{row['suit']}{stakes}⚪ не сыграна")
        else:
            lines.append(f"{g2}{row['suit']}{stakes}{key}⏳")
        if row.get("mar_end"):
            end = row["mar_end"]
    if end:
        if end["ok"]:
            lines += ["Марафон завершён", "   успешно 🥳🍺",
                      f"🔥 {n(end['start'])} - {n(end['end'])} 🔥",
                      f"   📊{end['wins']}/{end['n']}✅"]
        else:
            lines += ["Марафон слит 💥",
                      f"🔥 {n(end['start'])} - {n(end['end'])}",
                      f"   📊{end['wins']}/{end['n']}✅"]
        if "net" in end:
            lines.append(f"💵 Чистыми за марафон: {mar_sign(end['net'])}")
    else:
        done = sum(1 for r in col if r["status"] in ("✅", "❌"))
        lines.append(f"   📊{done}/{int(cfg.get('mar_len', 15))}")
    # итог по всем марафонам — внизу каждого поста
    ms = cfg.get("mar_stats", {}).get(col[0].get("mar_key", ""), {})
    if ms.get("ok") or ms.get("fail"):
        won, lost = ms.get("won", 0), ms.get("lost", 0)
        lines += ["",
                  f"🏆 Марафонов: {ms.get('ok', 0) + ms.get('fail', 0)} — зашло {ms.get('ok', 0)}✅ / "
                  f"слито {ms.get('fail', 0)}❌",
                  f"💰 Заработано: +{round(won)} · Потеряно: −{round(lost)}",
                  f"📈 Итого за марафоны: {mar_sign(won - lost)}"]
    return "\n".join(lines)


def format_rows(col, title, start=None, end=None):
    if not col:
        return None
    if col[0].get("mar"):
        return format_marathon(col, title)
    fin = cfg.get("fin_on", True) and start is not None
    streak = 0
    for row in reversed(col):
        if row["status"] in ("⏳", "⚪"):
            continue
        if row["status"] == "❌":
            streak += 1
        else:
            break
    hits = sum(1 for r in col if r["status"] == "✅")
    misses = sum(1 for r in col if r["status"] == "❌")
    head = f"<b>{title}</b> флэт {cfg.get('flat_pct', 1.0):g}%"
    if cfg.get("loss_up_pct", 0):
        head += f" (+{cfg['loss_up_pct']:g}% после ❌)"
    if streak:
        head += f" +{streak}"
    if hits or misses:
        head += f"  ({hits}✅/{misses}❌)"
    STEP_EMOJI = {1: "", 2: "1️⃣", 3: "2️⃣"}
    lines = [head]
    if fin:
        lines.append(f"💰 Старт: {money(start)}")
    for row in col[-COLUMN_MAX:]:
        step = int(row.get("step", 1))
        digit = STEP_EMOJI.get(step, str(step))
        # Строка ведёт свой догон, подставляется только цифра:
        #   446♦️        ждём 446
        #   446♦️1️⃣      мимо, ждём 447
        #   446♦️1️⃣✅    зашло на 1-м догоне
        #   448♠️2️⃣❌    2-й догон мимо
        amt = ""
        if fin and "result" in row:
            r = row["result"]
            amt = f" {'+' if r >= 0 else ''}{money(r)}"
        if row["status"] == "✅":
            lines.append(f"{row['game']}{row['suit']}{digit}✅{amt}")
        elif row["status"] == "❌":
            lines.append(f"{row['game']}{row['suit']}{digit}❌{amt}")
        elif row["status"] == "⚪":
            lines.append(f"{row['game']}{row['suit']}⚪ не сыграна")
        else:
            lines.append(f"{row['game']}{row['suit']}{digit}")
    if fin and end is not None:
        diff = end - start
        lines.append(f"💰 Итог: {money(end)} ({'+' if diff >= 0 else ''}{money(diff)})")
    return "\n".join(lines)


@listener.edited_message_handler(func=lambda m: in_group(m) and m.is_automatic_forward,
                                 content_types=["text", "photo"])
def on_post_edit(m):
    # статистика дописывает результат правкой поста — обновляем текст
    text = m.text or m.caption or ""
    posts[m.chat.id][m.message_id] = text
    threading.Thread(target=process_column_post, args=(m.chat.id, text), daemon=True).start()


def player_suits(text):
    """Масти карт игрока = первая скобка в посте вида #N280. 2(9♣ 3♣) - 9(9♣ K♥)"""
    mm = re.search(r"\(([^)]*)\)", text or "")
    if not mm:
        return []
    return [SUIT_SYMBOLS[ch] for ch in mm.group(1) if ch in SUIT_SYMBOLS]


def suit_stats(chat_id, last_n=20):
    games = [player_suits(t) for t in list(posts[chat_id].values())[-last_n:]]
    games = [g for g in games if g]
    cnt = {e: 0 for e in ("♠️", "♣️", "♥️", "♦️")}
    for g in games:
        for e in set(g):
            cnt[e] += 1
    return len(games), cnt


def pick_suits(cnt, persona_key=None):
    """Одна лучшая масть на игру: реже выпадала; у персонажей чуть разный выбор."""
    pool = list(cnt) if cnt else ["♠️", "♣️", "♥️", "♦️"]
    if not cnt:
        return [random.choice(pool)]
    # веса: реже → выше; небольшой разброс по персонажу
    weights = []
    for e in pool:
        w = 1.0 / (cnt.get(e, 0) + 1)
        if persona_key is not None:
            w *= 0.85 + 0.3 * ((hash(persona_key + e) % 100) / 100.0)
        weights.append(w)
    return [random.choices(pool, weights=weights, k=1)[0]]


_NO_GAP = [False]   # для режима «нет масти»: строка на следующую игру разрешена


def finished_history(chat_id, n=30):
    """Последние законченные игры канала по порядку: [(номер, текст), ...]."""
    # порядок — как посты пришли из канала (а не по номеру): после сброса нумерации
    # (#1440 → #1) по номеру старые игры оказывались «последними» и сигналы вставали
    order, texts = [], {}
    for t in list(posts[chat_id].values()):
        if not game_is_finished(t):
            continue
        try:
            g = int(game_no_from_post(t) or 0)
        except ValueError:
            continue
        if not g:
            continue
        if g not in texts:
            order.append(g)
        texts[g] = t
    for i in range(len(order) - 1, 0, -1):       # после сброса нумерации — только новый цикл
        if order[i] < order[i - 1] - 50:
            order = order[i:]
            break
    return [(g, texts[g]) for g in order][-n:]


def suit_drought(chat_id):
    """{масть: сколько последних игр подряд её не было у Игрока}, всего игр в истории"""
    hist = finished_history(chat_id)
    out = {}
    for e in ("♠️", "♣️", "♥️", "♦️"):
        n = 0
        for _, t in reversed(hist):
            if e in player_suits(t):
                break
            n += 1
        out[e] = n
    return out, len(hist)


def burned_suits(chat_id, col):
    """Масти, на которые уже ставили по «нет масти» и проиграли, а после этого
    масть ещё ни разу не выпала. На них повторно не ставим — ждём, пока появится."""
    hist = finished_history(chat_id)
    out = set()
    for row in col[-15:]:
        if row.get("status") != "❌" or "drought" not in row:
            continue
        try:
            last = int(row.get("cur_game", row["game"]))
        except ValueError:
            continue
        if hist and last > max(n for n, _ in hist) + 50:
            continue          # ставка из прошлого цикла нумерации (до сброса на #1) — не мешает
        if not any(n > last and row["suit"] in player_suits(t) for n, t in hist):
            out.add(row["suit"])
    return out


def drought_column(chat_id, g, need=None):
    """Режим «нет масти N игр»: если масти не было N игр подряд — ставка на неё
    на СЛЕДУЮЩУЮ игру. Пока прошлая ставка не закрыта — новой нет."""
    added = set()
    need = int(need or cfg.get("dr_suit_n", 3))
    d, total = suit_drought(chat_id)
    if total < need:
        return added
    nxt = str(int(g) + 1)
    for p in [p for p in active_personas() if can_post(p, chat_id)]:
        col = columns[chat_id].get(p["key"]) or []
        if any(r["status"] == "⏳" for r in col):
            continue
        # одна ставка на масть: проигранную масть пропускаем, пока она не выпадет
        burned = burned_suits(chat_id, col)
        cand = {e: v for e, v in d.items() if v >= need and e not in burned}
        if not cand:
            continue
        best = max(cand.values())
        suit = random.choice([e for e, v in cand.items() if v == best])
        marker = (chat_id, p["key"])
        seen = auto_prediction_posted[marker]
        if time.time() - seen.get(nxt, 0) < DUP_WINDOW:
            continue
        _NO_GAP[0] = True
        try:
            ok = add_column_picks(chat_id, p["key"], nxt, [suit])
        finally:
            _NO_GAP[0] = False
        if ok:
            columns[chat_id][p["key"]][-1]["drought"] = best
            seen[nxt] = time.time()
            added.add(p["key"])
    return added


def auto_column_after_post(chat_id, text):
    """По итогу игры добавляет новую строку прогноза (без публикации).
    Возвращает ключи персонажей, у которых появилась строка."""
    added = set()
    g = game_no_from_post(text)
    if not g or not game_is_finished(text):
        return added
    try:
        # Закончилась 444 → прогноз на 446 (LEAD = 2)
        target_game = str(int(g) + LEAD)
    except ValueError:
        return added

    if not cfg["enabled"] or not cfg.get("auto_column", True) or not cfg.get("forecasts", True):
        return added

    # марафон «нет масти N игр»: ставим только масть, которой не было N игр
    if marathon_on() and int(cfg.get("mar_dr", 0) or 0):
        try:
            return drought_column(chat_id, g, int(cfg["mar_dr"]))
        except Exception as e:
            print("Марафон «нет масти»:", e)
            return added


    if cfg.get("dr_on"):
        try:
            return drought_column(chat_id, g)
        except Exception as e:
            print("Режим «нет масти»:", e)
            return added

    pool = [p for p in active_personas() if can_post(p, chat_id)]
    if not pool:
        return added

    _, cnt = suit_stats(chat_id)
    for p in pool:
        try:
            marker = (chat_id, p["key"])
            seen = auto_prediction_posted[marker]
            if time.time() - seen.get(target_game, 0) < DUP_WINDOW:
                continue   # прогноз на эту игру уже есть (повторная правка поста)
            suits = pick_suits(cnt, persona_key=p["key"])
            if add_column_picks(chat_id, p["key"], target_game, suits):
                seen[target_game] = time.time()
                for old in [k for k, t in seen.items() if time.time() - t > DUP_WINDOW]:
                    del seen[old]
                added.add(p["key"])
        except Exception as e:
            print(f"auto_column {pname(p)}:", e)
            bump("errors")
    return added


def forecast_question(text):
    low = (text or "").lower()
    num = re.search(r"(?<!\d)(\d{1,5})(?!\d)", low)   # «284игре», «284 игра», «в 10»
    if not num:
        return None
    if re.search(r"масть|прогноз|какая|что (будет|выпадет|зайдёт|зайдет)|выпадет|зайд[её]т", low):
        return num.group(1)
    return None


def answer_forecast(p, chat_id, user_name, user_text, reply_to, game_no):
    time.sleep(random.randint(4, 12))
    total, cnt = suit_stats(chat_id)
    suits = pick_suits(cnt, persona_key=p["key"])
    stat_line = ", ".join(f"{e} {c}" for e, c in cnt.items())
    pick = " ".join(suits)
    try:
        prompt = (
            f"Ты пишешь реплику персонажа {pname(p)} ({pchar(p)}).\n"
            f"{names_rule(chat_id)}\n\n"
            f"В чате обсуждают прогноз масти игрока. "
            f"Участник {user_name} спросил: «{user_text}».\n"
            f"Статистика масти игрока за последние {total} игр (в скольких играх была масть): "
            f"{stat_line}.\n"
            f"Твой прогноз на {game_no} игру: {pick}.\n\n"
            f"Напиши ответ {user_name} в своём характере: обязательно начни с "
            f"«{game_no} игра: {pick}», можно сослаться на статистику, "
            f"уверенно или с юмором — как в обычном игровом чате. "
            f"До 25 слов. Только текст реплики."
        )
        text = clean_reply(ask_ai(chat_id, prompt, 120))
    except Exception as e:
        print("Ошибка прогноза:", e)
        text = ""
    if not text:   # ИИ недоступен или отказался — простой ответ без ИИ
        text = f"{game_no} игра: {pick}"
    send_as(p, chat_id, text, reply_to)
    # Личный столбик этого персонажа
    add_column_picks(chat_id, p["key"], game_no, suits)
    time.sleep(random.uniform(1.5, 4))
    # первое появление или правка уже висящего столбика
    publish_column(p, chat_id)


@listener.message_handler(func=lambda m: in_group(m) and not m.is_automatic_forward
                          and m.from_user and not m.from_user.is_bot
                          and m.sender_chat is None,
                          content_types=["text"])
def on_user(m):
    remember_group(m.chat)
    name = m.from_user.first_name or "Участник"
    history[m.chat.id].append((name, m.text))
    learn_slang(m.chat.id, m.text)
    user_times[m.chat.id].append(time.time())
    r = m.reply_to_message
    low = (m.text or "").lower()
    # Запрос столбика: «столбик», «колонка», «мои масти»
    if cfg["enabled"] and re.search(r"столбик|колонк|мои масти|твой столбик", low):
        pool = [x for x in active_personas() if can_post(x, m.chat.id)]
        # если ответили конкретному персонажу — его столбик, иначе случайный с данными
        replied = (BY_ID.get(r.from_user.id) if r and r.from_user else None)
        if replied and replied["key"] not in cfg["off"] and replied in pool:
            candidates = [replied]
        else:
            candidates = [x for x in pool if columns[m.chat.id].get(x["key"])]
            if not candidates:
                candidates = pool

        def _send_col(p):
            time.sleep(random.uniform(2, 6))
            col_text = format_column(m.chat.id, p["key"], title=pname(p))
            try:
                if col_text:
                    publish_column(p, m.chat.id)
                else:
                    p["bot"].send_message(
                        m.chat.id,
                        "Пока пусто — сначала спроси масть на игру",
                        reply_to_message_id=m.message_id,
                        allow_sending_without_reply=True,
                    )
            except Exception as e:
                print("Ошибка отправки столбика:", e)

        if candidates:
            threading.Thread(
                target=_send_col, args=(random.choice(candidates),), daemon=True
            ).start()
        return
    game_no = forecast_question(m.text)
    if cfg["enabled"] and cfg.get("forecasts", True) and game_no:
        now = time.time()
        replied = (BY_ID.get(r.from_user.id) if r and r.from_user else None)
        if replied and (replied["key"] in cfg["off"] or not persona_fits(replied, m.chat.id)):
            replied = None
        pool = [replied] if replied else [x for x in active_personas()
                                          if can_post(x, m.chat.id)]
        if pool and now - last_forecast[m.chat.id] >= FORECAST_COOLDOWN:
            last_forecast[m.chat.id] = now
            threading.Thread(target=answer_forecast,
                             args=(random.choice(pool), m.chat.id, name, m.text,
                                   m.message_id, game_no), daemon=True).start()
        return
    if (cfg["enabled"] and cfg["user_reply"] and r and r.from_user
            and r.from_user.id in BY_ID
            and BY_ID[r.from_user.id]["key"] not in cfg["off"]
            and persona_fits(BY_ID[r.from_user.id], m.chat.id)
            and random.random() < USER_REPLY_CHANCE):
        threading.Thread(target=answer_user,
                         args=(BY_ID[r.from_user.id], m.chat.id, name, m.text, m.message_id),
                         daemon=True).start()


@listener.message_handler(func=lambda m: in_group(m) and m.from_user
                          and not m.from_user.is_bot, content_types=["sticker"])
def on_group_sticker(m):
    remember_group(m.chat)
    name = m.from_user.first_name or "Участник"
    history[m.chat.id].append((name, f"[стикер {m.sticker.emoji or ''}]"))
    user_times[m.chat.id].append(time.time())
    sset = m.sticker.set_name
    if cfg.get("learn_stickers") and sset and sset not in cfg["sticker_sets"]:
        cfg["sticker_sets"].append(sset)
        save_settings()
        print(f"Добавлен стикерпак из группы: {sset}")


# ================= ПАНЕЛЬ УПРАВЛЕНИЯ =================
def onoff(v):
    return "ВКЛ" if v else "ВЫКЛ"


def btn(text, data):
    return types.InlineKeyboardButton(text, callback_data=data)


def back(to="menu:main"):
    return btn("⬅️ Назад", to)


# ----- главный экран -----
def main_text():
    busy = sum(1 for s in chat_state.values() if s["busy"])
    return (
        "🎛 <b>Панель персонажей</b>\n\n"
        f"Статус: {'🟢 работают' if cfg['enabled'] else '🔴 выключены'}\n"
        f"Шанс разговора: {int(cfg['dialog_chance'] * 100)}%\n"
        f"Пауза между разговорами: {cfg['cooldown'] // 60} мин\n"
        f"Авто-тишина: {onoff(cfg['auto_quiet'])}\n"
        f"Ответы людям: {onoff(cfg['user_reply'])}\n"
        f"Прогнозы масти: {onoff(cfg.get('forecasts', True))}\n"
        f"Режим «нет масти»: {onoff(cfg.get('dr_on'))}, после {cfg.get('dr_suit_n', 3)} игр\n"
        f"Шутки: {int(cfg.get('joke_chance', 0) * 100)}% разговоров\n"
        f"Стикеры: {int(cfg.get('sticker_chance', 0) * 100)}%, паков: {len(cfg['sticker_sets'])}\n"
        f"🃏 Нет масти: {onoff(drought_on())} · 5️⃣ Пять: {onoff(five_on())} · ♦️ Бубна: {onoff(diam_on())}\n"
        f"🛑 Стоп при заходе: {grox_stop_label()}\n"
        f"Активные: {', '.join(pname(p) for p in active_personas()) or 'никого'}\n"
        f"Групп: {len(cfg['groups'])}, сейчас говорят в: {busy}"
    )


def main_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(btn("🔴 Выключить" if cfg["enabled"] else "🟢 Включить", "toggle"))
    kb.add(btn("➖", "ch-"), btn(f"Шанс {int(cfg['dialog_chance'] * 100)}%", "noop"),
           btn("➕", "ch+"))
    kb.add(btn("➖", "cd-"), btn(f"Пауза {cfg['cooldown'] // 60} мин", "noop"),
           btn("➕", "cd+"))
    kb.add(btn(f"🤫 Авто-тишина: {onoff(cfg['auto_quiet'])}", "quiet"))
    kb.add(btn(f"💬 Ответы людям: {onoff(cfg['user_reply'])}", "ureply"))
    kb.add(btn(f"🔮 Прогнозы масти: {onoff(cfg.get('forecasts', True))}", "fcast"))
    kb.add(btn(f"🗣 Учить жаргон чата: {onoff(cfg.get('slang_on', True))}", "slang"))
    kb.add(btn("➖", "jk-"), btn(f"😂 Шутки {int(cfg.get('joke_chance', 0) * 100)}%", "noop"),
           btn("➕", "jk+"))
    kb.add(btn("➖", "sk-"), btn(f"🎭 Стикеры {int(cfg.get('sticker_chance', 0) * 100)}%", "noop"),
           btn("➕", "sk+"))
    kb.add(btn("👤 Персонажи", "menu:personas"), btn("🗂 Темы групп", "menu:groups"),
           row_width=2)
    kb.add(btn("🧷 Стикерпаки", "menu:stickers"), btn("💰 Финансы", "menu:fin"), row_width=2)
    kb.add(btn("🥇 21GROX — настройки", "menu:grox"))
    kb.add(btn(f"🃏 Нет масти: {onoff(drought_on())}", "drought:toggle"),
           btn(f"5️⃣ Пять: {onoff(five_on())}", "five:toggle"),
           row_width=2)
    kb.add(btn(f"♦️ Бубна: {onoff(diam_on())}", "diam:toggle"),
           btn(f"📚 Дубль: {onoff(grox_parallel())}", "grox:parallel"),
           btn(f"🛑 Стоп: {grox_stop_label()}", "grox:stophit"),
           row_width=2)
    kb.add(btn(f"💥 Перебор дилера: {onoff(db_cfg('on', False))}", "menu:dbust"))
    kb.add(btn(f"🏃 Ставка, когда нет масти N игр: {onoff(cfg.get('dr_on'))}", "drtoggle"))
    dn = int(cfg.get("dr_suit_n", 3))
    kb.row(*[btn(("✅ " if dn == v else "") + f"{v} игр", f"drn:{v}") for v in (2, 3, 4, 5, 6)])
    kb.add(btn("🎬 Разговор сейчас", "now"), btn("📊 Статистика", "stats"),
           row_width=2)
    kb.add(btn("🔄 Обновить", "menu:main"))
    return kb


# ----- персонажи -----
def personas_text():
    lines = ["👤 <b>Персонажи</b>\n", "Выбери, кого настроить:"]
    return "\n".join(lines)


def personas_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for p in PERSONAS:
        mark = "✅" if p["key"] not in cfg["off"] else "❌"
        kb.add(btn(f"{mark} {pname(p)}", "pe:" + p["key"]))
    kb.add(back())
    return kb


def persona_text(p):
    return (
        f"👤 <b>{pname(p)}</b>\n\n"
        f"Статус: {'✅ активен' if p['key'] not in cfg['off'] else '❌ выключен'}\n"
        f"Игра: 🎲 {GAME_NAMES.get(pgame(p), pgame(p))}\n"
        f"Характер: {pchar(p)}"
    )


def persona_kb(p):
    k = p["key"]
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(btn("✏️ Имя", "pn:" + k), btn("🎭 Характер", "pc:" + k))
    kb.add(btn("❌ Выключить" if k not in cfg["off"] else "✅ Включить", "pt:" + k))
    kb.add(btn(f"🎲 Игра: {GAME_NAMES.get(pgame(p), pgame(p))} (сменить)", "pg:" + k))
    kb.add(back("menu:personas"))
    return kb


# ----- группы -----
def groups_text():
    if not cfg["groups"]:
        return ("🗂 <b>Темы групп</b>\n\nПока нет ни одной группы. Они появятся "
                "здесь сами после первого поста или сообщения в группе.")
    return "🗂 <b>Темы групп</b>\n\nВыбери группу:"


def groups_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for cid, title in cfg["groups"].items():
        mark = "📝" if cid in cfg["topics"] else "🤖"
        kb.add(btn(f"{mark} {title}", "gr:" + cid))
    kb.add(back())
    return kb


def group_text(cid):
    title = cfg["groups"].get(cid, cid)
    topic = cfg["topics"].get(cid)
    return (
        f"🗂 <b>{title}</b>\n\n"
        f"Тема: {topic if topic else '🤖 авто (ИИ сам понимает по постам)'}"
    )


def group_kb(cid):
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(btn("✏️ Задать тему", "gt:" + cid), btn("🤖 Авто", "ga:" + cid))
    kb.add(back("menu:groups"))
    return kb


# ----- стикерпаки -----
# ----- финансы -----
def fin_text():
    banks = []
    for cid, title in cfg["groups"].items():
        for p in PERSONAS:
            k = bank_key(cid, p["key"])
            if k in cfg["bank"]:
                banks.append(f"• {title} — {pname(p)}: {money(cfg['bank'][k])}")
    return (
        "💰 <b>Финансы столбика</b>\n\n"
        f"Показывать в посте: {onoff(cfg.get('fin_on', True))}\n"
        + (f"🏃 <b>Режим: МАРАФОН</b> — банк {round(cfg.get('mar_start', 1000))}₽ делится на 3 ставки "
           f"догона, {int(cfg.get('mar_len', 15))} цепочек\n"
           + (f"Ставим только масть, которой не было {int(cfg.get('mar_dr', 0))} игр подряд\n\n"
              if int(cfg.get('mar_dr', 0) or 0) else "Ставим каждую игру\n\n")
           if cfg.get("marathon") else "") +
        f"Система: динамический флэт, без догона\n"
        f"После проигрыша: " + (f"+{cfg.get('loss_up_pct', 0):g}% к следующей ставке, "
                               f"после захода — снова базовая\n"
                               if cfg.get('loss_up_pct', 0) else "ставку не повышать\n") +
        f"Ставка: {cfg.get('flat_pct', 1.0):g}% от текущего банка персонажа\n"
        f"(при банке {money(cfg['start_bank'])} это "
        f"{money(cfg['start_bank'] * cfg.get('flat_pct', 1.0) / 100)})\n"
        f"Коэффициент: {cfg['odds']}\n"
        f"Стартовый банк: {money(cfg['start_bank'])}\n\n"
        + ("Текущий банк:\n" + "\n".join(banks) if banks else "Банк ещё не менялся")
    )


FLAT_PRESETS = [0.5, 1, 1.5, 2, 3, 4, 5, 10]   # кнопки выбора % от банка
UP_PRESETS = [0, 10, 20, 25, 30, 50, 75, 100]  # кнопки: на сколько % поднять ставку после ❌


def fin_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(btn(f"💰 В посте: {onoff(cfg.get('fin_on', True))}", "fin:on"))
    kb.add(btn(f"🏃 Марафон: {onoff(cfg.get('marathon'))}", "fin:mar"),
           btn("🔁 Новый марафон", "fin:marnew"), row_width=2)
    kb.add(btn("♻️ Сбросить статистику марафонов", "fin:marreset"))
    kb.add(btn(f"✏️ Банк марафона: {round(cfg.get('mar_start', 1000))}₽", "fin:marbank"))
    ml = int(cfg.get("mar_len", 15))
    kb.row(*[btn(("✅ " if ml == v else "") + f"{v} цеп.", f"fin:ml={v}") for v in (5, 10, 15, 20)])
    md = int(cfg.get("mar_dr", 0) or 0)
    kb.add(btn("🏃 Марафон: ставить масть, которой нет 👇", "fin:x"))
    kb.row(*[btn(("✅ " if md == v else "") + (f"{v} игр" if v else "каждая игра"), f"fin:md={v}")
             for v in (0, 2, 3, 4, 5)])
    # выбор процента динамического флэта
    cur = cfg.get("flat_pct", 1.0)
    kb.add(btn(f"🎯 Динамический флэт: {cur:g}% банка — выбери ниже 👇", "fin:x"))
    kb.row(*[btn(("✅ " if cur == v else "") + f"{v:g}%", f"fin:p={v:g}") for v in FLAT_PRESETS[:4]])
    kb.row(*[btn(("✅ " if cur == v else "") + f"{v:g}%", f"fin:p={v:g}") for v in FLAT_PRESETS[4:]])
    kb.row(btn("➖ 0.5%", "fin:pc-"), btn("✏️ Свой %", "fin:pct"), btn("➕ 0.5%", "fin:pc+"))
    # повышение ставки после проигрыша
    up = cfg.get("loss_up_pct", 0.0)
    kb.add(btn(f"📈 После проигрыша: " + (f"+{up:g}% к ставке" if up else "не повышать") + " 👇", "fin:x"))
    kb.row(*[btn(("✅ " if up == v else "") + (f"+{v:g}%" if v else "0"), f"fin:u={v:g}") for v in UP_PRESETS[:4]])
    kb.row(*[btn(("✅ " if up == v else "") + f"+{v:g}%", f"fin:u={v:g}") for v in UP_PRESETS[4:]])
    kb.add(btn("✏️ Свой % повышения", "fin:upct"))
    kb.add(btn("➖", "fin:od-"), btn(f"КФ {cfg['odds']}", "fin:x"), btn("➕", "fin:od+"))
    kb.add(btn("✏️ Задать банк", "fin:bank"))
    kb.add(back())
    return kb


def stickers_text():
    lines = ["🧷 <b>Стикерпаки</b>\n",
             "Чтобы добавить пак — просто пришли мне сюда любой стикер из него.\n"]
    if cfg["sticker_sets"]:
        for i, name in enumerate(cfg["sticker_sets"], 1):
            lines.append(f"{i}. https://t.me/addstickers/{name}")
    else:
        lines.append("Пока паков нет — персонажи пишут только текстом.")
    lines.append(f"\nУчиться у группы: {onoff(cfg.get('learn_stickers'))} "
                 f"(сами добавлять паки, которые шлют участники)")
    return "\n".join(lines)


def stickers_kb():
    kb = types.InlineKeyboardMarkup(row_width=1)
    for i, name in enumerate(cfg["sticker_sets"]):
        kb.add(btn(f"🗑 Удалить {name}"[:60], f"sd:{i}"))
    kb.add(btn(f"📚 Учиться у группы: {onoff(cfg.get('learn_stickers'))}", "slearn"))
    kb.add(back())
    return kb


@listener.message_handler(func=lambda m: m.chat.type == "private"
                          and is_admin(m.from_user.id), content_types=["sticker"])
def on_admin_sticker(m):
    sset = m.sticker.set_name
    if not sset:
        listener.send_message(m.chat.id, "Этот стикер не из пака, его добавить нельзя")
        return
    if sset in cfg["sticker_sets"]:
        listener.send_message(m.chat.id, "Этот пак уже добавлен 👍")
    else:
        cfg["sticker_sets"].append(sset)
        save_settings()
        n = len(bot_stickers(PERSONAS[0]))
        listener.send_message(m.chat.id, f"Пак «{sset}» добавлен ✅ Всего стикеров: {n}")
    show(m.chat.id, stickers_text(), stickers_kb())


def is_admin(user_id):
    return user_id in ADMIN_IDS


def show(chat_id, text, kb, msg_id=None):
    try:
        if msg_id:
            listener.edit_message_text(text, chat_id, msg_id, reply_markup=kb,
                                       parse_mode="HTML")
        else:
            listener.send_message(chat_id, text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass   # текст не изменился — это нормально


@listener.message_handler(commands=["start", "panel"],
                          func=lambda m: m.chat.type == "private")
def cmd_panel(m):
    if not is_admin(m.from_user.id):
        return
    pending.pop(m.from_user.id, None)
    show(m.chat.id, main_text(), main_kb())


@listener.message_handler(commands=["cancel"],
                          func=lambda m: m.chat.type == "private")
def cmd_cancel(m):
    if pending.pop(m.from_user.id, None):
        listener.send_message(m.chat.id, "Отменено")
    show(m.chat.id, main_text(), main_kb())


# ----- ввод текста (новое имя, характер, тема) -----
@listener.message_handler(func=lambda m: m.chat.type == "private"
                          and m.from_user.id in pending, content_types=["text"])
def on_input(m):
    kind, key = pending.pop(m.from_user.id)
    text = m.text.strip()
    if kind == "name":
        p = BY_KEY[key]
        if len(text) > 64:
            listener.send_message(m.chat.id, "Слишком длинно, максимум 64 символа")
            pending[m.from_user.id] = (kind, key)
            return
        cfg["personas"].setdefault(key, {})["name"] = text
        save_settings()
        try:
            p["bot"].set_my_name(name=text)      # меняем имя бота в Telegram
            note = "Имя изменено и в Telegram ✅"
        except Exception as e:
            note = (f"Имя в разговорах изменено, но Telegram не дал поменять "
                    f"имя бота ({e}). Можно поменять в BotFather через /setname")
        listener.send_message(m.chat.id, note)
        show(m.chat.id, persona_text(p), persona_kb(p))
    elif kind == "char":
        p = BY_KEY[key]
        cfg["personas"].setdefault(key, {})["character"] = text
        save_settings()
        listener.send_message(m.chat.id, "Характер обновлён ✅")
        show(m.chat.id, persona_text(p), persona_kb(p))
    elif kind == "dbcode":
        t = text.strip()
        if not re.fullmatch(r"\d+(\s+-?\d+(\.\d+)?)?", t):
            listener.send_message(m.chat.id, "Нужно число T или «T P», например 1234 или 1234 0")
            pending[m.from_user.id] = (kind, key)
            return
        db_set("t_game" if key == "tgame" else "t_dealer", t)
        save_settings()
        listener.send_message(m.chat.id, "Код сохранён ✅")
        show(m.chat.id, db_panel_text(), db_panel_kb())
    elif kind == "groxbank":
        try:
            v = float(text.replace(" ", "").replace(",", ".").replace("₽", ""))
        except ValueError:
            listener.send_message(m.chat.id, "Нужно число, например 10000")
            pending[m.from_user.id] = (kind, key)
            return
        for cid in cfg["groups"]:
            st = grox_state(cid)
            st["bank"] = v
            st["start"] = v
        save_settings()
        listener.send_message(m.chat.id, f"Банк 21GROX: {money(v)} ✅")
        show(m.chat.id, grox_panel_text(), grox_panel_kb())
    elif kind == "marbank":
        try:
            v = float(text.replace(" ", "").replace(",", ".").replace("₽", ""))
            if v < 10:
                raise ValueError
        except ValueError:
            listener.send_message(m.chat.id, "Нужно число, например 1000")
            pending[m.from_user.id] = (kind, key)
            return
        cfg["mar_start"] = v
        cfg["mar"] = {}
        save_settings()
        listener.send_message(m.chat.id, f"Банк марафона {round(v)}₽ ✅ Следующий марафон начнётся с него")
        show(m.chat.id, fin_text(), fin_kb())
    elif kind == "upct":
        try:
            v = float(text.replace("%", "").replace(",", ".").strip())
            if not 0 <= v <= 300:
                raise ValueError
        except ValueError:
            listener.send_message(m.chat.id, "Нужно число от 0 до 300, например 40")
            pending[m.from_user.id] = (kind, key)
            return
        cfg["loss_up_pct"] = round(v, 2)
        save_settings()
        listener.send_message(m.chat.id, f"После проигрыша ставка +{v:g}% ✅")
        show(m.chat.id, fin_text(), fin_kb())
    elif kind == "pct":
        try:
            v = float(text.replace("%", "").replace(",", ".").strip())
            if not 0.1 <= v <= 20:
                raise ValueError
        except ValueError:
            listener.send_message(m.chat.id, "Нужно число от 0.1 до 20, например 1.5")
            pending[m.from_user.id] = (kind, key)
            return
        cfg["flat_pct"] = round(v, 2)
        save_settings()
        listener.send_message(m.chat.id, f"Ставка {v:g}% от банка ✅ Новые прогнозы считаются так")
        show(m.chat.id, fin_text(), fin_kb())
    elif kind in ("bank", "stake"):
        try:
            v = float(text.replace(" ", "").replace(",", "."))
            if v <= 0:
                raise ValueError
        except ValueError:
            listener.send_message(m.chat.id, "Нужно число, например 10000")
            pending[m.from_user.id] = (kind, key)
            return
        if kind == "bank":
            cfg["start_bank"] = v
            for cid in list(cfg["groups"].keys()):
                for p in PERSONAS:
                    cfg["bank"][bank_key(cid, p["key"])] = v
            listener.send_message(m.chat.id, f"Банк {money(v)} ✅ Новый пост начнётся с него")
        else:
            cfg["stake"] = v
            listener.send_message(m.chat.id, f"Первая ставка {money(v)} ✅")
        save_settings()
        show(m.chat.id, fin_text(), fin_kb())
    elif kind == "topic":
        cfg["topics"][key] = text
        save_settings()
        listener.send_message(m.chat.id, "Тема сохранена ✅")
        show(m.chat.id, group_text(key), group_kb(key))


# ================= СИГНАЛ «💥 ПЕРЕБОР ДИЛЕРА» (по КФ 1xBet) =================
# Бот смотрит линию 1xBet «21 классик»: если в игре «Игра закончится перебором — Да»
# стоит заданный КФ (1.97), даём сигнал «Будет перебор у дилера — Да» (КФ 4–8) на эту игру
# и догоняем следующими играми. Итог берём из постов канала статистики (очки дилера > 21).
try:
    from curl_cffi import requests as cffi_requests
except Exception:
    cffi_requests = None
BX_CHAMP = 2092323
# коды рынков 1xBet «21 классик» (найдены по дампу):
#   8001/8002 — «Игра закончится перебором» Да/Нет;  8051/8052 — «Будет перебор у дилера» Да/Нет
#   8049/8050 — перебор у игрока;  7797 — в игре будет 21;  8043 — золотое очко;  G=1: T1 П1, T2 ничья, T3 П2
BX_HOST = "https://1xbet.com"
bx = {"s": None, "odds": {}, "last_ok": 0, "err": "", "games": 0}
db_lock = threading.Lock()


def db_cfg(key, default):
    return cfg.setdefault("dbust", {}).get(key, default)


def db_set(key, value):
    cfg.setdefault("dbust", {})[key] = value


def bx_get(url):
    if cffi_requests is None:
        raise RuntimeError("нет модуля curl_cffi (pip install curl_cffi)")
    if bx["s"] is None:
        bx["s"] = cffi_requests.Session()
        bx["s"].get(BX_HOST + "/", impersonate="safari15_5")
        time.sleep(2)
    r = bx["s"].get(BX_HOST + url, impersonate="safari15_5", timeout=15)
    if r.status_code == 403:
        bx["s"] = None
        raise RuntimeError("1xBet ответил 403 — пересоздаю сессию")
    return r.json()


def bx_games():
    """Игры линии: [(id, номер игры)]"""
    v = (bx_get(f"/service-api/LiveFeed/GetChampZip?champ={BX_CHAMP}").get("Value") or {})
    out = []
    for g in v.get("G") or []:
        try:
            out.append((g["I"], int(str(g.get("DI")).strip())))   # DI — номер игры, как #N в канале
        except (KeyError, ValueError, TypeError):
            continue
    return out


def bx_markets(gid):
    r = bx_get("/service-api/LiveFeed/GetGameZip"
               f"?id={gid}&lng=ru&isSubGames=true&GroupEvents=true"
               "&countevents=500&grMode=4&partner=1&marketType=1")
    out = []
    for grp in (r.get("Value") or {}).get("GE") or []:
        for line in grp.get("E") or []:
            for e in line:
                out.append({"G": grp.get("G"), "T": e.get("T"), "P": e.get("P"), "C": e.get("C")})
    return out


def bx_pick(markets, code):
    """code = "T" или "T P" → КФ"""
    if not code:
        return None
    parts = str(code).split()
    t = int(parts[0])
    p = float(parts[1]) if len(parts) > 1 else None
    for e in markets:
        if e["T"] == t and (p is None or e.get("P") == p):
            return e["C"]
    return None


def db_stakes():
    """Ровная прибыль под худший КФ дилера (db_kmin): заход отбивает все прошлые ставки."""
    n = int(db_cfg("steps", 5))
    k = float(db_cfg("kmin", 4.0))
    base = float(db_cfg("base", 100))
    m = cfg.get("grox_mult")
    if db_cfg("ladder", "grox") == "grox" and m:     # как «Догон ставок» в 21GROX: ×1.5 / ×2 / ×2.5
        return [int(round(base * float(m) ** i / 10)) * 10 for i in range(n)]
    out, profit = [base], base * (k - 1)
    while len(out) < n:
        out.append(int(-(-((sum(out) + profit) / (k - 1)) // 10)) * 10)
    return [int(x) for x in out]


def db_state(chat_id):
    st = cfg.setdefault("dbust_chats", {}).setdefault(str(chat_id), {})
    for k, v in (("row", None), ("msg_id", None), ("bank", 0.0), ("ok", 0), ("fail", 0)):
        st.setdefault(k, v)
    return st


def db_last_finished():
    """Последний законченный номер игры по постам канала (во всех чатах)."""
    best = 0
    for cid in cfg["groups"]:
        try:
            h = finished_history(int(cid), 3)
            if h:
                best = max(best, h[-1][0])
        except Exception:
            pass
    return best


def db_text(chat_id):
    st = db_state(chat_id)
    r = st["row"]
    if not r:
        return None
    sgn = lambda v: ("+" if v >= 0 else "−") + money(abs(v))
    lines = ["<b>💥 Перебор дилера</b>", "",
             f"<b>▶️ Сигнал на игру #{r['start']}</b> (общий перебор {r['trig']})"]
    for i, h in enumerate(r["hist"]):
        lines.append(f"├ #{h['n']} ставка {money(h['stake'])} · КФ {h['k']} — "
                     + ("✅" if h["hit"] else "мимо"))
    total = len(r["stakes"])
    if r["status"] == "⏳":
        k = r.get("kcur") or "?"
        lines.append(f"└ ⏳ ставка <b>{money(r['stakes'][r['step'] - 1])}</b> на #{r['cur']} "
                     f"· КФ {k} ({r['step']}/{total})")
    elif r["status"] == "✅":
        lines.append(f"└ ✅ #{r['game']} ({r['step']}-я игра) · ставка {money(r.get('stake_hit', 0))} "
                     f"· КФ {r.get('k_hit')} → <b>{sgn(r['result'])}</b>")
    elif r["status"] == "❌":
        lines.append(f"└ ❌ {total} игр мимо <b>{sgn(r['result'])}</b>")
    else:
        lines.append("└ ➖ нет итога")
    lines += ["", f"💰 Всего: <b>{sgn(st['bank'])}</b>", f"📊 {st['ok']}✅ / {st['fail']}❌"]
    return "\n".join(lines)


def db_publish(chat_id, new):
    st = db_state(chat_id)
    text = db_text(chat_id)
    pool = [p for p in PERSONAS if can_post(p, int(chat_id))]
    if not pool or not text:
        return
    p = pool[0]
    if not new and st.get("msg_id"):
        try:
            p["bot"].edit_message_text(text, int(chat_id), st["msg_id"], parse_mode="HTML")
            return
        except Exception as e:
            if "not modified" in str(e):
                return
            print("Перебор дилера, правка:", e)
            return
    try:
        st["msg_id"] = p["bot"].send_message(int(chat_id), text, parse_mode="HTML").message_id
    except Exception as e:
        print("Перебор дилера, отправка:", e)


def db_start_signal(num, trig, kd):
    """Сигнал по линии 1xBet: ставим перебор дилера на игру num во всех чатах 21."""
    with db_lock:
        for cid in cfg["groups"]:
            st = db_state(cid)
            if st["row"] and st["row"]["status"] == "⏳":
                continue                       # прошлая цепочка ещё идёт
            st["row"] = {"start": num, "cur": num, "step": 1, "stakes": db_stakes(),
                         "trig": trig, "status": "⏳", "hist": [], "kcur": kd}
            st["msg_id"] = None
            db_publish(cid, True)
        save_settings()


def db_dealer_bust(text):
    pts = [int(x) for x in re.findall(r"(\d+)\s*\(", text or "")[:2]]
    return len(pts) == 2 and pts[1] > 21


def process_dbust(chat_id, text):
    """Итог игры из канала → двигаем цепочку «перебор дилера»."""
    try:
        g = int(game_no_from_post(text) or 0)
    except ValueError:
        return
    if not g:
        return
    with db_lock:
        st = db_state(chat_id)
        r = st["row"]
        if not r or r["status"] != "⏳":
            return
        if g < r["cur"] - 50 or g - r["cur"] >= 5:     # сброс номеров / итоги пропали
            r["status"], r["result"] = "➖", 0.0
            db_publish(chat_id, False)
            save_settings()
            return
        if g != r["cur"]:
            return
        k = r.get("kcur") or float(db_cfg("kdef", 5.0))
        stake = r["stakes"][r["step"] - 1]
        hit = db_dealer_bust(text)
        r["hist"].append({"n": g, "stake": stake, "k": k, "hit": hit})
        spent = sum(r["stakes"][:r["step"]])
        if hit:
            r["status"], r["game"], r["k_hit"], r["stake_hit"] = "✅", g, k, stake
            r["result"] = round(stake * k - spent, 2)
            st["ok"] += 1
        elif r["step"] >= len(r["stakes"]):
            r["status"], r["result"] = "❌", -spent
            st["fail"] += 1
        else:
            r["step"] += 1
            r["cur"] = g + 1
            r["kcur"] = None                      # КФ следующей игры зафиксируем до её начала
        if r["status"] in ("✅", "❌"):
            st["bank"] = round(st["bank"] + r["result"], 2)
            if r["status"] == "✅":
                r["hist"] = r["hist"][:-1]        # последняя игра показывается итоговой строкой
        db_publish(chat_id, False)
        save_settings()


def db_loop():
    """Фоном смотрит линию 1xBet и ловит игры с нужным КФ общего перебора."""
    fired = set()
    while True:
        time.sleep(6)
        if not db_cfg("on", False):
            continue
        try:
            last = db_last_finished()
            gl = bx_games()
            bx["games"] = len(gl)
            for gid, num in gl:
                if not num or (last and num <= last):
                    continue
                m = bx_markets(gid)
                kg = bx_pick(m, db_cfg("t_game", "8001"))
                kd = bx_pick(m, db_cfg("t_dealer", "8051"))
                bx["odds"][num] = {"game": kg, "dealer": kd}
                if kd:
                    with db_lock:
                        for cid in cfg["groups"]:
                            r = db_state(cid)["row"]
                            if r and r["status"] == "⏳" and r["cur"] == num and not r.get("kcur"):
                                r["kcur"] = kd
                                db_publish(cid, False)
                target = float(db_cfg("target", 1.97))
                tol = float(db_cfg("tol", 0.0))
                if kg and abs(kg - target) <= tol + 1e-9 and num not in fired:
                    fired.add(num)
                    print(f"Перебор дилера: сигнал на #{num} (общий перебор {kg}, КФ дилера {kd})")
                    db_start_signal(num, kg, kd)
            for old in [n for n in bx["odds"] if last and n < last - 30]:
                bx["odds"].pop(old, None)
            bx["last_ok"], bx["err"] = time.time(), ""
        except Exception as e:
            bx["err"] = str(e)[:150]
            print("Линия 1xBet:", e)
            time.sleep(10)


def db_dump():
    """Все игры линии с КФ «общий перебор» и «перебор дилера» + полный список рынков ближайшей игры."""
    gl = sorted(bx_games(), key=lambda x: x[1])
    if not gl:
        return "В линии нет игр"
    lines = ["🔎 Игры в линии 1xBet (номер как #N в канале):"]
    first = None
    for gid, num in gl:
        m = bx_markets(gid)
        first = first or (gid, num, m)
        kg = bx_pick(m, db_cfg("t_game", "8001"))
        kd = bx_pick(m, db_cfg("t_dealer", "8051"))
        lines.append(f"#{num}: общий перебор {kg}, перебор дилера {kd}")
    gid, num, m = first
    lines += ["", f"Все рынки ближайшей игры #{num} (id {gid}):"]
    for e in m:
        lines.append(f"G={e['G']} T={e['T']} P={e.get('P')} КФ={e['C']}")
    return "\n".join(lines)


def db_panel_text():
    st_lines = []
    for cid, title in cfg["groups"].items():
        st = db_state(cid)
        r = st["row"]
        cur = (f"идёт: ставка на #{r['cur']} ({r['step']}/{len(r['stakes'])})"
               if r and r["status"] == "⏳" else "ждёт сигнал")
        st_lines.append(f"{title}: всего {money(st['bank'])}, {st['ok']}✅/{st['fail']}❌ — {cur}")
    ok = (f"✅ линия читается, игр в линии: {bx['games']}, "
          f"{int(time.time() - bx['last_ok'])} сек назад" if bx["last_ok"] else "⏳ линия ещё не читалась")
    near = sorted(bx["odds"].items())[-3:]
    return "\n".join([
        "💥 <b>Перебор дилера</b> — сигнал по КФ 1xBet\n",
        f"Статус: {'🟢 ВКЛ' if db_cfg('on', False) else '🔴 ВЫКЛ'}",
        f"Условие: «Игра закончится перебором — Да» = {db_cfg('target', 1.97)}"
        f" (±{db_cfg('tol', 0.0)}) → ставим «Перебор у дилера — Да»",
        f"Код рынка «общий перебор Да»: {db_cfg('t_game', '8001') or '❗ не задан'}",
        f"Код рынка «перебор дилера Да»: {db_cfg('t_dealer', '8051') or '❗ не задан'}",
        f"Догон: {db_cfg('steps', 5)} игр, ставки {' → '.join(money(x) for x in db_stakes())}",
        ("(догон как в 21GROX: ×" + format(float(cfg.get("grox_mult")), "g") + ")"
         if db_cfg("ladder", "grox") == "grox" and cfg.get("grox_mult") else
         f"(ровная прибыль под КФ дилера от {db_cfg('kmin', 4.0)})")
        + f"; если КФ дилера не прочитан — {db_cfg('kdef', 5.0)}",
        "",
        ok if not bx["err"] else f"❌ ошибка линии: {bx['err']}",
        "Ближайшие КФ: " + ("; ".join(f"#{n}: общий {o.get('game')}, дилер {o.get('dealer')}"
                                      for n, o in near) or "нет"),
        "",
    ] + st_lines)


def db_panel_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(btn("🔴 Выключить" if db_cfg("on", False) else "🟢 Включить", "dbx:on"))
    kb.add(btn("➖", "dbx:tg:-0.01"), btn(f"КФ общего перебора {db_cfg('target', 1.97)}", "noop"),
           btn("➕", "dbx:tg:0.01"))
    tv = (0.0, 0.01, 0.02, 0.03, 0.05, 0.07, 0.1, 0.15)
    tb = [btn(("✅" if abs(float(db_cfg("tol", 0.0)) - v) < 1e-9 else "") + f"±{v:g}", f"dbx:tol:{v}")
          for v in tv]
    kb.row(*tb[:4])
    kb.row(*tb[4:])
    kb.add(btn("Догон — сколько игр 👇", "noop"))
    kb.row(*[btn(("✅" if int(db_cfg("steps", 5)) == n else "") + str(n), f"dbx:st:{n}")
             for n in (3, 5, 7, 10)])
    lad = db_cfg("ladder", "grox")
    kb.row(btn(("✅ " if lad == "grox" else "") + "Догон как в 21GROX", "dbx:lad:grox"),
           btn(("✅ " if lad == "even" else "") + "Ровная прибыль", "dbx:lad:even"))
    kb.add(btn("➖", "dbx:km:-0.5"), btn(f"Мин. КФ дилера {db_cfg('kmin', 4.0)}", "noop"),
           btn("➕", "dbx:km:0.5"))
    kb.add(btn("➖", "dbx:kd:-0.5"), btn(f"КФ дилера по умолч. {db_cfg('kdef', 5.0)}", "noop"),
           btn("➕", "dbx:kd:0.5"))
    kb.add(btn("➖", "dbx:bs:-50"), btn(f"Первая ставка {db_cfg('base', 100)}", "noop"),
           btn("➕", "dbx:bs:50"))
    kb.add(btn("✏️ Код «общий перебор»", "dbx:tgame"), btn("✏️ Код «перебор дилера»", "dbx:tdeal"),
           row_width=2)
    kb.add(btn("🔎 Показать рынки 1xBet (найти коды)", "dbx:dump"))
    kb.add(btn("♻️ Сбросить статистику", "dbx:reset"), btn("🔄 Обновить", "menu:dbust"), row_width=2)
    kb.add(back())
    return kb


threading.Thread(target=db_loop, daemon=True).start()


def ask_input(c, kind, key, prompt):
    pending[c.from_user.id] = (kind, key)
    listener.send_message(c.message.chat.id, prompt + "\n\n/cancel — отмена")


# ----- кнопки -----
@listener.callback_query_handler(func=lambda c: True)
def on_button(c):
    if not is_admin(c.from_user.id):
        listener.answer_callback_query(c.id, "Нет доступа")
        return
    d = c.data
    chat, mid = c.message.chat.id, c.message.message_id
    note = None
    screen = "main"

    if d == "toggle":
        cfg["enabled"] = not cfg["enabled"]
    elif d == "slang":
        cfg["slang_on"] = not cfg.get("slang_on", True)
    elif d == "ch-":
        cfg["dialog_chance"] = max(0.0, round(cfg["dialog_chance"] - 0.05, 2))
    elif d == "ch+":
        cfg["dialog_chance"] = min(1.0, round(cfg["dialog_chance"] + 0.05, 2))
    elif d == "cd-":
        cfg["cooldown"] = max(60, cfg["cooldown"] - 60)
    elif d == "cd+":
        cfg["cooldown"] = min(3600, cfg["cooldown"] + 60)
    elif d == "quiet":
        cfg["auto_quiet"] = not cfg["auto_quiet"]
    elif d == "ureply":
        cfg["user_reply"] = not cfg["user_reply"]
    elif d == "fcast":
        cfg["forecasts"] = not cfg.get("forecasts", True)
    elif d == "jk-":
        cfg["joke_chance"] = max(0.0, round(cfg.get("joke_chance", 0) - 0.1, 2))
    elif d == "jk+":
        cfg["joke_chance"] = min(1.0, round(cfg.get("joke_chance", 0) + 0.1, 2))
    elif d == "sk-":
        cfg["sticker_chance"] = max(0.0, round(cfg.get("sticker_chance", 0) - 0.1, 2))
    elif d == "sk+":
        cfg["sticker_chance"] = min(1.0, round(cfg.get("sticker_chance", 0) + 0.1, 2))
    elif d == "drtoggle":
        cfg["dr_on"] = not cfg.get("dr_on")
    elif d.startswith("drn:"):
        cfg["dr_suit_n"] = int(d[4:])
    elif d == "menu:fin":
        screen = "fin"
    elif d == "menu:dbust":
        screen = "dbust"
    elif d.startswith("dbx:"):
        a = d[4:].split(":")
        screen = "dbust"
        if a[0] == "on":
            db_set("on", not db_cfg("on", False))
        elif a[0] == "tg":
            db_set("target", round(float(db_cfg("target", 1.97)) + float(a[1]), 3))
        elif a[0] == "tol":
            db_set("tol", float(a[1]))
        elif a[0] == "st":
            db_set("steps", int(a[1]))
        elif a[0] == "lad":
            db_set("ladder", a[1])
        elif a[0] == "km":
            db_set("kmin", max(1.5, round(float(db_cfg("kmin", 4.0)) + float(a[1]), 2)))
        elif a[0] == "kd":
            db_set("kdef", max(1.5, round(float(db_cfg("kdef", 5.0)) + float(a[1]), 2)))
        elif a[0] == "bs":
            db_set("base", max(10, int(db_cfg("base", 100)) + int(a[1])))
        elif a[0] in ("tgame", "tdeal"):
            ask_input(c, "dbcode", a[0], "Пришли код рынка из «🔎 Показать рынки»: число T "
                                           "(или «T P», например «1234 0»)")
            listener.answer_callback_query(c.id)
            return
        elif a[0] == "dump":
            listener.answer_callback_query(c.id, "Читаю линию…")
            try:
                txt = db_dump()
            except Exception as e:
                txt = f"Не получилось прочитать 1xBet: {e}"
            for i in range(0, len(txt), 3800):
                listener.send_message(chat, txt[i:i + 3800])
            return
        elif a[0] == "reset":
            for cid in cfg["groups"]:
                st = db_state(cid)
                st.update(bank=0.0, ok=0, fail=0)
            note = "Статистика перебора дилера сброшена"
    elif d == "menu:grox":
        screen = "grox"
    elif d == "five:toggle":
        cfg["five_on"] = not cfg.get("five_on", False)
        note = "Сигнал «Пять» " + ("ВКЛ" if cfg["five_on"] else "ВЫКЛ")
        screen = "main"
    elif d == "diam:toggle":
        cfg["diam_on"] = not cfg.get("diam_on", False)
        note = "Стратегия бубна " + ("ВКЛ" if cfg["diam_on"] else "ВЫКЛ")
        screen = "main"
    elif d == "drought:toggle":
        cfg["drought_on"] = not cfg.get("drought_on", True)
        note = "Сигнал «нет масти» " + ("ВКЛ" if cfg.get("drought_on", True) else "ВЫКЛ")
        screen = "main"
    elif d == "grox:parallel":
        cfg["grox_parallel"] = not cfg.get("grox_parallel", False)
        note = ("Дублировать сигналы ВКЛ — новый не ждёт конца старого"
                if cfg["grox_parallel"] else
                "Дублировать ВЫКЛ — ждём закрытия текущего сигнала")
        screen = "main"
    elif d == "grox:stophit":
        order = ["off", "real", "virt"]
        cur = grox_stop_mode()
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "off"
        cfg["grox_stop_mode"] = nxt
        cfg["grox_stop_hit"] = nxt == "real"
        note = "Стоп при заходе: " + grox_stop_label()
        screen = "main"
    elif d == "grox:autodog":
        cfg["grox_auto_dog"] = not cfg.get("grox_auto_dog", True)
        note = "Догон автомат " + ("ВКЛ" if cfg["grox_auto_dog"] else "ВЫКЛ")
        screen = "grox"
    elif d == "grox:statsreset":
        for st in cfg.setdefault("grox", {}).values():
            if not isinstance(st, dict):
                continue
            st["stats"] = {}
            st["mprofit"] = {}
            st["mprofit_since"] = time.strftime("%d.%m")
            st["virt_bank"] = 0.0
            st["src_profit"] = {"diam": 0.0, "five": 0.0, "drought": 0.0}
            st["src_stats"] = {"diam": [0, 0], "five": [0, 0], "drought": [0, 0]}
            st["virt_n"] = 0
            st["virt_done"] = []
            st["virt_full_bank"] = 0.0
            st["virt_full_n"] = 0
            st["virt_cont"] = []
            for k, _, _, _ in GROX_LINES:
                st["stats"][k] = [0, 0]
                st["mprofit"][k] = 0.0
        note = "Статистика 21GROX сброшена (банк не трогали)"
        screen = "grox"
    elif d.startswith("gxn:"):
        cfg["grox_n"] = int(d[4:])
        screen = "grox"
    elif d.startswith("gxm:"):
        v = float(d[4:])
        cfg["grox_mult"] = v if v else None
        screen = "grox"
    elif d == "gxb:reset":
        for st in cfg.setdefault("grox", {}).values():
            st["bank"] = 0.0
            st["start"] = 0.0
            st["mprofit"] = {}
            st["mprofit_since"] = time.strftime("%d.%m")
        note = "Банк 21GROX сброшен на 0"
        screen = "grox"
    elif d == "gxb:set":
        ask_input(c, "groxbank", "-", "Пришли банк 21GROX, например 10000")
        listener.answer_callback_query(c.id)
        return
    elif d.startswith("gxs:"):
        _, k, n = d.split(":")
        cfg.setdefault("grox_steps", {})[k] = int(n)
        screen = "grox"
    elif d.startswith("gxt:"):
        k = d[4:]
        cfg.setdefault("grox_on", {})[k] = not grox_enabled(k)
        screen = "grox"
    elif d.startswith("gxo:"):
        _, k, delta = d.split(":")
        go = cfg.setdefault("grox_odds", {})
        go[k] = max(1.01, round(grox_odds(k) + float(delta), 2))
        screen = "grox"
    elif d.startswith("fin:"):
        a = d[4:]
        screen = "fin"
        if a == "mar":
            cfg["marathon"] = not cfg.get("marathon")
            cfg["mar"] = {}            # все марафоны с нуля, новым постом
        elif a.startswith("md="):
            cfg["mar_dr"] = int(a[3:])
        elif a.startswith("ml="):
            cfg["mar_len"] = int(a[3:])
        elif a == "marnew":
            cfg["mar"] = {}
        elif a == "marreset":
            cfg["mar_stats"] = {}      # счётчики марафонов и заработок — с нуля
            note = "Статистика марафонов сброшена"
        elif a == "marbank":
            ask_input(c, "marbank", "-", "Пришли стартовый банк марафона, например 1000")
            listener.answer_callback_query(c.id)
            return
        elif a == "on":
            cfg["fin_on"] = not cfg.get("fin_on", True)
        elif a == "st-":
            cfg["stake"] = max(10, cfg["stake"] - 50)
        elif a == "st+":
            cfg["stake"] = cfg["stake"] + 50
        elif a.startswith("u="):
            cfg["loss_up_pct"] = float(a[2:])
        elif a == "upct":
            ask_input(c, "upct", "-", "На сколько % повышать ставку после каждого проигрыша? "
                      "Например 40 (от 0 до 300). После захода ставка снова базовая.")
            listener.answer_callback_query(c.id)
            return
        elif a.startswith("p="):
            cfg["flat_pct"] = float(a[2:])
        elif a == "pct":
            ask_input(c, "pct", "-", "Пришли процент от банка для ставки, например 1.5 "
                      "(от 0.1 до 20)")
            listener.answer_callback_query(c.id)
            return
        elif a == "pc-":
            cfg["flat_pct"] = max(0.5, round(cfg.get("flat_pct", 1.0) - 0.5, 1))
        elif a == "pc+":
            cfg["flat_pct"] = min(10.0, round(cfg.get("flat_pct", 1.0) + 0.5, 1))
        elif a == "od-":
            cfg["odds"] = max(1.01, round(cfg["odds"] - 0.05, 2))
        elif a == "od+":
            cfg["odds"] = round(cfg["odds"] + 0.05, 2)
        elif a == "mult":
            order = [2.0, 2.5, 3.0]
            cur = cfg["dogon_mult"]
            cfg["dogon_mult"] = order[(order.index(cur) + 1) % len(order)] if cur in order else 2.5
        elif a in ("bank", "stake"):
            ask_input(c, a, "-", "Пришли новый стартовый банк числом, например 10000"
                      if a == "bank" else "Пришли первую ставку числом, например 100")
            listener.answer_callback_query(c.id)
            return
    elif d == "menu:stickers":
        screen = "stickers"
    elif d == "slearn":
        cfg["learn_stickers"] = not cfg.get("learn_stickers")
        screen = "stickers"
    elif d.startswith("sd:"):
        i = int(d[3:])
        if 0 <= i < len(cfg["sticker_sets"]):
            cfg["sticker_sets"].pop(i)
        screen = "stickers"
    elif d == "now":
        note = start_dialog(state["last_post"], force=True)
    elif d == "stats":
        people = sum(users_last_hour(cid) for cid in list(user_times))
        note = (f"Сегодня: разговоров {stats['dialogs']}, реплик {stats['sent']}, "
                f"ошибок {stats['errors']}. Сообщений людей за час: {people}")
    elif d == "menu:personas":
        screen = "personas"
    elif d == "menu:groups":
        screen = "groups"
    elif d.startswith("pe:"):
        screen = "persona:" + d[3:]
    elif d.startswith("pt:"):
        k = d[3:]
        if k in cfg["off"]:
            cfg["off"].remove(k)
        else:
            cfg["off"].append(k)
        screen = "persona:" + k
    elif d.startswith("pg:"):
        k = d[3:]
        order = ["baccara", "21", "all"]
        cur = pgame(BY_KEY[k])
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "baccara"
        cfg["personas"].setdefault(k, {})["game"] = nxt
        screen = "persona:" + k
    elif d.startswith("pn:"):
        p = BY_KEY[d[3:]]
        ask_input(c, "name", p["key"], f"Пришли новое имя для «{pname(p)}»")
        listener.answer_callback_query(c.id)
        return
    elif d.startswith("pc:"):
        p = BY_KEY[d[3:]]
        ask_input(c, "char", p["key"],
                  f"Опиши характер «{pname(p)}» одной-двумя фразами.\n"
                  f"Например: «бывалый игрок, говорит с усмешкой, любит вспоминать "
                  f"старые заносы»")
        listener.answer_callback_query(c.id)
        return
    elif d.startswith("gr:"):
        screen = "group:" + d[3:]
    elif d.startswith("gt:"):
        cid = d[3:]
        ask_input(c, "topic", cid,
                  f"Пришли тему для «{cfg['groups'].get(cid, cid)}».\n"
                  f"Например: «киберфутбол пенальти FIFA 26, серии и вратари»")
        listener.answer_callback_query(c.id)
        return
    elif d.startswith("ga:"):
        cfg["topics"].pop(d[3:], None)
        screen = "group:" + d[3:]

    save_settings()
    listener.answer_callback_query(c.id, note or "", show_alert=bool(note))

    if screen == "main":
        show(chat, main_text(), main_kb(), mid)
    elif screen == "personas":
        show(chat, personas_text(), personas_kb(), mid)
    elif screen == "groups":
        show(chat, groups_text(), groups_kb(), mid)
    elif screen == "fin":
        show(chat, fin_text(), fin_kb(), mid)
    elif screen == "dbust":
        show(chat, db_panel_text(), db_panel_kb(), mid)
    elif screen == "grox":
        show(chat, grox_panel_text(), grox_panel_kb(), mid)
    elif screen == "stickers":
        show(chat, stickers_text(), stickers_kb(), mid)
    elif screen.startswith("persona:"):
        p = BY_KEY[screen.split(":", 1)[1]]
        show(chat, persona_text(p), persona_kb(p), mid)
    elif screen.startswith("group:"):
        cid = screen.split(":", 1)[1]
        show(chat, group_text(cid), group_kb(cid), mid)


print("Персонажи запущены:", ", ".join(pname(p) for p in PERSONAS))
listener.infinity_polling(skip_pending=True)
