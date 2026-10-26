# -*- coding: utf-8 -*-
import collections
import copy
import datetime
import html
import json
import math
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import traceback
from urllib.parse import urljoin, urlparse

import telebot
from playwright.sync_api import sync_playwright
from telebot import types

# Только одна копия бота: две копии с одним токеном делят сообщения Telegram
# (ошибка 409 Conflict) — одна ставит, другая теряет сигналы.
_single = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
  _single.bind(("127.0.0.1", 47394))
except OSError:
  print("⛔ autobet_bot.py уже запущен — вторая копия не стартует. Если копий быть"
        " не должно: Диспетчер задач → завершить все python и запустить бота один раз.")
  sys.exit(1)

# ================== НАСТРОЙКИ ==================
BOT_VERSION = "26.10 07:30"  # показывается при запуске и в статусе — видно, какая версия работает
# Секреты лежат в autobet.env рядом со скриптом (в git не попадает),
# формат — строки КЛЮЧ=значение, образец — autobet.env.example.
BOT_DIR = os.path.dirname(os.path.abspath(__file__))
SECRETS_FILE = os.path.join(BOT_DIR, "autobet.env")


def _find_secrets():
  """autobet.env, а если его нет — похожий файл (autobet.env.txt, autobet (1).env…)."""
  if os.path.exists(SECRETS_FILE):
    return SECRETS_FILE
  for name in sorted(os.listdir(BOT_DIR)):
    low = name.lower()
    if low.startswith("autobet") and ".env" in low and "example" not in low:
      return os.path.join(BOT_DIR, name)
  return None


def _load_secrets(path):
  if not path:
    return
  # utf-8-sig: Блокнот Windows ставит в начало файла невидимый BOM
  with open(path, encoding="utf-8-sig") as fh:
    for line in fh:
      line = line.strip()
      if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_secrets_path = _find_secrets()
_load_secrets(_secrets_path)

BOT_TOKEN = os.environ.get("AUTOBET_BOT_TOKEN", "")
ADMIN_ID = int(os.environ.get("AUTOBET_ADMIN_ID", "0") or 0)
if not BOT_TOKEN or not ADMIN_ID:
  raise SystemExit(
      f"Заполни AUTOBET_BOT_TOKEN и AUTOBET_ADMIN_ID в {SECRETS_FILE}"
      " (образец — autobet.env.example). "
      + (f"Прочитан файл {os.path.basename(_secrets_path)}, но в нём нет этих строк."
         if _secrets_path else
         "Файл не найден. В папке лежат: " + ", ".join(sorted(os.listdir(BOT_DIR))))
  )

CDP_URL = "http://127.0.0.1:9222"  # порт отладки Opera

# Браузер: "own" — бот сам запускает свой Chromium (отдельный профиль, мобильная
# версия сайта, сам перезапускает при зависании); "opera" — подключение к Opera
# по порту отладки. Переключается командой /browser own | opera.
BROWSER_PROFILE = os.path.join(BOT_DIR, "browser_profile")
# Прокси/VPN только для браузера бота: socks5://логин:пароль@хост:порт или
# http://логин:пароль@хост:порт. Пусто — без прокси (например, VPN на весь компьютер).
BROWSER_PROXY = os.environ.get("AUTOBET_PROXY", "")
BROWSER_DEVICE = "Pixel 7"  # какой телефон изображает браузер (мобильная версия сайта)

# Автовход, если сайт разлогинил (пусто — не входить)
LOGIN_ID = os.environ.get("AUTOBET_LOGIN_ID", "")  # E-mail или ID
LOGIN_PASSWORD = os.environ.get("AUTOBET_LOGIN_PASSWORD", "")
SITE = os.environ.get("AUTOBET_SITE", "db-bet81459.top")  # актуальное зеркало из Opera


BASE_STAKE = 50  # первая ставка, ₽
MULTIPLIER = 2.0  # множитель догона
MAX_STEPS = 3  # максимум шагов догона
DAILY_LOSS_LIMIT = 1000  # стоп за день, ₽
MIN_ODDS = 1.2  # НИЖЕ 1.2 НЕ СТАВИМ
START_VIRTUAL_BANK = 100.0
MAX_SIGNAL_AGE = 999999  # СИГНАЛЫ НЕ ОТМЕНЯЮТСЯ ПО ВРЕМЕНИ
SITE_DECIMAL_SEPARATOR = "."  # формат чисел в английской версии сайта

STATE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "autobet_state.json"
)

# ----- ⚽ FIFA пенальти -----
PEN_CHANNEL = -1003756268378  # канал «Пенальти Авто» (сигналы от penalty_collector.py)
PEN_SEARCH_PATH = "/en/search-events?searchtext=fifa18+penalty"
PEN_MARKET_TITLE = "1X2"  # блок рынка на сайте: W1 = П1, W2 = П2 (без ничьей)
PEN_BASE_STAKE = 50  # первая ставка пенальти, ₽
PEN_MULTIPLIER = 2.5  # множитель догона пенальти
PEN_MAX_STEPS = 3  # больше шагов не ставим, даже если в сигнале больше
PEN_MAX_ODDS_DIFF = 0.15  # КФ на сайте отличается от сигнала больше — не тот матч / уже идёт

# Русское название в канале → как команда пишется на DB Bet (части имени)
PEN_TEAMS = {
    "арсенал": ["arsenal"],
    "барселона": ["barcelona"],
    "бавария": ["bayern"],
    "реал": ["real madrid"],
    "реал мадрид": ["real madrid"],
    "псж": ["paris saint-germain", "paris sg", "psg"],
    "пари сен-жермен": ["paris saint-germain", "paris sg", "psg"],
    "ювентус": ["juventus"],
    "ливерпуль": ["liverpool"],
    "челси": ["chelsea"],
    "манчестер сити": ["manchester city", "man city"],
    "манчестер юнайтед": ["manchester united", "manchester utd", "man utd"],
    "боруссия": ["dortmund", "borussia d"],
    "боруссия д": ["dortmund", "borussia d"],
    "интер": ["inter"],
    "милан": ["ac milan", "milan"],
    "атлетико": ["atletico"],
    "тоттенхэм": ["tottenham"],
    "наполи": ["napoli"],
    "аякс": ["ajax"],
    "порту": ["porto"],
    "бенфика": ["benfica"],
    "рома": ["roma"],
    "лацио": ["lazio"],
    "севилья": ["sevilla"],
    "валенсия": ["valencia"],
    "лион": ["lyon"],
    "марсель": ["marseille"],
    "монако": ["monaco"],
    "байер": ["leverkusen", "bayer"],
    "эвертон": ["everton"],
    "вильярреал": ["villarreal"],
}

# ----- 🃏 21 очко -----
# Канал «21 очко Авто» с сигналами AUTO21 (формат — SIGNAL21.md). Можно задать
# здесь, в autobet.env (AUTOBET_G21_CHANNEL) или кнопкой, когда придёт первый пост.
G21_CHANNEL = int(os.environ.get("AUTOBET_G21_CHANNEL", "-1004380611765") or 0)  # «21 очко автоставка»
G21_SEARCH_PATH = "/ru/search-events?searchtext=21+ochko"
G21_GAME_TITLE = "21 Очко"
# код исхода в сигнале → (рынок в боте, заголовок блока на сайте, слово в купоне)
G21_OUTCOMES = {
    "G": ("ГОЛД", 'Будет "золотое очко"', "золотое очко"),
    "R": ("РАЗДАЧА", "Игра завершится на раздаче", "раздаче"),
}
# лесенки догона: последний шаг — максимум сайта (если лимит в купоне меньше — ставим лимит)
G21_LADDERS = {
    "ГОЛД": [25, 40, 60, 85, 130, 190, 290, 430, 650, 970],
    "РАЗДАЧА": [95, 140, 215, 320, 480, 720, 1080, 1620, 2430, 3650],
}
G21_MAX_ODDS_DIFF = 0.25  # КФ на сайте отличается от сигнала больше чем на 25% — не ставим
G21_FIND_TIMEOUT = 40  # сек ждём, пока игра появится в поиске
# Сигнал старше этого (например, после перезапуска бота или падения Opera) не ставим:
# игра/матч уже прошли. Теннис по-прежнему без ограничения (MAX_SIGNAL_AGE).
# У 21 очко запас большой: часы компьютера могут отставать/спешить, а устаревшие
# игры и так отсеиваются по номерам (g21_stale).
G21_SIGNAL_MAX_AGE = 10 * 60
PEN_SIGNAL_MAX_AGE = 4 * 60

GAMES = {"tennis": "🏓 Теннис", "penalty": "⚽ Пенальти", "g21": "🃏 21 очко"}
MARKETS = ("ТМ", "ТБ", "П1", "П2", "ГОЛД", "РАЗДАЧА")
# ===============================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML", threaded=False)
lock = threading.RLock()
class JobQueue(queue.Queue):
  """Очередь заданий браузера: 🃏 21 очко идёт первым — игра каждую минуту,
  ждать за долгими поисками пенальти/тенниса нельзя."""

  def _init(self, maxsize):
    self.urgent = collections.deque()
    self.normal = collections.deque()

  def _qsize(self):
    return len(self.urgent) + len(self.normal)

  def _put(self, job):
    payload = job.get("sig") or job.get("result") or {}
    (self.urgent if payload.get("game") == "g21" else self.normal).append(job)

  def _get(self):
    return self.urgent.popleft() if self.urgent else self.normal.popleft()

  def urgent_waiting(self):
    with self.mutex:
      return len(self.urgent)


jobs = JobQueue()
announced_channels = set()


def default_state():
  return {
      "running": True,  # Автоматически включен при старте
      "dry": True,
      "bank": None,
      "virtual_bank": START_VIRTUAL_BANK,
      "day": str(datetime.date.today()),
      "today_dry": {"bets": 0, "win": 0, "lose": 0, "profit": 0.0},
      "today_real": {"bets": 0, "win": 0, "lose": 0, "profit": 0.0},
      "open_bets": [],
      "processed_posts": [],
      "inbox": [],
      "closed_bets": [],
      "generation": 0,
      "bank_updated_at": None,
      "pending_reports": [],
      "channel_id": None,
      "channels": [],  # каналы теннисных сигналов (можно несколько)
      "report_sent_for": None,
      "base_stake": BASE_STAKE,
      "multiplier": MULTIPLIER,
      "max_steps": MAX_STEPS,
      "min_odds": MIN_ODDS,
      "daily_loss_limit": DAILY_LOSS_LIMIT,
      "games": {"tennis": True, "penalty": True, "g21": True},
      "g21_channel": None,
      "browser_mode": "opera",  # own | opera
      "pen_base_stake": PEN_BASE_STAKE,
      "pen_multiplier": PEN_MULTIPLIER,
      "pen_max_steps": PEN_MAX_STEPS,
      "pen_allow_repeat": False,  # вторая ставка на тот же матч из другой цепочки
  }


def validate_payload(p):
  if not isinstance(p, dict) or p.get("kind") not in ("signal", "result"):
    raise ValueError("некорректное событие")
  if p["kind"] == "result":
    if p.get("result") not in ("win", "lose", "void"):
      raise ValueError("некорректный результат")
    if p.get("set") is not None and (
        type(p["set"]) is not int or not 1 <= p["set"] <= 7
    ):
      raise ValueError("некорректная партия в результате")
    if p.get("players") is not None and not isinstance(p["players"], str):
      raise ValueError("некорректные игроки в результате")
    if p.get("signal_id") is not None and not isinstance(p["signal_id"], str):
      raise ValueError("некорректная ссылка на сигнал")
  else:
    if (
        not isinstance(p.get("players"), str)
        or type(p.get("set")) is not int
        or not 1 <= p["set"] <= 7
        or type(p.get("step")) is not int
        or not 1 <= p["step"] <= 20
        or p.get("market") not in MARKETS
        or isinstance(p.get("line"), bool)
        or not isinstance(p.get("line"), (int, float))
        or not math.isfinite(p["line"])
        or p["line"] <= 0
    ):
      raise ValueError("некорректный сигнал")


def validate_state(s):
  def number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )

  for field in ("running", "dry"):
    if not isinstance(s[field], bool):
      raise ValueError(f"{field}: требуется логическое значение")
  datetime.date.fromisoformat(s["day"])
  if not number(s["virtual_bank"]) or (
      s["bank"] is not None and not number(s["bank"])
  ):
    raise ValueError("некорректный банк")
  for field in ("today_dry", "today_real"):
    stats = s[field]
    if not isinstance(stats, dict) or not number(stats.get("profit")):
      raise ValueError(f"некорректная статистика {field}")
    for counter in ("bets", "win", "lose"):
      if type(stats.get(counter)) is not int or stats[counter] < 0:
        raise ValueError(f"некорректный счётчик {field}.{counter}")
  for field in (
      "open_bets",
      "closed_bets",
      "inbox",
      "processed_posts",
      "pending_reports",
  ):
    if not isinstance(s[field], list):
      raise ValueError(f"{field}: требуется список")
  if any(not isinstance(x, str) for x in s["processed_posts"]):
    raise ValueError("некорректные идентификаторы постов")
  for b in s["open_bets"] + s["closed_bets"]:
    if (
        not isinstance(b, dict)
        or not isinstance(b.get("players"), str)
        or number(b.get("stake")) is False
        or b["stake"] <= 0
        or number(b.get("odds")) is False
        or b["odds"] <= 1
        or type(b.get("dry")) is not bool
        or type(b.get("set")) is not int
        or not 1 <= b["set"] <= 7
        or b.get("market") not in MARKETS
        or number(b.get("line")) is False
        or b["line"] <= 0
        or b.get("status", "accepted")
        not in ("accepted", "placing", "unknown", "cancelled")
        or (b.get("post_id") is not None and not isinstance(b["post_id"], str))
    ):
      raise ValueError("некорректная сохранённая ставка")
  if type(s["generation"]) is not int or s["generation"] < 0:
    raise ValueError("некорректное поколение заданий")
  if s["channel_id"] is not None and type(s["channel_id"]) is not int:
    raise ValueError("некорректный ID канала")
  if s["bank_updated_at"] is not None and not number(s["bank_updated_at"]):
    raise ValueError("некорректное время снимка баланса")
  if s["report_sent_for"] is not None:
    datetime.date.fromisoformat(s["report_sent_for"])
  for item in s["inbox"]:
    if (
        not isinstance(item, dict)
        or not isinstance(item.get("id"), str)
        or item.get("kind") not in ("signal", "result")
        or not isinstance(item.get("payload"), dict)
        or item.get("status") not in ("pending", "review", "failed")
    ):
      raise ValueError("некорректное сохранённое событие")
    validate_payload(item["payload"])
    if item["kind"] == "signal" and (
        type(item.get("dry")) is not bool
        or type(item.get("generation")) is not int
        or not number(item.get("received_at"))
    ):
      raise ValueError("некорректное задание ставки")
  for report in s["pending_reports"]:
    if not isinstance(report, dict) or not isinstance(report.get("text"), str):
      raise ValueError("некорректный отложенный отчёт")
    datetime.date.fromisoformat(report["day"])


def load_state():
  if os.path.exists(STATE_FILE):
    try:
      with open(STATE_FILE, "r", encoding="utf-8") as f:
        s = default_state()
        loaded = json.load(f)
        if not isinstance(loaded, dict):
          raise ValueError("состояние должно быть JSON-объектом")
        s.update(loaded)
        if "virtual_bank" not in loaded:
          if s.get("dry", True):
            s["virtual_bank"] = (
                s["bank"] if s["bank"] is not None else START_VIRTUAL_BANK
            )
            s["bank"] = None
          else:
            s["virtual_bank"] = START_VIRTUAL_BANK
        if "today_dry" not in loaded or "today_real" not in loaded:
          old_today = loaded.get(
              "today", {"bets": 0, "win": 0, "lose": 0, "profit": 0.0}
          )
          if s.get("dry", True):
            s["today_dry"] = old_today
          else:
            s["today_real"] = old_today
        validate_state(s)
        return s
    except Exception as e:
      raise RuntimeError(
          f"Не удалось загрузить состояние {STATE_FILE}: {e}"
      ) from e
  return default_state()


state = load_state()
state["generation"] += 1
for index, saved_bet in enumerate(state["open_bets"] + state["closed_bets"]):
  saved_bet.setdefault("post_id", f"legacy:{index}")
  if saved_bet.get("status") == "placing":
    saved_bet["status"] = "unknown"
  saved_bet.setdefault("status", "accepted")

# старый формат: один канал → список каналов
if not isinstance(state.get("channels"), list):
  state["channels"] = []
state["channels"] = [c for c in state["channels"] if type(c) is int and c != PEN_CHANNEL]
if state["channel_id"] is not None and state["channel_id"] not in state["channels"]:
  if state["channel_id"] != PEN_CHANNEL:
    state["channels"].append(state["channel_id"])
if state["channel_id"] == PEN_CHANNEL:
  state["channel_id"] = state["channels"][0] if state["channels"] else None

# Бот всегда стартует в работе — пауза только вручную кнопкой
state["running"] = True


def save_state():
  with lock:
    temp_file = STATE_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as f:
      json.dump(state, f, ensure_ascii=False, indent=2)
      f.flush()
      os.fsync(f.fileno())
    os.replace(temp_file, STATE_FILE)


def roll_day():
  with lock:
    d = str(datetime.date.today())
    if state["day"] != d:
      old_day = state["day"]
      if state["report_sent_for"] != old_day and not any(
          r["day"] == old_day for r in state["pending_reports"]
      ):
        parts = [f" <b>Отчёт за {old_day}</b>"]
        for label, field in (
            ("Сухой режим", "today_dry"),
            ("Реальные ставки", "today_real"),
        ):
          t = state[field]
          parts.append(
              f"{label}: {t['bets']} ставок, {t['win']} ✅ / {t['lose']} ❌,"
              f" {money(t['profit'])}"
          )
        state["pending_reports"].append(
            {"day": old_day, "text": "\n".join(parts)}
        )
      state["day"] = d
      empty_stats = {"bets": 0, "win": 0, "lose": 0, "profit": 0.0}
      state["today_dry"] = dict(empty_stats)
      state["today_real"] = dict(empty_stats)
      save_state()


def send(text, **kw):
  try:
    bot.send_message(ADMIN_ID, text, **kw)
    return True
  except Exception as e:
    print("send error:", e)
    return False


def money(x):
  return f"{x:.2f}"


def parse_post(text):
  t = text or ""
  m_players = re.search(
      r"(?:⚔|✂|🥊|⚔️)?\s*([^\n]+?\s*[—–-]\s*[^\n]+)", t
  )
  players = None
  if m_players:
    names = re.sub(r"\([^)]*\)", "", m_players.group(1))
    names = re.sub(r"^[^\wА-Яа-яA-Za-z]+", "", names)
    parts = re.split(r"\s*[—–-]\s*|\s+-\s+", names)
    if len(parts) == 2 and all(p.strip() for p in parts):
      players = " — ".join(p.strip() for p in parts)

  win = bool(re.search(r"^\s*(?:\s*ВЫИГРЫШ|✅\s*\+\d+)", t, re.I | re.M))
  lose = bool(re.search(r"^\s*(?:❌\s*(?:мимо|проигр)|минус\b)", t, re.I | re.M))
  m_market = re.search(
      r"Ставка:\s*Тотал\s*партии\s*(ТМ|ТБ)\s*(\d+[.,]\d+)", t, re.I
  )
  # Виртуальный сет зашёл / БЕЗ СТАВКИ — реальных ставок не будет
  no_bet = bool(
      re.search(
          r"БЕЗ\s*СТАВКИ|Виртуальный\s*сет\s*зашёл|вирт\.\s*сет\s*зашёл",
          t,
          re.I,
      )
  )

  # «Сет 1:», «Сет 1 (вирт.):», «Сет 2: 100 ₽ …»
  set_blocks = re.findall(
      r"Сет\s*(\d+)\s*(?:\([^)]*\))?\s*:\s*([^\n]+)", t, re.I
  )

  def _is_virtual_block(content):
    return bool(
        re.search(r"вирт|virtual|\(вирт", content, re.I)
    ) and not bool(re.search(r"\d+\s*₽|\d+\s*руб", content, re.I))

  def _is_real_money_block(content):
    # Реальная ставка: есть сумма в ₽ и это не пометка «вирт»
    return bool(re.search(r"\d+[.,]?\d*\s*₽|\d+[.,]?\d*\s*руб", content, re.I))

  def _is_active_block(content):
    return bool(re.search(r"идёт|идет|⏳|⌛", content, re.I))

  # С какого сета начинаются РЕАЛЬНЫЕ ставки
  real_from = 1
  m_real_from = re.search(
      r"реальные\s*ставки\s*с\s*(\d+)|реальные\s*с\s*сета\s*:?\s*(\d+)|"
      r"Виртуально:\s*сет\s*\d+.*?реальные\s*ставки\s*с\s*(\d+)",
      t,
      re.I,
  )
  if m_real_from:
    real_from = int(
        next(g for g in m_real_from.groups() if g is not None)
    )

  active_live = any(_is_active_block(c) for _, c in set_blocks)

  if not (m_market and active_live and not no_bet):
    if win and lose:
      return None
    if win or lose:
      result_sets = re.findall(r"(?:Сет|Партия|Партии)\s*(\d+)\b", t, re.I)
      result_set = int(result_sets[-1]) if result_sets else None
      return {
          "kind": "result",
          "result": "win" if win else "lose",
          "players": players,
          "set": result_set,
      }
    if not m_market or no_bet:
      return None

  target_set = None
  step_num = 1
  active_content = ""

  if set_blocks:
    active = None
    for num, content in set_blocks:
      if _is_active_block(content):
        active = int(num)
        active_content = content
        break
    if active is not None:
      target_set = active
    else:
      target_set = int(set_blocks[-1][0])
      active_content = set_blocks[-1][1]
  else:
    target_set = real_from

  # Активный сет ещё виртуальный — не ставим
  if target_set < real_from:
    return None
  if _is_virtual_block(active_content):
    return None
  # Если в блоке явно нет суммы и сет помечен как вирт. в шапке
  if target_set < real_from:
    return None

  # Шаг догона = порядковый номер среди РЕАЛЬНЫХ сетов (с real_from)
  # Сет 2 при real_from=2 → step 1; сет 3 → step 2
  real_sets_so_far = []
  if set_blocks:
    for num, content in set_blocks:
      n = int(num)
      if n < real_from:
        continue
      # считаем реальным, если есть ₽ или это активный/будущий после virtual
      if _is_real_money_block(content) or _is_active_block(content) or n >= real_from:
        if n not in real_sets_so_far:
          real_sets_so_far.append(n)
  if target_set in real_sets_so_far:
    step_num = real_sets_so_far.index(target_set) + 1
  else:
    step_num = max(1, target_set - real_from + 1)

  explicit_step = re.search(r"\bШаг\s*(\d+)\b", t, re.I)
  if explicit_step:
    step_num = int(explicit_step.group(1))

  if not (1 <= target_set <= 7 and 1 <= step_num <= get_max_steps()):
    return None

  return {
      "kind": "signal",
      "players": players,
      "market": m_market.group(1).upper(),
      "line": float(m_market.group(2).replace(",", ".")),
      "set": target_set,
      "step": step_num,
      "odds": None,
  }


def get_base_stake():
  return float(state.get("base_stake", BASE_STAKE))


def get_multiplier():
  return float(state.get("multiplier", MULTIPLIER))


def get_max_steps():
  return int(state.get("max_steps", MAX_STEPS))


def get_min_odds():
  return float(state.get("min_odds", MIN_ODDS))


def limit_text():
  v = get_daily_loss_limit()
  return "выкл" if v <= 0 else money(v)


def get_daily_loss_limit():
  return float(state.get("daily_loss_limit", DAILY_LOSS_LIMIT))


def game_of(x):
  return (x or {}).get("game") or "tennis"


def game_on(game):
  return bool(state.get("games", {}).get(game, True))


def g21_ladder(market):
  return G21_LADDERS.get(market) or []


def get_steps_for(game, market=None):
  if game == "g21":
    if market:
      return len(g21_ladder(market))
    return max(len(x) for x in G21_LADDERS.values())
  if game == "penalty":
    return int(state.get("pen_max_steps", PEN_MAX_STEPS))
  return get_max_steps()


def stake_for(step, game="tennis", market=None):
  if game == "g21":
    ladder = g21_ladder(market)
    return float(ladder[step - 1]) if 1 <= step <= len(ladder) else 0.0
  if game == "penalty":
    base = float(state.get("pen_base_stake", PEN_BASE_STAKE))
    mult = float(state.get("pen_multiplier", PEN_MULTIPLIER))
    return round(base * (mult ** (step - 1)), 2)
  return round(get_base_stake() * (get_multiplier() ** (step - 1)), 2)


def pen_ladder_text():
  return " ".join(
      f"{step}:{money(stake_for(step, 'penalty'))}"
      for step in range(1, get_steps_for("penalty") + 1)
  )


def g21_ladder_text(market):
  return " ".join(str(x) for x in g21_ladder(market))


def describe(b):
  """Короткое описание ставки/сигнала для сообщений."""
  if game_of(b) == "g21":
    return f"🃏 21 очко #{b.get('match_no', '?')} · {b['market']}"
  if game_of(b) == "penalty":
    team = b.get("team") or ""
    return (
        f"⚽ Пенальти #{b.get('match_no', '?')} · {b['market']}"
        + (f" {b['line']:g}" if b.get("market") in ("ТБ", "ТМ") else "")
        + (f" ({team})" if team else "")
    )
  return f"🏓 Партия {b.get('set') or '?'} · {b['market']} {b['line']:g}"


def ladder_text():
  return " ".join(
      f"{step}:{money(stake_for(step))}"
      for step in range(1, get_max_steps() + 1)
  )


def _same_stake(current, expected):
  try:
    cur = float(str(current).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    return math.isfinite(cur) and abs(cur - float(expected)) < 0.001
  except (TypeError, ValueError):
    return False


def player_key(players):
  if not players:
    return None
  parts = [p.strip() for p in re.split(r"\s+[—–-]\s+", players) if p.strip()]
  if len(parts) != 2:
    return None
  names = tuple(sorted(_slug(p) for p in parts))
  return names if all(names) and names[0] != names[1] else None


def cur_site():
  """Текущее зеркало: из /mirror или с открытой вкладки, иначе SITE."""
  return state.get("site") or SITE


def remember_site(url):
  """Если вкладка открыта на рабочем зеркале DB Bet — запомнить его."""
  try:
    parsed = urlparse(url)
    host = parsed.hostname or ""
  except Exception:
    return
  if (parsed.path or "").rstrip("/").endswith("/block"):
    return  # страница блокировки по стране — это не рабочее зеркало
  if ("db-bet" in host or "dbbet" in host) and host != state.get("site"):
    with lock:
      old = cur_site()
      state["site"] = host
      save_state()
    send(f"🔄 Зеркало DB Bet: {html.escape(old)} → <b>{html.escape(host)}</b>")


def find_page(browser):
  # 1) живая вкладка DB Bet; мёртвые (ERR_FAILED на старом зеркале) пропускаем
  dead = None
  for ctx in browser.contexts:
    for pg in ctx.pages:
      url = pg.url or ""
      if "db-bet" in url or "dbbet" in url or url.startswith("chrome-error://"):
        if url.startswith("http") and not site_problem(pg):
          remember_site(url)
          return pg
        dead = dead or pg
  if dead is not None:
    return dead  # open_league() переведёт её на текущее зеркало

  try:
    if browser.contexts:
      ctx = browser.contexts[0]
      pg = ctx.new_page()
      pg.goto(f"https://{cur_site()}", wait_until="domcontentloaded")
      pg.wait_for_timeout(2000)
      return pg
  except Exception as e:
    print(f"Не удалось автоматически открыть вкладку в Opera: {e}")

  for ctx in browser.contexts:
    for pg in ctx.pages:
      if (
          pg.url
          and not pg.url.startswith("chrome://")
          and not pg.url.startswith("about:")
      ):
        return pg
  return None


LEAGUE_PATH = "/en/live/table-tennis/1691055-pro-league"


def league_url():
  return f"https://{cur_site()}{LEAGUE_PATH}"
MAX_SITE_STAKE = 25400
HEALTH_EVERY = 5 * 60  # проверка доступности сайта/VPN, сек

site_health = {"down": False, "reason": None, "since": None}


class SkipSignal(RuntimeError):
  """Сигнал пропускается сразу, без повторных попыток."""


class SiteDown(RuntimeError):
  pass


def site_problem(page):
  """Вернёт причину, если вместо сайта открыта страница ошибки (VPN/зеркало)."""
  try:
    url = page.url or ""
    if url.startswith("chrome-error://") or url.startswith("opera-error://"):
      return "страница ошибки браузера"
    body = page.evaluate(
        "() => (document.body && document.body.innerText || '').slice(0, 3000)"
    )
    if re.search(r"Out of memory|Aw, Snap", body or "", re.I):
      return "вкладка упала (нехватка памяти)"
    path = urlparse(url).path or ""
    if path.rstrip("/").endswith("/block") or re.search(
        r"Access denied|not available in your country", body or "", re.I
    ):
      m_cc = re.search(r"\b([A-Z]{2})\s+\d{1,3}(?:\.\d{1,3}){3}\b", body or "")
      return (
          "доступ запрещён для страны"
          + (f" {m_cc.group(1)}" if m_cc else "")
          + " — поменяй регион VPN на Europe"
      )
    m = re.search(r"\bERR_[A-Z_]+\b", body or "")
    if m or re.search(r"can.t be reached|недоступен|не удаётся получить доступ",
                      body or "", re.I):
      return "сайт не открывается" + (f" ({m.group(0)})" if m else "")
  except Exception as e:
    return f"страница не отвечает: {e}"
  return None


def open_league(page, timeout=15000):
  """Открыть Лигу Про; при ошибке сети/VPN — SiteDown."""
  try:
    page.goto(league_url(), wait_until="domcontentloaded", timeout=timeout)
  except Exception as e:
    if "net::ERR" in str(e) or "Timeout" in str(e):
      raise SiteDown(
          f"{cur_site()} не открывается ({str(e).splitlines()[0][:120]}) — "
          "проверь VPN Opera или задай новое зеркало: /mirror адрес"
      ) from e
    raise
  problem = site_problem(page)
  if problem:
    raise SiteDown(
        f"{cur_site()}: {problem} — проверь VPN Opera или задай новое"
        " зеркало: /mirror адрес"
    )
  # сайт мог сам перекинуть на новое зеркало — запоминаем его
  remember_site(page.url)

_TR = dict(
    zip(
        "абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
        [
            "a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l",
            "m", "n", "o", "p", "r", "s", "t", "u", "f", "kh", "ts", "ch",
            "sh", "shch", "", "y", "", "e", "yu", "ya",
        ],
    )
)


def _slug(s):
  s = (s or "").lower()
  s = "".join(_TR.get(ch, ch) for ch in s)
  return re.sub(r"[^a-z]", "", s)


def _num(txt, decimal_separator=SITE_DECIMAL_SEPARATOR):
  if decimal_separator not in (".", ","):
    raise ValueError("неверный десятичный разделитель")
  m = re.search(r"(?<![\d.,])\d[\d\s\u00a0\u202f.,]*", txt or "")
  if not m:
    return None
  if (txt or "")[:m.start()].rstrip().endswith("-"):
    return None
  num = re.sub(r"[\s\u00a0\u202f]", "", m.group(0))
  group_separator = "," if decimal_separator == "." else "."
  pattern = (
      rf"(?:\d+|\d{{1,3}}(?:{re.escape(group_separator)}\d{{3}})+)"
      rf"(?:{re.escape(decimal_separator)}\d{{1,2}})?"
  )
  if not re.fullmatch(pattern, num):
    return None
  try:
    value = float(
        num.replace(group_separator, "").replace(decimal_separator, ".")
    )
    return value if math.isfinite(value) else None
  except ValueError:
    return None


def get_site_balance(page):
  for sel in [
      '[data-gtm="account-balance-value-mobile"]',
      ".double-row-header-balance-info__content",
  ]:
    try:
      el = page.query_selector(sel)
      if el:
        v = _num(el.inner_text())
        if v is not None:
          return v
    except Exception:
      pass
  return None


def find_match_url(page, players):
  if not players:
    return None
  parts = [p.strip() for p in re.split(r"\s+[—–-]\s+", players) if p.strip()]

  surnames = []
  for p in parts:
    words = p.split()
    surname = words[-1] if words else p
    slugged = _slug(surname)
    if len(slugged) >= 3:
      surnames.append(slugged[:3])

  if len(surnames) != 2:
    return None

  try:
    open_league(page, timeout=15000)
    page.wait_for_timeout(3500)

    hrefs = page.eval_on_selector_all(
        "a[href*='/1691055-pro-league/']",
        "els => els.map(e => e.getAttribute('href'))",
    )

    candidates = set()
    for href in hrefs:
      if not href or "platform_type=desktop" in href:
        continue
      url = urljoin(page.url, href)
      parsed = urlparse(url)
      if parsed.scheme != "https":
        continue
      if not ("db-bet" in parsed.hostname or "dbbet" in parsed.hostname):
        continue

      path_lower = parsed.path.lower()
      if all(root in path_lower for root in surnames):
        candidates.add(url.split("?")[0].rstrip("/"))

    if len(candidates) == 1:
      return next(iter(candidates))
    elif len(candidates) > 1:
      return list(candidates)[0]
  except SiteDown:
    raise
  except Exception as e:
    print(f"Ошибка при поиске URL матча: {e}")

  return None


def _set_name(n):
  return "1st set" if n == 1 else f"{n} Set"


def clear_coupon(page):
  for _ in range(12):
    cards = page.query_selector_all(
        '[data-test="betting-quick-coupon-events-card-market-name"]'
    )
    if not cards:
      cards = page.query_selector_all('[data-test*="coupon-events-card"]')
    if not cards:
      return

    removed = False
    for sel in (
        '[data-test="betting-quick-coupon-events-card-remove"]',
        '[data-test="betting-quick-coupon-events-card-lock-remove"]',
        '[data-test*="remove"]',
    ):
      btns = page.query_selector_all(sel)
      if btns:
        try:
          btns[0].click(force=True, timeout=1500)
          removed = True
        except Exception:
          try:
            page.evaluate("b => b.click()", btns[0])
            removed = True
          except Exception:
            pass
        if removed:
          page.wait_for_timeout(400)
          break

    if removed:
      continue

    try:
      page.evaluate("""() => {
        const roots = document.querySelectorAll(
          '[data-test*="coupon"], [class*="quick-coupon"], [class*="bet-slip"]'
        );
        const clicked = new Set();
        roots.forEach(root => {
          const btns = root.querySelectorAll(
            '[data-test*="remove"], [class*="remove"], [aria-label*="remove" i], [aria-label*="close" i], [aria-label*="удал" i]'
          );
          btns.forEach(b => {
            if (clicked.has(b)) return;
            const txt = (
              b.innerText || b.getAttribute('aria-label') || b.getAttribute('data-test') || ''
            ).toLowerCase();
            if (
              txt.includes('place') || txt.includes('confirm') ||
              txt.includes('stake') || txt.includes('постав')
            ) return;
            try { b.click(); clicked.add(b); } catch (e) {}
          });
        });
      }""")
      page.wait_for_timeout(500)
    except Exception:
      pass

    left = page.query_selector_all(
        '[data-test="betting-quick-coupon-events-card-market-name"]'
    )
    if not left:
      return
  return


def prepare_bet(page, sig, stake):
  _filled["stake"] = None
  if game_of(sig) == "g21":
    return prepare_21_bet(page, sig, stake)
  if game_of(sig) == "penalty":
    return prepare_pen_bet(page, sig, stake)
  if not sig["set"]:
    raise RuntimeError("в сигнале не указан номер партии")
  if stake > MAX_SITE_STAKE:
    raise RuntimeError(
        f"сумма {money(stake)} больше максимума сайта {MAX_SITE_STAKE}"
    )

  url = find_match_url(page, sig["players"])
  if not url:
    raise RuntimeError("матч завершён или не найден в live Лиги Про")

  with lock:
    sig["match_url"] = url

  page.goto(url, wait_until="domcontentloaded")
  page.wait_for_timeout(2000)

  if page.query_selector(".market-grid-canvas"):
    raise RuntimeError(
        "открыта ПК-версия сайта — переключи DB Bet на MOBILE VERSION"
    )

  clear_coupon(page)

  set_name = _set_name(sig["set"])

  start_wait = time.time()
  tab_clicked = False
  while time.time() - start_wait < 30:
    tab_cand = page.locator(f"text='{set_name}'")
    if tab_cand.count() > 0 and tab_cand.first.is_visible():
      try:
        tab_cand.first.click(force=True)
        page.wait_for_timeout(1000)
        tab_clicked = True
        break
      except Exception:
        pass
    page.wait_for_timeout(1500)

  if not tab_clicked:
    raise RuntimeError(
        f"нет вкладки «{set_name}» (партия завершена или рынок закрыт)"
    )

  side = "Under" if sig["market"] == "ТМ" else "Over"
  line = f"{sig['line']:g}"
  label = f"{side} {line}"

  odds = None
  btn = None
  last_seen_odds = None
  start_odds_wait = time.time()

  def _is_clean_market_text(txt):
    if not txt:
      return False
    t = txt.lower().replace(",", ".")
    if side.lower() not in t or line not in t:
      return False
    other_lines = ["16.5", "17.5", "18", "18.5", "19", "19.5", "20", "20.5", "21", "21.5", "22.5"]
    for ol in other_lines:
      if ol == line:
        continue
      if re.search(rf"(?<![\d.]){re.escape(ol)}(?![\d.])", t):
        return False
    return True

  while time.time() - start_odds_wait < 20:
    try:
      market_text = page.locator(f"text=\"{label}\"")
      count = market_text.count()
      for i in range(count):
        el = market_text.nth(i)
        if not el.is_visible():
          continue

        candidates = [
          el.locator("xpath=ancestor::button[1]"),
          el.locator("xpath=ancestor::*[@role='button'][1]"),
          el.locator(
              "xpath=ancestor::*[contains(@class,'ui-market') or "
              "contains(@class,'market-button') or contains(@class,'odd') or "
              "contains(@class,'coefficient')][1]"
          ),
          el.locator("xpath=ancestor::div[contains(@class,'market') or contains(@class,'odd')][1]"),
          el,
        ]

        for cand in candidates:
          if cand.count() == 0:
            continue
          candidate = cand.first
          try:
            val_txt = candidate.inner_text()
          except Exception:
            continue
          if not _is_clean_market_text(val_txt):
            continue
          parsed = _num(val_txt)
          if parsed is None:
            continue
          last_seen_odds = parsed
          if parsed >= get_min_odds():
            btn = candidate
            odds = parsed
            break
        if btn is not None:
          break

      if btn is not None:
        break

      rows = page.locator(f"div:has-text(\"{label}\")")
      for i in range(min(rows.count(), 15)):
        row = rows.nth(i)
        if not row.is_visible():
          continue
        try:
          val_txt = row.inner_text()
        except Exception:
          continue
        if not _is_clean_market_text(val_txt):
          continue
        parsed = _num(val_txt)
        if parsed is None:
          continue
        last_seen_odds = parsed
        if parsed >= get_min_odds():
          inner = row.locator(f"text=\"{label}\"")
          if inner.count() > 0:
            btn = inner.first
          else:
            btn = row
          odds = parsed
          break
      if btn is not None:
        break

    except Exception:
      pass
    page.wait_for_timeout(800)

  if btn is None or odds is None:
    if last_seen_odds is not None and last_seen_odds < get_min_odds():
      raise RuntimeError(f"КФ {last_seen_odds} упал ниже минимума {get_min_odds()}")
    raise RuntimeError(f"«{label}»: линия заблокирована (замки) или недоступна")

  def _click_market():
    try:
      btn.scroll_into_view_if_needed()
      page.wait_for_timeout(300)
      btn.click(force=True, timeout=3000)
    except Exception:
      page.evaluate("(el) => el.click()", btn)
    page.wait_for_timeout(1200)

  def _coupon_cards():
    return page.locator(
        '[data-test="betting-quick-coupon-events-card-market-name"]'
    )

  clear_coupon(page)
  page.wait_for_timeout(400)

  _click_market()

  cards = _coupon_cards()
  if cards.count() != 1:
    clear_coupon(page)
    page.wait_for_timeout(500)
    _click_market()
    cards = _coupon_cards()

  if cards.count() > 1:
    for attempt in range(8):
      cards = _coupon_cards()
      if cards.count() <= 1:
        break
      removed = False
      for i in range(cards.count()):
        try:
          txt = cards.nth(i).inner_text().lower()
          if side.lower() in txt and line in txt:
            continue
          card_root = cards.nth(i).locator(
              "xpath=ancestor::*[contains(@data-test,'card') or contains(@class,'card')][1]"
          )
          rm = card_root.locator(
              '[data-test*="remove"], button, [class*="remove"], [class*="close"]'
          )
          if rm.count() > 0:
            rm.first.click(force=True)
            page.wait_for_timeout(400)
            removed = True
            break
        except Exception:
          pass
      if not removed:
        page.evaluate(
            """(side, line) => {
              const cards = document.querySelectorAll(
                '[data-test="betting-quick-coupon-events-card-market-name"]'
              );
              cards.forEach(c => {
                const t = (c.innerText || '').toLowerCase();
                if (!(t.includes(side.toLowerCase()) && t.includes(line))) {
                  const root = c.closest('[data-test*="card"]') || c.parentElement;
                  const btn = root && root.querySelector(
                    '[data-test*="remove"], button, [class*="remove"], [class*="close"]'
                  );
                  if (btn) btn.click();
                }
              });
            }""",
            side,
            line,
        )
        page.wait_for_timeout(500)

  cards = _coupon_cards()
  if cards.count() == 0:
    raise RuntimeError("после очистки купон пуст — рынок не добавился")
  if cards.count() != 1:
    raise RuntimeError(f"в купоне {cards.count()} событий вместо одного")

  coupon_text = cards.first.inner_text()
  if not (side.lower() in coupon_text.lower() and line in coupon_text):
    raise RuntimeError(f"в купон попал не тот исход: {coupon_text}")

  fill_stake(page, stake)
  return odds


def fill_stake(page, stake):
  """Вписывает сумму в купон и проверяет, что сайт её принял."""
  inp = None
  for sel in (
      'input.ui-number-input__field[placeholder="Enter stake"]',
      'input.ui-number-input__field[placeholder*="stake" i]',
      'input.ui-number-input__field[placeholder*="сумм" i]',
      ".quick-coupon-bet-amount input.ui-number-input__field",
      '[data-test*="stake"] input',
      '[class*="bet-amount"] input',
      '[class*="coupon"] input[type="text"]',
      '[class*="coupon"] input[type="number"]',
      'input.ui-number-input__field',
  ):
    loc = page.locator(sel)
    if loc.count() > 0:
      try:
        if loc.first.is_visible(timeout=1000):
          inp = loc.first
          break
      except Exception:
        pass
  if inp is None:
    raise RuntimeError("не найдено поле суммы в купоне")
  s = str(int(stake)) if float(stake).is_integer() else f"{stake:.2f}"
  inp.click(force=True)
  page.wait_for_timeout(200)
  inp.fill("")
  inp.fill(s)
  page.wait_for_timeout(300)
  try:
    current = inp.input_value()
  except Exception:
    current = ""
  if not _same_stake(current, stake):
    try:
      page.evaluate(
          """(el, val) => {
            el.focus();
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
          }""",
          inp,
          s,
      )
      page.wait_for_timeout(300)
      current = inp.input_value()
    except Exception:
      pass
  if not _same_stake(current, stake):
    raise RuntimeError(f"сумма в купоне отличается: '{current}' != '{s}'")
  page.wait_for_timeout(800)


# ---------- ⚽ пенальти: поиск матча и W1/W2 ----------

def pen_aliases(team_ru):
  """Русское название команды → варианты написания на сайте."""
  key = re.sub(r"\s+", " ", (team_ru or "").strip().lower().replace("ё", "е"))
  if key in PEN_TEAMS:
    return PEN_TEAMS[key]
  for ru, en in PEN_TEAMS.items():
    if key.startswith(ru + " ") or ru.startswith(key + " "):
      return en
  # команда не из таблицы: латиница как есть, кириллица — транслит
  slug = "".join(_TR.get(ch, ch) for ch in key)
  return [slug] if slug else []


def _has_team(text, aliases):
  t = (text or "").lower()
  return any(a in t for a in aliases)


# Ищет на странице самые «глубокие» элементы, где есть обе команды (строка матча),
# помечает их data-ab-hit и возвращает ссылку, если карточка — <a>.
PEN_FIND_JS = """
(args) => {
  const [a1, a2] = args;
  const has = (t, arr) => arr.some(a => t.includes(a));
  document.querySelectorAll('[data-ab-hit]').forEach(e => e.removeAttribute('data-ab-hit'));
  const els = Array.from(document.querySelectorAll('body *'));
  let n1 = 0, n2 = 0, sample = '';
  const both = [];
  for (const el of els) {
    if (el.children.length > 40) continue;
    const t = (el.innerText || '').toLowerCase();
    if (!t || t.length > 500) continue;
    const h1 = has(t, a1), h2 = has(t, a2);
    if (h1 && !el.querySelector('*') ) n1++;
    if (h2 && !el.querySelector('*') ) n2++;
    if ((h1 || h2) && !sample && t.length > 15) sample = t.replace(/\\s+/g, ' ');
    if (h1 && h2) both.push(el);
  }
  // оставляем только самые вложенные (внутри нет другого совпадения)
  const deep = both.filter(el => !both.some(o => o !== el && el.contains(o)));
  const hits = deep.map((el, i) => {
    el.setAttribute('data-ab-hit', String(i));
    const a = el.closest('a[href]');
    return {i, href: a ? a.getAttribute('href') : null,
            text: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 150)};
  });
  return {hits, diag: {n1, n2, sample, total: deep.length}};
}
"""


PEN_SEARCH_WAIT = 60  # сек: сколько ждать появления матча на сайте

PEN_SCROLL_TOP_JS = """
() => {
  window.scrollTo(0, 0);
  document.querySelectorAll('*').forEach(el => {
    if (el.scrollTop > 0) el.scrollTop = 0;
  });
}
"""

# Прокрутка на ~экран: и окно, и внутренние прокручиваемые блоки. True — дошли до конца.
PEN_SCROLL_JS = """
() => {
  let moved = false;
  const step = Math.max(300, window.innerHeight * 0.7);
  const before = window.scrollY;
  window.scrollBy(0, step);
  if (window.scrollY !== before) moved = true;
  document.querySelectorAll('*').forEach(el => {
    if (el.scrollHeight > el.clientHeight + 50) {
      const oy = getComputedStyle(el).overflowY;
      if (oy === 'auto' || oy === 'scroll') {
        const t = el.scrollTop;
        el.scrollTop = t + step;
        if (el.scrollTop !== t) moved = true;
      }
    }
  });
  return !moved;
}
"""


PEN_CLICK_FAILS = {"n": 0}


def _pen_open_hit(page, h, search_url):
  """Открывает найденную карточку: ссылка — берём адрес, иначе кликаем мышью."""
  if h.get("href") and "search" not in h["href"]:
    return urljoin(search_url, h["href"]).split("?")[0].rstrip("/")
  sel = f'[data-ab-hit="{h["i"]}"]'
  base = search_url.split("?")[0]

  def opened(timeout):
    try:
      page.wait_for_url(lambda u: u.split("?")[0] != base, timeout=timeout)
      return page.url.split("?")[0].rstrip("/")
    except Exception:
      return None

  try:
    # ставим карточку в центр экрана (видимая — не пропадёт из списка)
    page.evaluate(
        "(sel) => { const el = document.querySelector(sel);"
        " if (el) el.scrollIntoView({block: 'center'}); }", sel)
    page.wait_for_timeout(400)
    # список мог перерисоваться — заново помечаем карточки и находим эту же по тексту
    if not page.evaluate("(sel) => !!document.querySelector(sel)", sel):
      res = page.evaluate(PEN_FIND_JS, [h["a1"], h["a2"]])
      same = [x for x in res["hits"] if x["text"] == h["text"]] or res["hits"]
      if not same:
        PEN_CLICK_FAILS["n"] += 1
        return None
      sel = f'[data-ab-hit="{same[0]["i"]}"]'
    # 1) настоящий клик мышью по центру строки с командами и по самой карточке
    for target in ("el", "card"):
      box = page.evaluate(
          """([sel, target]) => {
               let el = document.querySelector(sel);
               if (!el) return null;
               if (target === 'card') {
                 let c = el;
                 for (let k = 0; k < 4 && c.parentElement; k++) {
                   c = c.parentElement;
                   if (/w1/i.test(c.innerText || '')) break;
                 }
                 el = c;
               }
               const r = el.getBoundingClientRect();
               return {x: r.left + r.width / 2, y: r.top + Math.min(r.height / 2, 40),
                       vis: r.width > 0 && r.height > 0};
             }""",
          [sel, target],
      )
      if not box or not box["vis"]:
        continue
      page.mouse.click(box["x"], box["y"])
      url = opened(5000)
      if url:
        return url
    # 2) запасной вариант — клик через JS
    page.evaluate(
        "(sel) => { const el = document.querySelector(sel);"
        " if (el) (el.closest('a,[role=button],[onclick]') || el).click(); }", sel)
    url = opened(4000)
    if url:
      return url
  except Exception:
    pass
  PEN_CLICK_FAILS["n"] += 1
  return None


def pen_find_match(page, sig):
  home, away = [x.strip() for x in sig["players"].split(" — ", 1)]
  a1, a2 = pen_aliases(home), pen_aliases(away)
  if not a1 or not a2:
    raise RuntimeError("не удалось перевести названия команд")
  url = f"https://{cur_site()}{PEN_SEARCH_PATH}"
  try:
    page.goto(url, wait_until="domcontentloaded", timeout=15000)
  except Exception as e:
    if "net::ERR" in str(e) or "Timeout" in str(e):
      raise SiteDown(f"{cur_site()} не открывается — проверь VPN Opera") from e
    raise
  problem = site_problem(page)
  if problem:
    raise SiteDown(f"{cur_site()}: {problem} — проверь VPN Opera")
  remember_site(page.url)

  with lock:
    used = {
        b.get("match_url")
        for b in state["open_bets"] + state["closed_bets"]
        if b.get("match_url")
    }
  search_url = page.url
  found, diag = [], {}
  PEN_CLICK_FAILS["n"] = 0
  deadline = time.time() + PEN_SEARCH_WAIT
  first = True
  while time.time() < deadline:
    if not first:
      # матч мог ещё не появиться на сайте — обновляем поиск и ищем снова
      page.wait_for_timeout(8000)
      try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
      except Exception:
        continue
    first = False
    page.wait_for_timeout(2500)
    # список может показывать только видимую часть — ищем на каждом шаге прокрутки
    for _ in range(40):
      try:
        res = page.evaluate(PEN_FIND_JS, [a1, a2])
      except Exception as e:
        diag = {"err": str(e)[:100]}
        break
      d = res["diag"]
      if d.get("n1", 0) + d.get("n2", 0) >= diag.get("n1", 0) + diag.get("n2", 0):
        diag = d
      for h in res["hits"]:
        h["a1"], h["a2"] = a1, a2
        url = _pen_open_hit(page, h, search_url)
        if not url:
          continue
        if url not in found:
          found.append(url)
        if url not in used:
          return url, a1, a2
        # уже ставили на этот матч — возвращаемся к поиску
        try:
          page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
          page.wait_for_timeout(2000)
        except Exception:
          pass
        break
      try:
        at_end = page.evaluate(PEN_SCROLL_JS)
      except Exception:
        break
      if at_end:
        break
      page.wait_for_timeout(350)

  if found:
    raise RuntimeError(
        f"матч {home} — {away}: на сайте только уже сыгранные этим ботом"
    )
  sample = html.escape((diag.get("sample") or "")[:120])
  if PEN_CLICK_FAILS["n"]:
    PEN_CLICK_FAILS["n"] = 0
    raise RuntimeError(
        f"матч {home} — {away} найден в поиске, но карточка не открылась по клику"
        " — пришли ссылку на матч из адресной строки, сделаю переход напрямую"
    )
  raise RuntimeError(
      f"матч {home} — {away} не найден в поиске «fifa18 penalty» · ищу как"
      f" {a1[0]} / {a2[0]} · на странице: {a1[0]} ×{diag.get('n1', '?')},"
      f" {a2[0]} ×{diag.get('n2', '?')}"
      + (f" · пример карточки: «{sample}»" if sample else "")
  )


# Карточки в поиске: для каждой карточки с обеими командами находит кнопку W1/W2,
# её КФ и время матча. Кнопку помечает data-ab-btn.
PEN_CARDS_JS = """
([a1, a2, label]) => {
  const has = (t, arr) => arr.some(a => t.includes(a));
  document.querySelectorAll('[data-ab-btn]').forEach(e => e.removeAttribute('data-ab-btn'));
  const els = Array.from(document.querySelectorAll('body *'));
  const both = els.filter(el => {
    const t = (el.textContent || '').toLowerCase();
    return t && t.length < 500 && has(t, a1) && has(t, a2);
  });
  const deep = both.filter(el => !both.some(o => o !== el && el.contains(o)));
  const out = [];
  deep.forEach((el, i) => {
    // карточка — ближайший предок, где есть и W1, и W2
    let card = el;
    for (let k = 0; k < 8 && card; k++) {
      const t = card.innerText || '';
      if (/\\bW1\\b/.test(t) && /\\bW2\\b/.test(t)) break;
      card = card.parentElement;
    }
    if (!card) return;
    // кнопка: самый маленький элемент, где текст = «W1 <число>»
    const esc = label.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&').replace(/ /g, '\\\\s+');
    const re = new RegExp('^\\\\s*' + esc + '\\\\s+(\\\\d+(?:[.,]\\\\d+)?)\\\\s*$', 'i');
    let btn = null, odds = null;
    for (const b of card.querySelectorAll('*')) {
      const m = (b.innerText || '').match(re);
      if (m) { btn = b; odds = parseFloat(m[1].replace(',', '.')); }
    }
    if (!btn) return;
    btn.setAttribute('data-ab-btn', String(i));
    const ct = (card.innerText || '').replace(/\\s+/g, ' ');
    const tm = ct.match(/\\d{2}\\/\\d{2}\\s+\\d{2}:\\d{2}/);
    const ownTxt = (el.innerText || '').replace(/\\s+/g, ' ').trim().toLowerCase();
    out.push({i, odds, time: tm ? tm[0] : '', key: (tm ? tm[0] : '') + ' ' + ownTxt,
              text: ct.slice(0, 120)});
  });
  return out;
}
"""


PEN_SEARCH_TEXT = "fifa18 penalty"


def pen_ensure_search(page):
  """Сайт иногда открывает поиск пустым — тогда вводим текст сами и ждём список.
  Возвращает True, если поле поиска найдено."""
  # поле поиска: первое видимое текстовое поле (подпись «Search championships»
  # — отдельный элемент, а не placeholder)
  found = False
  for _ in range(30):  # до 15 сек ждём, пока страница догрузится
    found = page.evaluate("""() => {
        document.querySelectorAll('[data-ab-search]').forEach(e => e.removeAttribute('data-ab-search'));
        const el = Array.from(document.querySelectorAll('input, textarea')).find(e => {
          const t = (e.getAttribute('type') || 'text').toLowerCase();
          const r = e.getBoundingClientRect();
          return ['text', 'search', ''].includes(t) && r.width > 0 && r.height > 0;
        });
        if (!el) return false;
        el.setAttribute('data-ab-search', '1');
        return true;
    }""")
    if found:
      break
    page.wait_for_timeout(500)
  if not found:
    return False
  try:
    inp = page.locator('[data-ab-search="1"]').first
    if PEN_SEARCH_TEXT in (inp.input_value() or "").lower() and re.search(
        r"\bW1\b|Events:\s*\d+",
        page.evaluate("() => (document.body.innerText || '').slice(0, 4000)") or ""):
      return True  # поиск заполнен и список уже есть
    inp.click()
    inp.fill("")
    inp.type(PEN_SEARCH_TEXT, delay=40)
    inp.press("Enter")
    for _ in range(24):  # ждём карточки или «Events: N»
      page.wait_for_timeout(500)
      txt = page.evaluate("() => (document.body.innerText || '').slice(0, 4000)")
      if re.search(r"\bW1\b|Events:\s*\d+", txt or ""):
        break
  except Exception as e:
    print("Поиск пенальти: не смог ввести текст —", e)
  return True


def pen_label(sig):
  """Подпись кнопки на сайте: W1 / W2 / TOTAL 4.5 O / TOTAL 4.5 U."""
  m = sig["market"]
  if m in ("ТБ", "ТМ"):
    return f"TOTAL {float(sig['line']):g} {'O' if m == 'ТБ' else 'U'}"
  return "W1" if m == "П1" else "W2"


def prepare_pen_bet(page, sig, stake):
  """Ставка прямо из поиска: карточка матча → кнопка W1/W2 → купон."""
  if stake > MAX_SITE_STAKE:
    raise RuntimeError(f"сумма {money(stake)} больше максимума сайта {MAX_SITE_STAKE}")
  home, away = [x.strip() for x in sig["players"].split(" — ", 1)]
  a1, a2 = pen_aliases(home), pen_aliases(away)
  if not a1 or not a2:
    raise RuntimeError("не удалось перевести названия команд")
  label = pen_label(sig)
  want = sig.get("odds")
  search_url = f"https://{cur_site()}{PEN_SEARCH_PATH}"
  try:
    page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
  except Exception as e:
    if "net::ERR" in str(e) or "Timeout" in str(e):
      raise SiteDown(f"{cur_site()} не открывается — проверь VPN Opera") from e
    raise
  problem = site_problem(page)
  if problem:
    raise SiteDown(f"{cur_site()}: {problem}")
  remember_site(page.url)
  if page.query_selector(".market-grid-canvas"):
    raise RuntimeError("открыта ПК-версия сайта — переключи DB Bet на MOBILE VERSION")
  with lock:
    used = {b.get("match_url") for b in state["open_bets"] + state["closed_bets"]
            if b.get("match_url")}

  seen = {}  # key → odds (для отчёта, если ни один не подошёл)
  deadline = time.time() + PEN_SEARCH_WAIT
  first = True
  while time.time() < deadline:
    if not first:
      # матч мог ещё не появиться — ждём и заново вводим поиск (без перезагрузки)
      page.wait_for_timeout(8000)
      try:
        page.evaluate("() => window.scrollTo(0, 0)")
        inp = page.locator('[data-ab-search="1"]')
        if inp.count():
          inp.first.fill("")
      except Exception:
        pass
    first = False
    page.wait_for_timeout(1500)
    if not pen_ensure_search(page):
      # поля поиска нет совсем — страница сломалась, только тогда перезагружаем
      try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2500)
        pen_ensure_search(page)
      except Exception:
        continue
    # 1) просматриваем ВЕСЬ список: все карточки с нужными командами и их КФ
    allc = {}
    for _ in range(40):
      try:
        cards = page.evaluate(PEN_CARDS_JS, [a1, a2, label])
      except Exception:
        cards = []
      for c in cards:
        if c["odds"]:
          allc[c["key"]] = c["odds"]
          seen[c["key"]] = c["odds"]
      try:
        at_end = page.evaluate(PEN_SCROLL_JS)
      except Exception:
        break
      if at_end:
        break
      page.wait_for_timeout(350)
    if not allc:
      continue

    # 2) выбираем лучший матч: КФ ближе всего к сигналу, сначала свободные
    fits = {k: v for k, v in allc.items()
            if not want or abs(v - want) <= PEN_MAX_ODDS_DIFF}
    used_k = {k for k in fits if f"pen:{k}|{label}" in used}
    free_k = [k for k in fits if k not in used_k]
    allow_rep = bool(state.get("pen_allow_repeat"))
    if used_k and not free_k and not allow_rep:
      t = next(iter(used_k)).split(" ")[:2]
      raise SkipSignal(
          f"на матч {' '.join(t)} {home} — {away} уже стоит ставка"
          " (сигнал из другой цепочки на тот же матч) — второй раз не ставим"
      )
    order = sorted(free_k + (sorted(used_k) if allow_rep else []),
                   key=lambda k: (k in used_k, abs(fits[k] - want) if want else 0))
    if not order:
      continue

    # 3) возвращаемся к выбранной карточке и жмём кнопку
    for target in order:
      try:
        page.evaluate(PEN_SCROLL_TOP_JS)
      except Exception:
        pass
      page.wait_for_timeout(400)
      clicked = None
      for _ in range(40):
        try:
          cards = page.evaluate(PEN_CARDS_JS, [a1, a2, label])
        except Exception:
          cards = []
        c = next((x for x in cards if x["key"] == target), None)
        if c:
          clicked = c
          break
        try:
          if page.evaluate(PEN_SCROLL_JS):
            break
        except Exception:
          break
        page.wait_for_timeout(350)
      if not clicked:
        continue
      if want and abs(clicked["odds"] - want) > PEN_MAX_ODDS_DIFF:
        continue  # КФ успел уехать, пока искали
      odds = _pen_click_btn(page, clicked, [a1, a2, label])
      if odds is None:
        continue
      if odds < get_min_odds():
        clear_coupon(page)
        raise RuntimeError(f"КФ {odds} ниже минимума {get_min_odds()}")
      with lock:
        sig["match_url"] = f"pen:{clicked['key']}|{label}"
      cards_c = page.locator('[data-test="betting-quick-coupon-events-card-market-name"]')
      if cards_c.count() != 1:
        raise RuntimeError(f"в купоне {cards_c.count()} событий вместо одного")
      card_text = cards_c.first.inner_text()
      if label in ("W1", "W2"):
        my_team = a1 if label == "W1" else a2
        ok_coupon = re.search(rf"\b{label}\b", card_text) or _has_team(card_text, my_team)
      else:
        ok_coupon = f"{float(sig['line']):g}" in card_text.replace(",", ".")
      if not ok_coupon:
        raise RuntimeError(f"в купон попал не тот исход: {card_text}")
      fill_stake(page, stake)
      return odds

  if seen:
    variants = "; ".join(f"{k[:40]} → {label} {v}" for k, v in list(seen.items())[:4])
    raise RuntimeError(
        f"{home} — {away}: нет матча с {label} около КФ {want}"
        f" (на сайте: {variants}) — матч уже идёт или ещё не появился"
    )
  try:
    n_ev = re.search(r"Events:\s*(\d+)",
                     page.evaluate("() => document.body.innerText || ''") or "")
  except Exception:
    n_ev = None
  raise RuntimeError(
      f"матч {home} — {away} не найден в поиске «fifa18 penalty» · ищу как"
      f" {a1[0]} / {a2[0]} · "
      + (f"в поиске матчей: {n_ev.group(1)}" if n_ev else "список матчей не загрузился")
  )


def _pen_click_btn(page, c, args):
  """Кликает мышью по кнопке W1/W2 карточки c. Возвращает КФ или None."""
  sel = f'[data-ab-btn="{c["i"]}"]'
  try:
    clear_coupon(page)
    page.evaluate("(sel) => { const el = document.querySelector(sel);"
                  " if (el) el.scrollIntoView({block: 'center', inline: 'center'}); }", sel)
    page.wait_for_timeout(400)
    if not page.evaluate("(sel) => !!document.querySelector(sel)", sel):
      again = [x for x in page.evaluate(PEN_CARDS_JS, args) if x["key"] == c["key"]]
      if not again:
        return None
      c = again[0]
      sel = f'[data-ab-btn="{c["i"]}"]'
    box = page.evaluate(
        """(sel) => { const el = document.querySelector(sel); if (!el) return null;
                      const r = el.getBoundingClientRect();
                      return {x: r.left + r.width / 2, y: r.top + r.height / 2}; }""",
        sel,
    )
    if not box:
      return None
    page.mouse.click(box["x"], box["y"])
    page.wait_for_timeout(1500)
    n = page.locator('[data-test="betting-quick-coupon-events-card-market-name"]').count()
    if n == 0:
      # запасной клик через JS
      page.evaluate("(sel) => { const el = document.querySelector(sel); if (el) el.click(); }", sel)
      page.wait_for_timeout(1500)
      n = page.locator('[data-test="betting-quick-coupon-events-card-market-name"]').count()
    return c["odds"] if n >= 1 else None
  except Exception:
    return None


def prepare_pen_bet_matchpage(page, sig, stake):
  if stake > MAX_SITE_STAKE:
    raise RuntimeError(f"сумма {money(stake)} больше максимума сайта {MAX_SITE_STAKE}")
  url, a1, a2 = pen_find_match(page, sig)
  with lock:
    sig["match_url"] = url
  page.goto(url, wait_until="domcontentloaded")
  page.wait_for_timeout(2500)
  if page.query_selector(".market-grid-canvas"):
    raise RuntimeError("открыта ПК-версия сайта — переключи DB Bet на MOBILE VERSION")

  label = pen_label(sig)
  # блок «1X2» и в нём кнопка W1/W2
  btn, odds = None, None
  start = time.time()
  while time.time() - start < 20 and btn is None:
    try:
      head = page.locator(
          f"xpath=//*[normalize-space(text())='{PEN_MARKET_TITLE}']"
      )
      for i in range(head.count()):
        block = head.nth(i).locator(
            f"xpath=ancestor::*[.//*[normalize-space(text())='{label}']][1]"
        )
        if block.count() == 0:
          continue
        lab = block.first.locator(f"xpath=.//*[normalize-space(text())='{label}']")
        if lab.count() == 0:
          continue
        for cand in (
            lab.first.locator("xpath=ancestor::button[1]"),
            lab.first.locator("xpath=ancestor::*[@role='button'][1]"),
            lab.first.locator("xpath=.."),
        ):
          if cand.count() == 0:
            continue
          txt = cand.first.inner_text()
          val = _num(txt.replace(label, " "))
          if val is not None and val > 1:
            btn, odds = cand.first, val
            break
        if btn is not None:
          break
    except Exception:
      pass
    if btn is None:
      page.wait_for_timeout(1000)

  if btn is None:
    raise RuntimeError(f"нет кнопки {label} в «{PEN_MARKET_TITLE}» (рынок закрыт или матч начался)")
  if odds < get_min_odds():
    raise RuntimeError(f"КФ {odds} ниже минимума {get_min_odds()}")
  want = sig.get("odds")
  if want and abs(odds - want) > PEN_MAX_ODDS_DIFF:
    raise RuntimeError(
        f"КФ на сайте {odds}, в сигнале {want} — похоже, это не тот матч"
    )

  clear_coupon(page)
  page.wait_for_timeout(400)
  try:
    btn.scroll_into_view_if_needed()
    btn.click(force=True, timeout=3000)
  except Exception:
    page.evaluate("(el) => el.click()", btn)
  page.wait_for_timeout(1200)

  cards = page.locator('[data-test="betting-quick-coupon-events-card-market-name"]')
  if cards.count() != 1:
    raise RuntimeError(f"в купоне {cards.count()} событий вместо одного")
  card_text = cards.first.inner_text()
  my_team = a1 if label == "W1" else a2
  if not (re.search(rf"\b{label}\b", card_text) or _has_team(card_text, my_team)):
    raise RuntimeError(f"в купон попал не тот исход: {card_text}")

  fill_stake(page, stake)
  return odds


# ---------- 🃏 21 очко: игра по номеру, «Да» в нужном рынке ----------

# сумма, которую prepare_*_bet реально вписала в купон (None — как просили)
_filled = {"stake": None}


def take_filled_stake(stake):
  filled, _filled["stake"] = _filled["stake"], None
  return stake if filled is None else filled


G21_FIND_JS = """([title, no]) => {
  const norm = s => (s || '').replace(/\\s+/g, ' ').trim();
  let best = null, bestLen = 1e9, numbers = [];
  for (const el of document.querySelectorAll('a, div, li, article, section')) {
    const text = el.innerText || '';
    if (text.length > 600) continue;  // большой блок — это список, а не карточка
    const lines = text.split('\\n').map(norm).filter(Boolean);
    const titles = lines.filter(l => /^21 (очко|классика)$/i.test(l));
    if (titles.length !== 1 || titles[0].toLowerCase() !== title.toLowerCase()) continue;
    const nums = lines.filter(l => /^\\d{1,6}$/.test(l)).map(Number);
    numbers.push(...nums);
    if (nums.includes(no) && text.length < bestLen) { best = el; bestLen = text.length; }
  }
  if (!best) return {found: false, numbers: Array.from(new Set(numbers))};
  best.setAttribute('data-ab-g21', String(no));
  const a = best.closest('a[href]') || best.querySelector('a[href]');
  best.scrollIntoView({block: 'center'});
  const r = best.getBoundingClientRect();
  return {found: true, href: a ? a.getAttribute('href') : null,
          x: r.left + r.width / 2, y: r.top + Math.min(r.height / 2, 40)};
}"""

G21_MARKET_JS = """(title) => {
  const norm = s => (s || '').replace(/[«»“”„"]/g, '"').replace(/\\s+/g, ' ').trim().toLowerCase();
  const want = norm(title);
  const heads = Array.from(document.querySelectorAll('body *')).filter(el =>
      el.children.length <= 3 && norm(el.innerText) === want);
  const yesRe = /^да\\s*(\\d+(?:[.,]\\d+)?)$/i;
  const isYes = el => yesRe.test((el.innerText || '').replace(/\\s+/g, ' ').trim());
  for (const h of heads) {
    let box = h;
    for (let k = 0; k < 6 && box.parentElement; k++) {
      box = box.parentElement;
      // кнопка «Да КФ»: самый вложенный элемент, где есть и «Да», и КФ
      const btn = Array.from(box.querySelectorAll('*')).find(el =>
          isYes(el) && !Array.from(el.children).some(isYes));
      if (!btn) continue;
      let locked = false;
      for (let e = btn, i = 0; e && i < 3; e = e.parentElement, i++) {
        const cls = String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className);
        if (/lock|disabled|blocked/i.test(cls) || e.getAttribute('aria-disabled') === 'true'
            || e.querySelector('[class*="lock" i]')) { locked = true; break; }
      }
      btn.scrollIntoView({block: 'center'});
      const r = btn.getBoundingClientRect();
      const odds = parseFloat(btn.innerText.replace(/\\s+/g, ' ').trim().match(yesRe)[1]
                              .replace(',', '.'));
      return {x: r.left + r.width / 2, y: r.top + r.height / 2, odds, locked};
    }
  }
  return null;
}"""


def g21_channel():
  return state.get("g21_channel") or G21_CHANNEL or None


# Самые свежие номера игр из канала: по ним старые сигналы в очереди пропускаются сразу
_g21_seen = {"bet": 0, "done": 0}


_skips = {"n": 0, "last_sent": 0.0}


def note_skip(text):
  """Пропуск устаревшего сигнала: в лог всегда, в Telegram — сводкой не чаще раза в 5 мин."""
  print("⏭", text)
  _skips["n"] += 1
  if time.time() - _skips["last_sent"] >= 300:
    n, _skips["n"], _skips["last_sent"] = _skips["n"], 0, time.time()
    send(f"⏭ Пропущено устаревших сигналов: {n} (последний: {html.escape(text)})")


def g21_stale(no):
  """Причина пропуска, если игра no уже прошла (пришли сигналы на следующие игры)."""
  if _g21_seen["done"] >= no:
    return f"игра #{no} уже сыграна — пропускаю, ставлю на следующую"
  if _g21_seen["bet"] > no:
    return f"пришёл сигнал на игру #{_g21_seen['bet']} — #{no} уже не успеть, пропускаю"
  return None


_g21_urls = {}  # номер игры → адрес её страницы (Голд и Раздача на одну игру — без повторного поиска)


def g21_open_game(page, no):
  """Находит в поиске игру «21 Очко» №no и открывает её страницу."""
  known = _g21_urls.get(no)
  if known:
    if page.url != known:
      page.goto(known, wait_until="domcontentloaded", timeout=15000)
      page.wait_for_timeout(1000)
    return page.url
  search_url = f"https://{cur_site()}{G21_SEARCH_PATH}"
  deadline = time.time() + G21_FIND_TIMEOUT
  last_numbers = []
  while True:
    try:
      page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
    except Exception as e:
      if "net::ERR" in str(e) or "Timeout" in str(e):
        raise SiteDown(f"{cur_site()} не открывается — проверь VPN Opera") from e
      raise
    problem = site_problem(page)
    if problem:
      raise SiteDown(f"{cur_site()}: {problem}")
    # Поиск грузится несколько секунд (сначала серые заглушки) — ждём на той же
    # странице и не перезагружаем: перезагрузка сбрасывает загрузку списка.
    loaded_at = time.time()
    while time.time() < deadline:
      page.wait_for_timeout(1000)
      stale = g21_stale(no)
      if stale:
        raise SkipSignal(stale)
      res = page.evaluate(G21_FIND_JS, [G21_GAME_TITLE, no])
      if res and res.get("found"):
        if res.get("href"):
          page.goto(urljoin(search_url, res["href"]), wait_until="domcontentloaded",
                    timeout=15000)
        else:
          base = page.url.split("?")[0]
          page.mouse.click(res["x"], res["y"])
          try:
            page.wait_for_url(lambda u: u.split("?")[0] != base, timeout=8000)
          except Exception:
            raise RuntimeError(f"не открылась страница игры #{no}")
        page.wait_for_timeout(1500)
        _g21_urls[no] = page.url
        for old_no in [k for k in _g21_urls if k < no - 20]:
          _g21_urls.pop(old_no, None)
        return page.url
      numbers = (res or {}).get("numbers") or []
      if numbers:
        last_numbers = numbers
        if min(numbers) > no:
          raise SkipSignal(f"игра #{no} уже прошла (в поиске с #{min(numbers)})")
      waited = time.time() - loaded_at
      # список есть, а нашей игры ещё нет — обновляем раз в 15 с;
      # список так и не появился — перезагружаем через 25 с
      if (numbers and waited > 15) or waited > 25:
        break
      if int(waited) % 4 == 3:
        try:
          page.mouse.wheel(0, 400)  # подгрузить ленивые блоки
        except Exception:
          pass
    if time.time() >= deadline:
      seen = ", ".join(str(x) for x in sorted(last_numbers)[:6])
      if not seen:
        try:
          body = page.evaluate("() => (document.body.innerText || '').slice(0, 300)")
        except Exception:
          body = ""
        seen = "нет игр; на странице: " + re.sub(r"\s+", " ", body)[:200]
      raise SkipSignal(f"игра «{G21_GAME_TITLE}» #{no} не найдена в поиске (видно: {seen})")


def _g21_coupon_limit(page):
  """Максимальная ставка из купона («от 10 ₽ до 970 ₽») или None."""
  try:
    body = page.evaluate("() => document.body.innerText || ''")
  except Exception:
    return None
  m = re.search(r"до\s*([\d\s ]+(?:[.,]\d+)?)\s*₽", body or "", re.I)
  if not m:
    return None
  try:
    return float(re.sub(r"[\s ]", "", m.group(1)).replace(",", "."))
  except ValueError:
    return None


def prepare_21_bet(page, sig, stake):
  out = next((v for v in G21_OUTCOMES.values() if v[0] == sig["market"]), None)
  if out is None:
    raise SkipSignal(f"исход {sig['market']} для 21 очко не поддерживается")
  _, block_title, coupon_word = out
  no = sig["match_no"]
  stale = g21_stale(no)
  if stale:
    raise SkipSignal(stale)

  url = g21_open_game(page, no)
  with lock:
    sig["match_url"] = url
  clear_coupon(page)

  btn = None
  searched = False
  deadline = time.time() + 20
  while time.time() < deadline:
    btn = page.evaluate(G21_MARKET_JS, block_title)
    if btn:
      break
    if not searched:
      # рынка не видно — пробуем «Поиск по рынкам»
      inp = page.locator('input[placeholder*="рынк" i]')
      if inp.count():
        try:
          inp.first.fill(coupon_word)
          searched = True
        except Exception:
          pass
    page.wait_for_timeout(1000)
  if not btn:
    raise SkipSignal(f"нет рынка «{block_title}» в игре #{no}")
  if btn.get("locked"):
    raise SkipSignal(f"игра #{no} уже началась — ставки закрыты")

  odds = float(btn["odds"])
  if odds < get_min_odds():
    raise SkipSignal(f"КФ {odds} ниже минимума {get_min_odds()}")
  want = sig.get("odds")
  if want and abs(odds - want) / want > G21_MAX_ODDS_DIFF:
    raise SkipSignal(f"КФ на сайте {odds}, в сигнале {want} — слишком большая разница")

  page.mouse.click(btn["x"], btn["y"])
  page.wait_for_timeout(1200)
  cards = page.locator('[data-test="betting-quick-coupon-events-card-market-name"]')
  if cards.count() == 0:
    raise SkipSignal(f"исход не попал в купон — игра #{no}, вероятно, уже началась")
  if cards.count() != 1:
    raise RuntimeError(f"в купоне {cards.count()} событий вместо одного")
  card_text = cards.first.inner_text()
  if coupon_word.lower() not in card_text.lower():
    raise RuntimeError(f"в купон попал не тот исход: {card_text}")

  limit = _g21_coupon_limit(page)
  amount = math.floor(min(stake, limit) if limit else stake)
  if amount < 10:
    raise SkipSignal(f"сумма {money(amount)} меньше минимальной ставки сайта")
  if limit and amount < stake:
    send(f"ℹ️ 21 очко #{no}: ставка {money(stake)} больше лимита сайта — ставлю {money(amount)}.")
  _filled["stake"] = float(amount)
  fill_stake(page, amount)
  return odds


def parse_21_post(text):
  """Сообщение из канала 21 очко (AUTO21 …) → событие, ('stop', sig) или None."""
  m = re.search(r"AUTO21\s+(BET|RESULT|STOP)\b(.*)", text or "", re.I)
  if not m:
    return None
  cmd = m.group(1).upper()
  kv = {k.lower(): v for k, v in re.findall(r"(\w+)=(\S+)", m.group(2))}
  sid = kv.get("sig")
  if not sid:
    return None
  if cmd == "STOP":
    return ("stop", sid)
  try:
    no = int(kv["game"])
  except (KeyError, ValueError):
    return None
  if cmd == "RESULT":
    win = kv.get("win")
    if win not in ("0", "1"):
      return None
    return {
        "kind": "result",
        "game": "g21",
        "result": "win" if win == "1" else "lose",
        "signal_id": f"g21:{sid}:{no}",
        "players": None,
        "set": None,
        "event_id": f"g21:{sid}:{no}:res",
    }
  out = G21_OUTCOMES.get(kv.get("out", "").upper())
  try:
    step = int(kv.get("step", ""))
    kf = float(kv["kf"].replace(",", ".")) if kv.get("kf") else None
  except ValueError:
    return None
  if out is None:
    return ("unsupported", kv.get("out", "?"))
  return {
      "kind": "signal",
      "game": "g21",
      "players": "Игрок — Дилер",
      "market": out[0],
      "odds": kf,
      "step": step,
      "set": 1,
      "line": 1.0,
      "match_no": no,
      "sig_id": sid,
  }


def _process_21_message(msg, is_edit=False):
  ev = parse_21_post(msg.text or msg.caption or "")
  if ev is None:
    return
  if isinstance(ev, tuple):
    if ev[0] == "stop":
      send(f"🃏 21 очко: цепочка {html.escape(ev[1])} остановлена сигналом STOP.")
    else:
      send(f"⚠️ 21 очко: исход {html.escape(ev[1])} пока не поддерживается — пропуск.")
    return
  roll_day()
  m_no = re.search(r"game=(\d+)", msg.text or msg.caption or "")
  if m_no:
    key = "bet" if ev["kind"] == "signal" else "done"
    _g21_seen[key] = max(_g21_seen[key], int(m_no.group(1)))
  if ev["kind"] == "signal":
    if not game_on("g21") or not state["running"]:
      return  # 21 очко выключено — сигнал тихо пропускаем
    event_id = f"g21:{ev['sig_id']}:{ev['match_no']}"
  else:
    event_id = ev["event_id"]
  try:
    enqueue_event(event_id, ev, received_at=_msg_time(msg))
  except ValueError as e:
    send(f"⚠️ 21 очко: событие отклонено: {html.escape(str(e))}")


class PlacementUnknown(RuntimeError):
  pass


def check_signal(job, stake):
  sig = job["sig"]
  if not state["running"]:
    raise RuntimeError("бот на паузе")
  # Отменяем только при смене сухой/реальный — смена ставок, каналов,
  # «Тест браузера» и т.п. уже начатую ставку больше не срывает.
  if state["dry"] != job["dry"]:
    raise RuntimeError(
        "режим сухой/реальный переключён после получения сигнала; задание отменено"
    )

  game = game_of(sig)
  if not game_on(game):
    raise RuntimeError(f"{GAMES.get(game, game)} выключен в пульте")
  max_steps = get_steps_for(game, sig.get("market") if game == "g21" else None)
  if not 1 <= sig["step"] <= max_steps or not 1 <= sig["set"] <= 7:
    raise RuntimeError(
        f"шаг {sig['step']} больше лимита ({max_steps})"
        if sig["step"] > max_steps
        else "недопустимый шаг или номер партии"
    )
  stats = state["today_dry" if job["dry"] else "today_real"]
  exposure = sum(
      b["stake"]
      for b in state["open_bets"]
      if b["dry"] == job["dry"] and b.get("post_id") != job["id"]
  )
  if get_daily_loss_limit() > 0 and -stats["profit"] + exposure + stake > get_daily_loss_limit():
    raise RuntimeError(
        "новая ставка превысит дневной лимит с учётом открытых ставок"
    )
  # Неизвестные ставки больше НЕ блокируют новые сигналы
  if player_key(sig["players"]) is None:
    raise RuntimeError("не распознаны оба игрока")
  if game == "tennis" and any(
      game_of(b) == "tennis"
      and player_key(b["players"]) == player_key(sig["players"])
      and b.get("post_id") != job["id"]
      for b in state["open_bets"]
  ):
    raise RuntimeError("по этому матчу уже есть незакрытая ставка")
  if sig.get("match_url") and any(
      b.get("match_url") == sig["match_url"]
      and b["set"] == sig["set"]
      and b["dry"] == job["dry"]
      and b.get("result") in ("win", "lose")
      for b in state["closed_bets"]
  ):
    raise RuntimeError(
        "ставка на эту партию данного события уже рассчитана; повтор отменён"
    )
  if job["dry"] and state["virtual_bank"] - exposure < stake:
    raise RuntimeError("недостаточно средств в виртуальном банке")


def bet_record(job, stake, odds, status="accepted"):
  sig = job["sig"]
  return dict(
      players=sig["players"],
      stake=stake,
      odds=odds,
      market=sig["market"],
      line=sig["line"],
      set=sig["set"],
      step=sig["step"],
      dry=job["dry"],
      time=time.time(),
      post_id=job["id"],
      status=status,
      match_url=sig.get("match_url"),
      game=game_of(sig),
      match_no=sig.get("match_no"),
      team=sig.get("team"),
  )


def _find_place_bet_button(page):
  selectors = [
      '[data-test="betting-quick-coupon-footer-place-bet"]',
      '[data-test*="place-bet"]',
      'button:has-text("Place a bet")',
      'button:has-text("Place bet")',
      'button:has-text("Сделать ставку")',
      'button:has-text("Поставить")',
      '[class*="place-bet"]',
      'button[class*="place"]',
  ]
  for sel in selectors:
    try:
      loc = page.locator(sel)
      if loc.count() > 0:
        btn = loc.first
        try:
          if btn.is_visible(timeout=1500):
            return btn
        except Exception:
          pass
    except Exception:
      pass
  return None


def place_bet_real(page, job, stake):
  """Возвращает (КФ, баланс после ставки, поставленная сумма)."""
  sig = job["sig"]
  odds = prepare_bet(page, sig, stake)
  stake = take_filled_stake(stake)

  btn = None
  for _ in range(25):
    btn = _find_place_bet_button(page)
    if btn is not None:
      try:
        enabled = btn.is_enabled(timeout=500)
      except Exception:
        enabled = False
      if enabled:
        break
      btn = None
    page.wait_for_timeout(250)
  else:
    try:
      found = page.evaluate("""() => {
        const texts = ['place a bet', 'place bet', 'сделать ставку', 'поставить'];
        const btns = document.querySelectorAll('button, [role="button"], a');
        for (const b of btns) {
          const t = (b.innerText || '').toLowerCase().trim();
          if (texts.some(x => t.includes(x))) {
            const style = window.getComputedStyle(b);
            if (style.display !== 'none' && style.visibility !== 'hidden') {
              return true;
            }
          }
        }
        return false;
      }""")
      if not found:
        raise RuntimeError("кнопка Place a bet не найдена в купоне")
    except RuntimeError:
      raise
    except Exception as e:
      raise RuntimeError(f"кнопка Place a bet неактивна/не найдена: {e}") from e

  with lock:
    check_signal(job, stake)
    bal_before = get_site_balance(page)
    if bal_before is None or bal_before < stake:
      raise RuntimeError("баланс недоступен или недостаточен; размещение отменено")
    state["open_bets"].append(bet_record(job, stake, odds, "placing"))
    save_state()
    try:
      if btn is not None:
        btn.click(timeout=3000)
      else:
        page.evaluate("""() => {
          const texts = ['place a bet', 'place bet', 'сделать ставку', 'поставить'];
          const btns = document.querySelectorAll('button, [role="button"], a');
          for (const b of btns) {
            const t = (b.innerText || '').toLowerCase().trim();
            if (texts.some(x => t.includes(x))) {
              b.click();
              return;
            }
          }
        }""")
    except Exception as e:
      raise PlacementUnknown(
          "ошибка во время нажатия Place a bet; ставка могла пройти"
      ) from e
  try:
    for _ in range(40):
      page.wait_for_timeout(500)
      bal = get_site_balance(page)
      if bal is not None and abs(bal - (bal_before - stake)) <= 0.01:
        return odds, bal, stake
  except Exception as e:
    raise PlacementUnknown(
        "соединение потеряно после нажатия Place a bet; ставка могла пройти"
    ) from e
  raise PlacementUnknown(
      "после нажатия Place a bet сайт не подтвердил списание; проверь купон и"
      " историю ставок вручную"
  )


def event_job(item):
  job = dict(item)
  job["fn"] = job_bet if item["kind"] == "signal" else job_result
  job["sig" if item["kind"] == "signal" else "result"] = item["payload"]
  return job


def drop_pending(game):
  """Выключили игру — убираем её ещё не начатые сигналы из очереди и из inbox."""
  removed = 0
  with jobs.mutex:
    for dq in (jobs.urgent, jobs.normal):
      keep = [j for j in dq if not (j.get("fn") == job_bet and game_of(j.get("sig")) == game)]
      removed += len(dq) - len(keep)
      dq.clear()
      dq.extend(keep)
  with lock:
    before = len(state["inbox"])
    state["inbox"] = [
        x for x in state["inbox"]
        if not (x["kind"] == "signal" and game_of(x["payload"]) == game)
    ]
    if len(state["inbox"]) != before:
      save_state()
  return removed


def finish_event(event_id, review=False, retryable=False):
  with lock:
    previous = copy.deepcopy(state)
    for item in state["inbox"]:
      if item["id"] == event_id:
        if review:
          item["status"] = "review"
        elif retryable:
          item["status"] = "failed"
        else:
          state["inbox"].remove(item)
          state["processed_posts"].append(event_id)
          state["processed_posts"] = state["processed_posts"][-2000:]
        try:
          save_state()
        except Exception:
          state.clear()
          state.update(previous)
          raise
        return


def execute_job(job, page=None):
  outcome = job["fn"](page, job)
  if "id" not in job:
    return
  if outcome == "retry":
    finish_event(job["id"], retryable=True)
  else:
    finish_event(job["id"], review=outcome is False)


PAGE_RECYCLE_EVERY = 15  # через столько заданий вкладка заменяется новой (память)
# Бот держит ровно одну вкладку DB Bet: остальные (старые после переподключения,
# открытые сайтом в новом окне) закрываются. False — закрывать только упавшие.
CLOSE_EXTRA_TABS = True
_tab = {"page": None, "uses": 0}


def _is_dbbet_url(url):
  url = url or ""
  return "db-bet" in url or "dbbet" in url


def _tab_dead(pg):
  try:
    if pg is None or pg.is_closed():
      return True
    body = pg.evaluate(
        "() => (document.body && document.body.innerText || '').slice(0, 400)",
    )
    return bool(re.search(r"Out of memory|Aw, Snap|Опаньки|нехватк\w* памяти", body or "", re.I))
  except Exception:
    return True  # вкладка упала (Target crashed) или не отвечает


def close_extra_tabs(browser, keep):
  """Закрывает лишние вкладки DB Bet и страницы ошибок, кроме keep."""
  if keep is None:
    return 0  # своей вкладки нет — ничего не трогаем
  closed = 0
  for ctx in browser.contexts:
    for other in list(ctx.pages):
      if other == keep:
        continue
      url = other.url or ""
      error_tab = url.startswith(("chrome-error://", "opera-error://"))
      if not (_is_dbbet_url(url) or error_tab):
        continue
      if CLOSE_EXTRA_TABS or error_tab or _tab_dead(other):
        try:
          other.close()
          closed += 1
        except Exception:
          pass
  if closed:
    print(f"Закрыто лишних вкладок DB Bet: {closed}")
  return closed


def adopt_tab(browser):
  """После (пере)подключения к Opera старые вкладки DB Bet не трогаем скриптами:
  зависшая вкладка не отвечает, и бот повис бы вместе с ней. fresh_page откроет
  новую вкладку и закроет остальные (закрытие работает и для зависших)."""
  _tab["page"], _tab["uses"] = None, 0
  return None


def fresh_page(browser):
  """Своя вкладка DB Bet: новая, если старая упала или отработала свой срок."""
  pg = _tab["page"]
  dead = _tab_dead(pg)
  if dead or _tab["uses"] >= PAGE_RECYCLE_EVERY:
    if pg is not None and dead:
      send("♻️ Вкладка DB Bet упала (нехватка памяти) — открываю новую.")
    try:
      if pg is not None and not pg.is_closed():
        pg.close()
    except Exception:
      pass
    pg = None
    try:
      ctx = browser.contexts[0] if browser.contexts else browser.new_context()
      pg = ctx.new_page()
      pg.goto(f"https://{cur_site()}/en", wait_until="domcontentloaded", timeout=20000)
      pg.wait_for_timeout(2000)
    except Exception as e:
      print("Не удалось открыть новую вкладку:", e)
      if pg is None:
        pg = find_page(browser)
    _tab["page"], _tab["uses"] = pg, 0
  _tab["uses"] += 1
  close_extra_tabs(browser, pg)
  return pg


_login = {"last_try": 0.0}


def is_logged_out(page):
  """Нет баланса, а в шапке есть «Log in»/«Registration»."""
  try:
    if get_site_balance(page) is not None:
      return False
    return bool(page.evaluate(
        """() => Array.from(document.querySelectorAll('button, a'))
              .some(b => /^(log in|registration|вход|регистрация)$/i
                         .test((b.innerText || '').trim()))"""
    ))
  except Exception:
    return False


def ensure_login(page):
  """Если разлогинен — входит по LOGIN_ID/LOGIN_PASSWORD. True — вошли/и так в аккаунте."""
  if page is None or not LOGIN_ID or not LOGIN_PASSWORD:
    return True
  if not is_logged_out(page):
    return True
  if time.time() - _login["last_try"] < 300:
    return False  # не долбим вход чаще раза в 5 минут
  _login["last_try"] = time.time()
  back = page.url
  try:
    page.goto(f"https://{cur_site()}/en/user/login", wait_until="domcontentloaded",
              timeout=20000)
    page.wait_for_timeout(2500)
    # форма рисуется с задержкой — ждём поле пароля
    try:
      page.wait_for_selector('input[type="password"]', state="visible", timeout=5000)
    except Exception:
      # полей нет — жмём «Log in» в шапке, после этого появляется форма
      page.evaluate("""() => {
          const b = Array.from(document.querySelectorAll('button, a, [role=button]'))
            .find(x => /^(log in|вход|войти)$/i.test((x.innerText || '').trim())
                       && x.getBoundingClientRect().width > 0);
          if (b) b.setAttribute('data-ab-open-login', '1');
      }""")
      opener = page.locator('[data-ab-open-login="1"]')
      if opener.count():
        opener.first.click(timeout=3000)
      try:
        page.wait_for_selector('input[type="password"]', state="visible", timeout=12000)
      except Exception:
        pass
    tab = page.get_by_text("By email", exact=True)
    if tab.count():
      try:
        tab.first.click(timeout=3000)
        page.wait_for_timeout(700)
      except Exception:
        pass
    pwd = page.locator('input[type="password"]')
    # поле логина: первое видимое текстовое поле (без type, text, email, tel) перед паролем
    idx = page.evaluate("""() => {
        const all = Array.from(document.querySelectorAll('input'));
        const vis = el => { const r = el.getBoundingClientRect();
                            return r.width > 0 && r.height > 0; };
        const pw = all.find(el => el.type === 'password' && vis(el));
        const ok = el => vis(el) && ['text', 'email', 'tel', ''].includes(
                        (el.getAttribute('type') || '').toLowerCase());
        let cands = all.filter(ok);
        if (pw) cands = cands.filter(el =>
            el.compareDocumentPosition(pw) & Node.DOCUMENT_POSITION_FOLLOWING);
        const el = cands[cands.length - 1];
        if (!el) return -1;
        el.setAttribute('data-ab-login', '1');
        return 1;
    }""")
    login_inp = page.locator('[data-ab-login="1"]').first if idx == 1 else None
    if login_inp is None or not pwd.count():
      fields = page.evaluate("""() => Array.from(document.querySelectorAll('input'))
          .map(e => (e.getAttribute('type') || '-') + ':' + (e.placeholder || e.name || ''))
          .slice(0, 8).join(', ')""")
      raise RuntimeError(f"не нашёл поля логина/пароля (на странице: {fields or 'нет полей'})")
    login_inp.click()
    login_inp.fill(LOGIN_ID)
    pwd.first.click()
    pwd.first.fill(LOGIN_PASSWORD)
    page.wait_for_timeout(300)
    # кнопка «LOG IN» после поля пароля (в шапке тоже есть «Log in» — её не трогаем)
    marked = page.evaluate("""() => {
        const pw = Array.from(document.querySelectorAll('input[type=password]'))
                     .find(e => e.getBoundingClientRect().width > 0);
        const btns = Array.from(document.querySelectorAll('button, [role=button], input[type=submit]'))
          .filter(b => /^(log in|войти|вход)$/i.test((b.innerText || b.value || '').trim()))
          .filter(b => !pw || (pw.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING));
        if (!btns.length) return false;
        btns[0].setAttribute('data-ab-submit', '1');
        return true;
    }""")
    if marked:
      page.locator('[data-ab-submit="1"]').first.click(timeout=3000)
    else:
      pwd.first.press("Enter")
    for _ in range(30):
      page.wait_for_timeout(500)
      if get_site_balance(page) is not None:
        send("🔐 Сайт разлогинил — бот вошёл заново.")
        return True
    body = page.evaluate("() => (document.body.innerText || '').slice(0, 2000)")
    why = ("нужна капча/код" if re.search(r"captcha|капч|code|код", body, re.I)
           else "баланс не появился")
    send(f"🔴 Не удалось войти на DB Bet автоматически ({why}) — войди вручную в Opera.")
    return False
  except Exception as e:
    send(f"🔴 Автовход не сработал: {html.escape(str(e)[:150])} — войди вручную в Opera.")
    return False
  finally:
    try:
      if back and "/user/login" not in back and page.url != back:
        page.goto(back, wait_until="domcontentloaded", timeout=15000)
    except Exception:
      pass


# ---------- свой браузер (Chromium, запускает бот) ----------

class OwnBrowser:
  """Обёртка над persistent-контекстом Chromium с тем же интерфейсом, что у
  браузера Opera по CDP: .contexts, .is_connected(), .new_context()."""

  def __init__(self, ctx):
    self.ctx = ctx
    self.closed = False
    ctx.on("close", lambda *_: setattr(self, "closed", True))

  @property
  def contexts(self):
    return [] if self.closed else [self.ctx]

  def is_connected(self):
    if self.closed:
      return False
    try:
      self.ctx.cookies("https://example.com")  # запрос в браузер: умер — будет ошибка
      return True
    except Exception:
      self.closed = True
      return False

  def new_context(self):
    return self.ctx

  def close(self):
    try:
      self.ctx.close()
    except Exception:
      pass
    self.closed = True


def _proxy_settings(url):
  """socks5://user:pass@host:port → настройки прокси для Playwright."""
  if not url:
    return None
  u = urlparse(url)
  out = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
  if u.username:
    out["username"] = u.username
    out["password"] = u.password or ""
  return out


def kill_own_browser():
  """Принудительно закрывает Chromium бота (по папке профиля): зависший браузер
  иначе держит задание вечно, а профиль занят и новый не запустится.
  Ищем только процессы chrome с этим --user-data-dir, а не всё, где встречается
  путь, — иначе команда закрыла бы сама себя."""
  try:
    if os.name == "nt":
      prof = BROWSER_PROFILE.replace("'", "''")
      subprocess.run(
          ["powershell", "-NoProfile", "-Command",
           "Get-CimInstance Win32_Process -Filter \"Name LIKE 'chrome%'\" | Where-Object {"
           f" $_.CommandLine -like '*--user-data-dir={prof}*' }} |"
           " ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"],
          timeout=30, capture_output=True,
      )
    else:
      out = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True,
                           timeout=10).stdout
      for line in out.splitlines():
        pid, _, args = line.strip().partition(" ")
        if "chrom" in args.split(" ")[0] and f"--user-data-dir={BROWSER_PROFILE}" in args:
          try:
            os.kill(int(pid), 9)
          except Exception:
            pass
  except Exception as e:
    print("Не удалось закрыть браузер бота:", e)


def install_chromium():
  """Ставит Chromium для Playwright (один раз, ~150 МБ, 1–3 минуты)."""
  send("⏳ Устанавливаю Chromium для своего браузера (1–3 минуты)…")
  r = subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"],
                     capture_output=True, text=True, timeout=900)
  if r.returncode != 0:
    raise RuntimeError("установка Chromium не удалась: "
                       + (r.stderr or r.stdout or "")[-300:])
  send("✅ Chromium установлен.")


def launch_own_browser(p):
  try:
    return _launch_own_browser(p)
  except Exception as e:
    if "Executable doesn't exist" not in str(e) and "playwright install" not in str(e):
      raise
  install_chromium()  # Chromium ещё не скачан — ставим сами и запускаем снова
  return _launch_own_browser(p)


def _launch_own_browser(p):
  kill_own_browser()  # хвост от прошлого запуска держит профиль
  device = dict(p.devices.get(BROWSER_DEVICE) or {})
  device.pop("default_browser_type", None)
  ctx = p.chromium.launch_persistent_context(
      BROWSER_PROFILE,
      headless=False,
      proxy=_proxy_settings(BROWSER_PROXY),
      locale="ru-RU",
      args=[
          "--no-first-run",
          "--disable-extensions",
          "--disable-gpu",  # меньше сбоев отрисовки и памяти
          "--disable-features=Translate,MediaRouter",
          "--disable-background-networking",
      ],
      **device,
  )
  return OwnBrowser(ctx)


def browser_mode():
  return "own" if state.get("browser_mode") == "own" else "opera"


def browser_name():
  return "свой Chromium" if browser_mode() == "own" else "Opera"


JOB_HANG_LIMIT = 300  # сек: дольше задание идти не может — значит, браузер завис
_busy = {"since": None, "what": ""}


def watchdog_loop():
  """Если браузер завис (вкладка не отвечает), задание висит вечно и бот молча
  перестаёт ставить. Тогда сообщаем и перезапускаем бота — Skript Manager
  запустит его заново, бот откроет новую вкладку, а зависшую закроет."""
  while True:
    time.sleep(10)
    since = _busy["since"]
    if since and time.time() - since > JOB_HANG_LIMIT and browser_mode() == "own" \
        and not _busy.get("killed"):
      # свой браузер можно перезапустить, не трогая бота: зависшая команда
      # получит ошибку, и бот запустит браузер заново
      _busy["killed"] = True
      send(f"🔴 Браузер не отвечает {int(time.time() - since)} с"
           f" (задание: {html.escape(_busy['what'])}). Перезапускаю браузер.")
      kill_own_browser()
      continue
    if since and time.time() - since > JOB_HANG_LIMIT + (90 if _busy.get("killed") else 0):
      send(
          f"🔴 Браузер не отвечает {int(time.time() - since)} с"
          f" (задание: {html.escape(_busy['what'])}). Перезапускаю бота — если он"
          " не поднимется сам, запусти его заново и проверь Opera."
      )
      os._exit(3)


def _job_title(job):
  try:
    sig = job.get("sig")
    return describe(sig) if sig else getattr(job.get("fn"), "__name__", "?")
  except Exception:
    return "?"


_launch_warned = {"done": False}


def browser_worker():
  p = None
  browser = None
  mode = browser_mode()
  while True:
    job = jobs.get()
    _busy["since"], _busy["what"], _busy["killed"] = time.time(), _job_title(job), False
    try:
      if job["fn"] == job_result:
        execute_job(job)
        continue
      if browser is not None and mode != browser_mode():
        if isinstance(browser, OwnBrowser):
          browser.close()
        browser = None  # режим переключили командой /browser
      if browser is None or not browser.is_connected():
        try:
          if p is None:
            p = sync_playwright().start()
          mode = browser_mode()
          if mode == "own":
            browser = launch_own_browser(p)
          else:
            browser = p.chromium.connect_over_cdp(CDP_URL, timeout=5000)
          adopt_tab(browser)
        except Exception as e:
          print("Браузер не запустился:", e)
          if browser_mode() == "own" and not _launch_warned.get("done"):
            _launch_warned["done"] = True
            send(f"❌ Свой браузер не запустился: <code>{html.escape(str(e)[:300])}</code>"
                 "\nЕсли Chromium не установлен: <code>playwright install chromium</code>."
                 " Вернуться на Opera: /browser opera")
          browser = None
          execute_job(job)
          continue
        _launch_warned["done"] = False
      page = fresh_page(browser)
      ensure_login(page)
      execute_job(job, page)
    except Exception as e:
      # Переподключаемся только если связь с Opera действительно потеряна:
      # иначе на каждую ошибку открывалась бы новая вкладка, а старая оставалась.
      try:
        if browser is not None and not browser.is_connected():
          browser = None
      except Exception:
        browser = None
      # Не ставим на паузу — только лог и продолжаем
      send(
          f"⚠️ Ошибка обработки (бот продолжает работу): "
          f"<code>{html.escape(str(e))}</code>"
      )
      traceback.print_exc()
    finally:
      _busy["since"] = None
      jobs.task_done()


def job_test(page, job):
  if not page:
    send(f"❌ Не удалось открыть вкладку {cur_site()} ({browser_name()}).")
    return
  shot = page.screenshot()
  bal = get_site_balance(page)
  mob = (
      " мобильная версия"
      if not page.query_selector(
          ".market-grid-canvas, .double-row-header-balance"
      )
      else " ПК-версия (нужна мобильная!)"
  )
  cap = f"✅ Браузер на связи ({browser_name()})\n{page.url}\n{mob}"
  if bal is not None:
    cap += f"\nБаланс на сайте: {money(bal)}"
  bot.send_photo(ADMIN_ID, shot, caption=cap)


def warn_last_step(sig):
  game = game_of(sig)
  steps = get_steps_for(game, sig.get("market") if game == "g21" else None)
  if sig["step"] >= steps:
    send(
        f"⚠️ Это последний шаг догона ({sig['step']}/{steps})!\n"
        f"{html.escape(sig['players'] or '')} — {html.escape(describe(sig))}"
    )


def job_bet(page, job):
  sig = job["sig"]
  game = game_of(sig)
  stake = stake_for(sig["step"], game, sig.get("market"))
  title = html.escape(sig["players"] or "матч не распознан")

  def head(odds):
    return (
        " "
        + title
        + "\n"
        + html.escape(describe(sig))
        + " · КФ "
        + str(odds)
        + "\nШаг догона: "
        + str(sig["step"])
        + " из "
        + str(get_steps_for(game, sig.get("market") if game == "g21" else None))
        + "\nСумма: "
        + money(stake)
    )

  def not_placed(reason):
    shot = None
    try:
      shot = page.screenshot() if page else None
    except Exception:
      pass

    match_url = sig.get("match_url", "")
    link_str = (
        " <a href='" + match_url + "'>Ссылка на матч в браузере</a>"
        if str(match_url).startswith("http")
        else ""
    )

    # Автоматически удаляем из очереди, чтобы бот не зависал и шел дальше
    finish_event(job["id"])

    text = (
        "⚠️ Ставка НЕ поставлена (сигнал пропущен)\n "
        + title
        + "\nПричина: "
        + html.escape(reason)
        + link_str
    )
    try:
      if shot:
        bot.send_photo(ADMIN_ID, shot, caption=text[:1024], parse_mode="HTML")
      else:
        send(text, parse_mode="HTML")
    except Exception as net_err:
      print(f"⚠️ Ошибка отправки в Telegram: {net_err}")
    return None

  if not game_on(game) or not state["running"]:
    print(f"⏭ {describe(sig)}: игра выключена или бот на паузе — пропуск")
    return  # тихо: после выключения игры в очереди могут остаться десятки сигналов

  max_age = {"g21": G21_SIGNAL_MAX_AGE, "penalty": PEN_SIGNAL_MAX_AGE}.get(game)
  age = time.time() - float(job.get("received_at") or time.time())
  if max_age and age > max_age:
    note_skip(f"{describe(sig)}: сигнал устарел ({int(age // 60)} мин {int(age % 60)} с)")
    return  # без браузера: после перезапуска таких десятки

  if game == "g21":
    stale = g21_stale(sig.get("match_no") or 0)
    if stale:
      note_skip(f"{describe(sig)}: {stale}")
      return  # без браузера — очередь сразу идёт дальше

  reject_reason = None
  with lock:
    existing = next(
        (
            b
            for b in state["open_bets"] + state["closed_bets"]
            if b.get("post_id") == job["id"]
        ),
        None,
    )
    if existing:
      return
    try:
      check_signal(job, stake)
    except RuntimeError as e:
      reject_reason = str(e)
  if reject_reason:
    return not_placed(reject_reason)
  if not page:
    return not_placed(f"вкладка {cur_site()} не открыта или браузер недоступен")

  MAX_RETRIES = 3  # Снижено до 3 быстрых попыток
  RETRY_DELAY = 3  # 3 секунды задержка между попытками
  last_error = None

  for attempt in range(1, MAX_RETRIES + 1):
    if attempt > 1 and (not game_on(game) or not state["running"]):
      print(f"⏭ {describe(sig)}: игру выключили — повторы прекращены")
      return
    try:
      if job["dry"]:
        odds = prepare_bet(page, sig, stake)
        stake = take_filled_stake(stake)
        with lock:
          check_signal(job, stake)
          previous = copy.deepcopy(state)
          state["open_bets"].append(bet_record(job, stake, odds))
          state["today_dry"]["bets"] += 1
          try:
            save_state()
          except Exception:
            state.clear()
            state.update(previous)
            raise
        try:
          match_url = sig.get("match_url", "")
          link_str = (
              " <a href='" + match_url + "'>Ссылка на матч</a>" if str(match_url).startswith("http") else ""
          )
          bot.send_photo(
              ADMIN_ID,
              page.screenshot(),
              caption=(
                  " СУХОЙ РЕЖИМ — ставка записана:\n" + head(odds) + link_str
              ),
              parse_mode="HTML",
          )
          warn_last_step(sig)
        except Exception as e:
          print(f"Сухая ставка записана, но скриншот не ушел из-за сети: {e}")
        return

      else:
        odds, bal, stake = place_bet_real(page, job, stake)
        with lock:
          previous = copy.deepcopy(state)
          bet = next(
              b for b in state["open_bets"] if b.get("post_id") == job["id"]
          )
          bet["status"] = "accepted"
          state["bank"] = bal
          state["bank_updated_at"] = time.time()
          state["today_real"]["bets"] += 1
          try:
            save_state()
          except Exception:
            state.clear()
            state.update(previous)
            raise
        match_url = sig.get("match_url", "")
        link_str = (
            " <a href='" + match_url + "'>Ссылка на матч</a>" if str(match_url).startswith("http") else ""
        )
        send(
            "✅ Ставка записана\n"
            + head(odds)
            + "\nБаланс сайта: "
            + money(bal)
            + link_str,
            parse_mode="HTML",
        )
        warn_last_step(sig)
        return

    except PlacementUnknown as e:
      with lock:
        bet = next(
            (
                b
                for b in state["open_bets"]
                if b.get("post_id") == job["id"]
            ),
            None,
        )
        if bet is not None:
          bet["status"] = "unknown"
          save_state()
      match_url = sig.get("match_url", "")
      link_str = (
          " <a href='" + match_url + "'>Ссылка на матч</a>" if str(match_url).startswith("http") else ""
      )
      send(
          f"⚠️ Размещение {html.escape(job['id'])} не подтверждено:"
          f" {html.escape(str(e))}. Бот НЕ на паузе, продолжает работу."
          f"{link_str} По возможности проверь историю сайта:"
          " /confirm ID placed КФ или /confirm ID cancel.",
          parse_mode="HTML",
      )
      return

    except SiteDown as e:
      # Сайт/VPN лежит — повторять бессмысленно, сразу сообщаем
      mark_site(str(e))
      return not_placed(str(e))

    except SkipSignal as e:
      try:
        clear_coupon(page)
      except Exception:
        pass
      return not_placed(str(e))

    except Exception as e:
      last_error = e
      with lock:
        bet = next(
            (
                b
                for b in state["open_bets"]
                if b.get("post_id") == job["id"] and b.get("status") == "placing"
            ),
            None,
        )
        if bet is not None:
          state["open_bets"].remove(bet)
          try:
            save_state()
          except Exception:
            pass

      if attempt < MAX_RETRIES and game != "g21" and jobs.urgent_waiting():
        return not_placed(
            f"{last_error} · повторы прерваны: в очереди ставки 🃏 21 очко"
        )
      if attempt < MAX_RETRIES:
        send(
            f"⏳ Попытка {attempt}/{MAX_RETRIES} не удалась: "
            f"{html.escape(str(e)[:150])}\n"
            f"Повтор через {RETRY_DELAY} сек…"
        )
        try:
          clear_coupon(page)
        except Exception:
          pass
        time.sleep(RETRY_DELAY)
        continue
      else:
        return not_placed(
            f"после {MAX_RETRIES} попыток: {last_error}"
        )


def _post_id_matches(bet_id, ref):
  if not bet_id or not ref:
    return False
  bet_id = str(bet_id)
  ref = str(ref)
  if bet_id == ref:
    return True
  if bet_id.startswith(ref + ":"):
    return True
  if ref.startswith(bet_id + ":"):
    return True
  return False


def handle_result(r):
  with lock:
    if r.get("event_id") and any(
        b.get("result_id") == r["event_id"] for b in state["closed_bets"]
    ):
      return True
    ref = r.get("signal_id")
    key = player_key(r.get("players"))
    candidates = []
    for bet in state["open_bets"]:
      status = bet.get("status", "accepted")
      # итог с точным ID ставки закрывает и неподтверждённую ставку
      # (баланс на сайте иногда обновляется позже, чем бот ждёт)
      exact = bool(ref) and bet.get("post_id") == ref
      if status != "accepted" and not (exact and status in ("unknown", "placing")):
        continue
      if ref:
        matches = _post_id_matches(bet.get("post_id"), ref)
        if key is not None and player_key(bet["players"]) != key:
          if not matches:
            matches = False
        if r.get("set") is not None and bet["set"] != r["set"]:
          matches = False
      else:
        matches = (
            key is not None
            and r.get("set") is not None
            and (player_key(bet["players"]) == key and bet["set"] == r["set"])
        )
        if matches and any(
            player_key(old["players"]) == key and old["set"] == r.get("set")
            for old in state["closed_bets"]
        ):
          matches = False
      if matches:
        candidates.append(bet)
    if len(candidates) != 1:
      return len(candidates) == 0
    b = candidates[0]
    previous = copy.deepcopy(state)
    state["open_bets"].remove(b)
    stats = state["today_dry" if b["dry"] else "today_real"]
    unconfirmed = b.get("status", "accepted") != "accepted"
    if unconfirmed:
      b["status"] = "accepted"
      stats["bets"] += 1
    if r["result"] == "void":
      profit = 0.0  # матч не состоялся / итог не пришёл — ставка возвращена
    elif r["result"] == "win":
      profit = round(b["stake"] * (b["odds"] - 1), 2)
    else:
      profit = -b["stake"]
    if r["result"] != "void":
      stats["win" if r["result"] == "win" else "lose"] += 1
    stats["profit"] = round(stats["profit"] + profit, 2)
    if b["dry"]:
      state["virtual_bank"] = round(state["virtual_bank"] + profit, 2)
    else:
      state["bank"] = None
      state["bank_updated_at"] = None
    b["result"] = r["result"]
    b["result_id"] = r.get("event_id")
    state["closed_bets"].append(b)
    exposure = sum(
        x["stake"] for x in state["open_bets"] if x["dry"] == b["dry"]
    )
    limit_hit = (
        state["dry"] == b["dry"]
        and get_daily_loss_limit() > 0
        and -stats["profit"] + exposure >= get_daily_loss_limit()
    )
    try:
      save_state()
    except Exception:
      state.clear()
      state.update(previous)
      raise
    match_url = b.get("match_url", "")
    link_str = (
        " <a href='" + match_url + "'>Ссылка на матч</a>" if str(match_url).startswith("http") else ""
    )

    res_icon = {"win": "✅", "lose": "❌", "void": "➖ возврат"}[r["result"]]
    text = (
        ("🧪" if b["dry"] else "💰")
        + " Результат "
        + html.escape(str(b.get("post_id", "?")))
        + "\n"
        + html.escape(b["players"])
        + "\n"
        + html.escape(describe(b))
        + "\n"
        + res_icon
        + " "
        + f"{profit:+.2f}"
        + link_str
        + ("\n⚠️ ставка не была подтверждена сайтом — проверь в истории ставок"
           if unconfirmed else "")
        + "\nЗа сегодня: "
        + money(stats["profit"])
        + f" ({stats['win']} ✅ / {stats['lose']} ❌)"
    )
  send(text, parse_mode="HTML")
  if not b["dry"]:
    jobs.put({"fn": job_balance})
  if limit_hit:
    send(
        "⚠️ Дневной стоп-лосс достигнут — новые ставки будут отклоняться, "
        "но бот НЕ на паузе (продолжает слушать канал)."
    )
  return True


START_TS = 0.0  # когда бот запущен (время Telegram); сигналы до него не ставим
_old_skipped = {"n": 0}


def enqueue_event(event_id, payload, received_at=None):
  validate_payload(payload)
  if (payload["kind"] == "signal" and received_at is not None
      and START_TS and received_at < START_TS - 2):
    # пришёл, пока бот был выключен (Telegram отдаёт накопившееся после запуска)
    _old_skipped["n"] += 1
    print(f"⏭ сигнал {event_id} отправлен до запуска бота — пропуск")
    return False
  with lock:
    if event_id in state["processed_posts"]:
      return False
    existing = next((x for x in state["inbox"] if x["id"] == event_id), None)
    if existing is not None and existing.get("status") != "failed":
      return False
    item = dict(
        id=event_id,
        kind=payload["kind"],
        payload=payload,
        status="pending",
        received_at=time.time() if received_at is None else received_at,
        dry=state["dry"],
        generation=state["generation"],
    )
    previous = copy.deepcopy(state)
    if existing is not None:
      state["inbox"].remove(existing)
    state["inbox"].append(item)
    try:
      save_state()
    except Exception:
      state.clear()
      state.update(previous)
      raise
    jobs.put(event_job(item))
    return True


def extract_set_results(text, players=None):
  results = []
  set_blocks = re.findall(
      r"Сет\s*(\d+)\s*(?:\([^)]*\))?\s*:\s*([^\n]+)", text or "", re.I
  )
  for num, content in set_blocks:
    if re.search(r"идёт|идет|⏳|⌛", content, re.I):
      continue
    # Виртуальные сеты не закрывают реальные ставки бота
    if re.search(r"вирт|зашло бы", content, re.I) and not re.search(
        r"\d+\s*₽", content, re.I
    ):
      continue
    is_win = bool(re.search(r"✅|\+\d+", content))
    is_lose = bool(re.search(r"❌|\-\d+|минус|мимо", content, re.I))
    if is_win and not is_lose:
      results.append({
          "kind": "result",
          "result": "win",
          "players": players,
          "set": int(num),
      })
    elif is_lose and not is_win:
      results.append({
          "kind": "result",
          "result": "lose",
          "players": players,
          "set": int(num),
      })
  return results


def parse_pen_post(text):
  """Сообщение из «Пенальти Авто» → событие или None."""
  t = text or ""
  m_id = re.search(r"ID:\s*(\d+(?:-\d+)+)", t)
  if not m_id:
    return None
  sid = m_id.group(1)
  m_no = re.search(r"Матч\s*#(\d+)", t)
  if t.startswith("СТАВКА ПЕНАЛЬТИ"):
    m_teams = re.search(r"Матч\s*#\d+:\s*(.+?)\s+—\s+(.+)", t)
    m_side = re.search(r"Исход:\s*(П[12])\s*\(([^)]*)\)", t)
    m_tot = re.search(r"Исход:\s*(ТБ|ТМ)\s*(\d+(?:[.,]\d+)?)", t, re.I)
    m_kf = re.search(r"КФ:\s*(\d+[.,]\d+)", t)
    m_step = re.search(r"Шаг:\s*(\d+)", t)
    if not (m_teams and (m_side or m_tot) and m_step and m_no):
      return None
    return {
        "kind": "signal",
        "game": "penalty",
        "players": f"{m_teams.group(1).strip()} — {m_teams.group(2).strip()}",
        "market": m_side.group(1) if m_side else m_tot.group(1).upper(),
        "team": m_side.group(2).strip() if m_side else None,
        "odds": float(m_kf.group(1).replace(",", ".")) if m_kf else None,
        "step": int(m_step.group(1)),
        "set": 1,
        "line": (float(m_tot.group(2).replace(",", ".")) if m_tot and not m_side
                 else 1.0),
        "match_no": int(m_no.group(1)),
        "sig_id": sid,
    }
  if t.startswith("ИТОГ ПЕНАЛЬТИ"):
    m_res = re.search(r"Результат:\s*(WIN|LOSE|VOID)", t)
    if not m_res:
      return None
    return {
        "kind": "result",
        "game": "penalty",
        "result": m_res.group(1).lower(),
        "signal_id": f"pen:{sid}",
        "players": None,
        "set": None,
        "event_id": f"pen:{sid}:res",
    }
  return None


def _msg_time(msg):
  """Когда сообщение отправлено в канал (а не когда бот его прочитал)."""
  stamp = getattr(msg, "date", None)
  if isinstance(stamp, datetime.datetime):
    stamp = stamp.timestamp()
  return float(stamp) if stamp else time.time()


def _process_pen_message(msg, is_edit=False):
  ev = parse_pen_post(msg.text or msg.caption or "")
  if ev is None:
    return
  print(f"Пенальти: {ev['kind']} {ev.get('sig_id') or ev.get('signal_id')}"
        f" (игра {'ВКЛ' if game_on('penalty') else 'ВЫКЛ'})")
  roll_day()
  if ev["kind"] == "signal":
    if not game_on("penalty") or not state["running"]:
      return  # пенальти выключены — сигнал тихо пропускаем
    event_id = f"pen:{ev['sig_id']}"
  else:
    event_id = ev["event_id"]
  try:
    enqueue_event(event_id, ev, received_at=_msg_time(msg))
  except ValueError as e:
    send(f"⚠️ Пенальти: событие отклонено: {html.escape(str(e))}")


def _process_channel_message(msg, is_edit=False):
  text = msg.text or msg.caption or ""
  if msg.chat.id == PEN_CHANNEL:
    _process_pen_message(msg, is_edit)
    return
  if g21_channel() and msg.chat.id == g21_channel():
    _process_21_message(msg, is_edit)
    return
  with lock:
    if msg.chat.id not in state["channels"]:
      if msg.chat.id not in announced_channels:
        announced_channels.add(msg.chat.id)
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(
            "✅ Добавить канал теннисных сигналов",
            callback_data=f"setch_{msg.chat.id}",
        ))
        kb.add(types.InlineKeyboardButton(
            "🃏 Это канал 21 очко",
            callback_data=f"set21_{msg.chat.id}",
        ))
        title = html.escape(getattr(msg.chat, "title", "") or "")
        send(
            f"ℹ️ Пришёл пост из канала <b>{title}</b> ({msg.chat.id}),"
            " которого нет в списке. Добавить? Остальные каналы останутся.",
            reply_markup=kb,
        )
      return
  roll_day()

  stamp = getattr(msg, "edit_date", None) or getattr(msg, "date", time.time())
  if isinstance(stamp, datetime.datetime):
    stamp = stamp.timestamp()

  base_id = f"{msg.chat.id}:{msg.message_id}"
  parsed = parse_post(text)

  players = parsed.get("players") if parsed else None
  if players is None:
    m_players = re.search(
        r"(?:⚔|✂|🥊|⚔️)?\s*([^\n]+?\s*[—–-]\s*[^\n]+)", text or ""
    )
    if m_players:
      names = re.sub(r"\([^)]*\)", "", m_players.group(1))
      names = re.sub(r"^[^\wА-Яа-яA-Za-z]+", "", names)
      parts = re.split(r"\s*[—–-]\s*|\s+-\s+", names)
      if len(parts) == 2 and all(p.strip() for p in parts):
        players = " — ".join(p.strip() for p in parts)

  for res in extract_set_results(text, players):
    res_id = f"{base_id}:result:s{res['set']}:{res['result']}"
    res["event_id"] = res_id
    try:
      enqueue_event(res_id, res, received_at=stamp)
    except ValueError:
      pass

  if parsed is None:
    if state["dry"] and not is_edit:
      send(f"ℹ️ Пост не распознан:\n<code>{html.escape(text[:500])}</code>")
    return

  if parsed["kind"] == "signal":
    if not game_on("tennis"):
      return  # теннис выключен — сигнал тихо пропускаем (итоги выше уже учтены)
    event_id = f"{base_id}:s{parsed['set']}:step{parsed['step']}"
  else:
    event_id = base_id
    reply = getattr(msg, "reply_to_message", None)
    if reply:
      parsed["signal_id"] = f"{msg.chat.id}:{reply.message_id}"
    parsed["event_id"] = event_id

  try:
    enqueue_event(event_id, parsed, received_at=stamp)
  except ValueError as e:
    send(f"⚠️ Пост отклонён: {html.escape(str(e))}")


@bot.channel_post_handler(content_types=["text", "photo"])
def on_channel_post(msg):
  _process_channel_message(msg, is_edit=False)


@bot.edited_channel_post_handler(content_types=["text", "photo"])
def on_edited_channel_post(msg):
  _process_channel_message(msg, is_edit=True)


def job_result(page, job):
  return handle_result(job["result"])


def mark_site(reason):
  """reason=None — сайт доступен. Шлёт уведомление только при смене состояния."""
  if reason:
    if not site_health["down"]:
      site_health.update(down=True, reason=reason, since=time.time())
      send(
          "🔴 <b>DB Bet недоступен</b>\n"
          + html.escape(reason)
          + "\nСигналы будут пропускаться, пока сайт не откроется."
      )
  elif site_health["down"]:
    mins = int((time.time() - (site_health["since"] or time.time())) // 60)
    site_health.update(down=False, reason=None, since=None)
    send(f"🟢 DB Bet снова открывается (простой ~{mins} мин).")


def job_health(page, job):
  if not page:
    mark_site(f"{browser_name()} не отвечает или вкладка не открыта")
    return
  try:
    open_league(page)
    mark_site(None)
    if job.get("notify"):
      send(f"🟢 {html.escape(cur_site())} открывается, Лига Про на месте.")
  except SiteDown as e:
    if job.get("notify") and site_health["down"]:
      send("🔴 " + html.escape(str(e)))
    mark_site(str(e))
  except Exception as e:
    mark_site(f"ошибка проверки: {e}")


def health_loop():
  time.sleep(60)
  while True:
    try:
      # не мешаем ставкам: проверяем только при пустой очереди
      if jobs.empty():
        jobs.put({"fn": job_health})
    except Exception:
      traceback.print_exc()
    time.sleep(HEALTH_EVERY)


def job_balance(page, job):
  balance = get_site_balance(page) if page else None
  if balance is not None:
    with lock:
      state["bank"] = balance
      state["bank_updated_at"] = time.time()
      save_state()
  if job.get("notify"):
    send(status_text(), reply_markup=panel())


def choice_keyboard(pairs, row_width=3):
  kb = types.InlineKeyboardMarkup(row_width=row_width)
  kb.add(*[
      types.InlineKeyboardButton(label, callback_data=data)
      for label, data in pairs
  ])
  kb.add(types.InlineKeyboardButton("« Назад", callback_data="back"))
  return kb


def panel():
  kb = types.InlineKeyboardMarkup(row_width=2)
  kb.add(
      types.InlineKeyboardButton(
          "⏸ Пауза" if state["running"] else "▶️ Старт", callback_data="toggle"
      ),
      types.InlineKeyboardButton(
          "Сухой: ВКЛ" if state["dry"] else "Реальные ставки",
          callback_data="dry",
      ),
  )
  kb.add(*[
      types.InlineKeyboardButton(
          f"{name}: {'ВКЛ ✅' if game_on(g) else 'ВЫКЛ ⛔️'}", callback_data=f"game_{g}"
      )
      for g, name in GAMES.items()
  ])
  kb.add(
      types.InlineKeyboardButton(
          f"⚽ Ставка: {money(state.get('pen_base_stake', PEN_BASE_STAKE))}",
          callback_data="pen_set_stake",
      ),
      types.InlineKeyboardButton(
          f"⚽ ×{state.get('pen_multiplier', PEN_MULTIPLIER)} · шагов"
          f" {get_steps_for('penalty')}",
          callback_data="pen_set_mult",
      ),
  )
  kb.add(types.InlineKeyboardButton(
      "⚽ Повтор на тот же матч: " + ("ВКЛ ✅" if state.get("pen_allow_repeat") else "ВЫКЛ"),
      callback_data="pen_repeat",
  ))
  kb.add(
      types.InlineKeyboardButton("Банк / сегодня", callback_data="bank"),
      types.InlineKeyboardButton("Открытые ставки", callback_data="open_bets"),
  )
  kb.add(
      types.InlineKeyboardButton(
          f"Ставка: {money(get_base_stake())} ₽", callback_data="set_stake"
      ),
      types.InlineKeyboardButton(
          f"Множитель: ×{get_multiplier()}", callback_data="set_mult"
      ),
  )
  kb.add(
      types.InlineKeyboardButton(
          f"Шагов: {get_max_steps()}", callback_data="set_steps"
      ),
      types.InlineKeyboardButton(
          f"Мин.КФ: {get_min_odds()}", callback_data="set_min_odds"
      ),
  )
  kb.add(
      types.InlineKeyboardButton(
          f"Стоп/день: {limit_text()}", callback_data="set_limit"
      ),
      types.InlineKeyboardButton("Сброс статистики", callback_data="reset_stats"),
  )
  kb.add(
      types.InlineKeyboardButton("Тест браузера", callback_data="test"),
      types.InlineKeyboardButton("Сброс канала", callback_data="reset_ch"),
  )
  kb.row(
      types.InlineKeyboardButton(
          "Закрыть все висящие", callback_data="closeall"
      )
  )
  return kb


def status_text():
  with lock:
    snapshot = copy.deepcopy(state)
  t = snapshot["today_dry" if snapshot["dry"] else "today_real"]
  bank = snapshot["virtual_bank"] if snapshot["dry"] else snapshot["bank"]
  bank_text = money(bank) if bank is not None else "не синхронизирован с сайтом"
  if not snapshot["dry"] and bank is not None and snapshot["bank_updated_at"]:
    bank_text += (
        " (снимок "
        + datetime.datetime.fromtimestamp(snapshot["bank_updated_at"]).strftime(
            "%d.%m %H:%M:%S"
        )
        + ")"
    )

  st_running = "▶️ работает" if snapshot["running"] else "⏸ пауза"
  st_mode = " сухой" if snapshot["dry"] else " РЕАЛЬНЫЙ"
  st_stake = money(snapshot.get("base_stake", BASE_STAKE))
  st_mult = str(snapshot.get("multiplier", MULTIPLIER))
  st_steps = str(snapshot.get("max_steps", MAX_STEPS))
  st_limit = limit_text()
  st_min_odds = str(snapshot.get("min_odds", MIN_ODDS))
  st_bets = str(t["bets"])
  st_win = str(t["win"])
  st_lose = str(t["lose"])
  st_prof = money(t["profit"])
  st_open = str(len(snapshot["open_bets"]))
  st_rev = str(sum(x["status"] == "review" for x in snapshot["inbox"]))
  st_fail = str(sum(x["status"] == "failed" for x in snapshot["inbox"]))
  st_chan = (
      ", ".join(str(c) for c in snapshot.get("channels", []))
      or "не выбран (жди пост и нажми «Добавить»)"
  ) + f" · ⚽ {PEN_CHANNEL}"

  return (
      " <b>Автоставка DB Bet (теннис + пенальти + 21 очко)</b>"
      + f" · версия {BOT_VERSION}\n"
      + "Статус: "
      + st_running
      + "\n"
      + "Режим: "
      + st_mode
      + "\n"
      + "Ставка: "
      + st_stake
      + " ×"
      + st_mult
      + ", шагов "
      + st_steps
      + "\n"
      + "Лестница: "
      + html.escape(ladder_text())
      + "\n"
      + "⚽ Пенальти: "
      + html.escape(pen_ladder_text())
      + "\n"
      + "🃏 21 очко (канал "
      + str(g21_channel() or "не задан")
      + "):\n  Голд: "
      + html.escape(g21_ladder_text("ГОЛД"))
      + "\n  Раздача: "
      + html.escape(g21_ladder_text("РАЗДАЧА"))
      + "\n"
      + "Игры: "
      + ", ".join(
          f"{name} {'✅' if game_on(g) else '⛔️'}" for g, name in GAMES.items()
      )
      + "\n"
      + "Браузер: "
      + browser_name()
      + (" · прокси" if browser_mode() == "own" and BROWSER_PROXY else "")
      + "\n"
      + "Мин. КФ: "
      + st_min_odds
      + " | Стоп за день: "
      + st_limit
      + "\n"
      + "Банк: "
      + bank_text
      + "\n"
      + "Сегодня: "
      + st_bets
      + " ставок, "
      + st_win
      + " ✅ / "
      + st_lose
      + " ❌, "
      + st_prof
      + "\n"
      + "Открытых ставок: "
      + st_open
      + "\n"
      + "Результатов для проверки: "
      + st_rev
      + "\n"
      + "Не поставленных сигналов: "
      + st_fail
      + "\n"
      + "Каналы: "
      + st_chan
      + "\n"
      + "Команды: /closeall, /pending, /confirm, /result, /discard, /retry, /stake, /mirror"
  )


@bot.message_handler(commands=["start", "menu"])
def cmd_start(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  roll_day()
  bot.send_message(ADMIN_ID, status_text(), reply_markup=panel())


@bot.message_handler(commands=["stake"])
def cmd_stake(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").replace(",", ".").split()
  try:
    if len(parts) != 2:
      raise ValueError("Используй /stake 75")
    val = float(parts[1])
    if not math.isfinite(val) or val < 10 or val > MAX_SITE_STAKE:
      raise ValueError(f"сумма от 10 до {MAX_SITE_STAKE}")
    with lock:
      previous = copy.deepcopy(state)
      state["base_stake"] = val
      state["generation"] += 1
      try:
        save_state()
      except Exception:
        state.clear()
        state.update(previous)
        raise
    send(f"Первая ставка: {money(val)} ₽\nЛестница: {html.escape(ladder_text())}")
  except ValueError as e:
    send(html.escape(str(e)))


@bot.message_handler(commands=["limit"])
def cmd_limit(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").replace(",", ".").split()
  try:
    if len(parts) != 2:
      raise ValueError
    val = float(parts[1])
    if not math.isfinite(val) or val < 0 or 0 < val < 100:
      raise ValueError
  except ValueError:
    send(f"Сейчас: {limit_text()}\nСвоя сумма: /limit 7500 · без лимита: /limit 0")
    return
  with lock:
    state["daily_loss_limit"] = val
    save_state()
  send(f"Дневной стоп-лосс: {limit_text()}")


@bot.message_handler(commands=["browser"])
def cmd_browser(msg):
  """/browser own — свой Chromium, /browser opera — Opera по порту отладки."""
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").split()
  if len(parts) != 2 or parts[1].lower() not in ("own", "opera"):
    send(f"Сейчас: {browser_name()}\n/browser own — свой Chromium (бот запускает сам)"
         "\n/browser opera — Opera по порту отладки")
    return
  with lock:
    state["browser_mode"] = parts[1].lower()
    save_state()
  send(f"🌐 Браузер: {browser_name()}. Переключусь на следующем задании —"
       " нажми «Тест браузера», чтобы проверить сразу.")


@bot.message_handler(commands=["vbank"])
def cmd_vbank(msg):
  """Виртуальный банк сухого режима: /vbank 20000."""
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").replace(",", ".").split()
  try:
    if len(parts) != 2:
      raise ValueError
    val = float(parts[1])
    if not math.isfinite(val) or val <= 0:
      raise ValueError
  except ValueError:
    send(f"Виртуальный банк: {money(state['virtual_bank'])}\nЗадать: /vbank 20000")
    return
  with lock:
    state["virtual_bank"] = round(val, 2)
    save_state()
  send(f"🧪 Виртуальный банк сухого режима: {money(state['virtual_bank'])}")


@bot.message_handler(commands=["mirror"])
def cmd_mirror(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").split()
  if len(parts) != 2:
    send(
        f"Текущее зеркало: <b>{html.escape(cur_site())}</b>\n"
        "Сменить: /mirror db-bet-12345.top (можно вставить ссылку целиком)"
    )
    return
  raw = parts[1].strip()
  host = urlparse(raw if "://" in raw else "https://" + raw).hostname or ""
  if not re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", host) or not (
      "db-bet" in host or "dbbet" in host
  ):
    send("Это не похоже на адрес DB Bet. Пример: /mirror db-bet-12345.top")
    return
  with lock:
    state["site"] = host
    save_state()
  send(f"✅ Зеркало установлено: <b>{html.escape(host)}</b>\nПроверяю…")
  jobs.put({"fn": job_health, "notify": True})


@bot.message_handler(
    func=lambda m: bool(
        m.text
        and not m.text.startswith("/")
        and re.search(r"db-?bet[\w-]*\.[a-z]{2,}", m.text, re.I)
    ),
    content_types=["text"],
)
def msg_mirror(msg):
  """Адрес зеркала простым сообщением (без /mirror) — тоже принимаем."""
  if msg.from_user.id != ADMIN_ID:
    return
  m = re.search(r"(?:https?://)?(db-?bet[\w-]*\.[a-z]{2,})", msg.text, re.I)
  msg.text = "/mirror " + m.group(1).lower()
  cmd_mirror(msg)


@bot.message_handler(commands=["retry"])
def cmd_retry(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  with lock:
    if not state["running"]:
      send("Бот на паузе. Сначала нажми Старт.")
      return
    previous = copy.deepcopy(state)
    failed = [x for x in state["inbox"] if x["status"] == "failed"]
    for item in failed:
      item["status"] = "pending"
      item["generation"] = state["generation"]
      item["dry"] = state["dry"]
      item["received_at"] = time.time()
    try:
      save_state()
    except Exception:
      state.clear()
      state.update(previous)
      send("Не удалось сохранить состояние, повтор отменён.")
      return
    queued = [event_job(item) for item in failed]
  for job in queued:
    jobs.put(job)
  send(
      f"В очереди повторно: {len(queued)}."
      if queued
      else "Нет неудавшихся сигналов."
  )


def close_all_hanging():
  with lock:
    previous = copy.deepcopy(state)
    bets = list(state["open_bets"])
    for bet in bets:
      bet["status"] = "cancelled"
      bet["result"] = "cancelled"
      state["closed_bets"].append(bet)
    state["open_bets"] = []
    inbox_n = len(state["inbox"])
    for item in state["inbox"]:
      if isinstance(item.get("id"), str):
        state["processed_posts"].append(item["id"])
    state["processed_posts"] = state["processed_posts"][-2000:]
    state["inbox"] = []
    state["generation"] += 1
    state["running"] = True
    try:
      save_state()
    except Exception:
      state.clear()
      state.update(previous)
      raise
    return len(bets), inbox_n, True


def closeall_text(closed_n, inbox_n, resumed):
  return (
      f"Закрыто ставок в боте: {closed_n} "
      "(принятые, неизвестные и зависшие).\n"
      f"Убрано из проверки: {inbox_n}.\n"
      "Баланс на сайте и банк в боте не менялись.\n"
      "Бот работает и принимает новые сигналы."
  )


@bot.message_handler(commands=["closeall"])
def cmd_closeall(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  try:
    closed_n, inbox_n, resumed = close_all_hanging()
  except Exception as e:
    send("Не удалось закрыть: " + html.escape(str(e)))
    return
  send(closeall_text(closed_n, inbox_n, resumed), reply_markup=panel())


@bot.message_handler(commands=["channel"])
def cmd_channel(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  try:
    parts = (msg.text or "").split()
    if len(parts) == 1:
      send(channels_text())
      return
    if len(parts) != 3 and (len(parts) != 2 or int(parts[1]) >= 0):
      raise ValueError(
          "Добавить: /channel -100… · убрать: /channel del -100… · список: /channel"
      )
    if parts[1].lower() in ("del", "remove", "удалить"):
      ch = int(parts[2])
      with lock:
        if ch in state["channels"]:
          state["channels"].remove(ch)
        state["channel_id"] = state["channels"][0] if state["channels"] else None
        save_state()
      send("Канал убран.\n" + channels_text())
      return
    add_channel(int(parts[1]))
  except ValueError as e:
    send(html.escape(str(e)))


def channels_text():
  chans = state["channels"]
  return (
      "🏓 Каналы теннисных сигналов: "
      + (", ".join(str(c) for c in chans) if chans else "нет")
      + f"\n⚽ Пенальти Авто: {PEN_CHANNEL} (подключён всегда)"
      + "\nДобавить: /channel -100… · убрать: /channel del -100…"
  )


def add_channel(ch):
  if ch == PEN_CHANNEL:
    send("⚽ «Пенальти Авто» подключён автоматически, добавлять не нужно.\n"
         + channels_text())
    return
  with lock:
    if ch not in state["channels"]:
      state["channels"].append(ch)
    if state["channel_id"] is None:
      state["channel_id"] = ch
    save_state()
  send("✅ Канал добавлен, бот работает.\n" + channels_text(), reply_markup=panel())


def signal_reference(value):
  if re.fullmatch(r"\d+", value):
    if state["channel_id"] is None:
      raise ValueError("канал ещё не выбран")
    return f"{state['channel_id']}:{value}"
  if re.fullmatch(r"\d+(?:-\d+)+", value):
    return f"pen:{value}"  # ID пенальти, например 123456-260-2
  if re.fullmatch(r"pen:\d+(?:-\d+)+", value):
    return value
  if not re.fullmatch(r"(?:-?\d+|legacy):\d+(?::\w+)*", value):
    raise ValueError("ID должен быть номером поста или полным ID из /pending")
  return value


@bot.message_handler(commands=["pending", "confirm", "result", "discard"])
def cmd_review(msg):
  if msg.from_user.id != ADMIN_ID:
    return
  parts = (msg.text or "").split()
  command = parts[0].split("@")[0]
  try:
    if command == "/pending":
      with lock:
        rows = [
            (
                f"Ставка {b.get('post_id', '?')}: {b.get('status', 'accepted')},"
                f" {b['players']}, партия {b['set']}"
            )
            for b in state["open_bets"]
        ]
        rows += [
            f"Пост {item['id']}: требует сопоставления"
            for item in state["inbox"]
            if item["status"] == "review"
        ]
        rows += [
            f"Сигнал {item['id']}: не поставлен, ждёт /retry"
            for item in state["inbox"]
            if item["status"] == "failed"
        ]
      text = "\n".join(rows) if rows else "Неразобранных событий нет."
      for offset in range(0, len(text), 3000):
        send(text[offset : offset + 3000], parse_mode=None)
      return
    if command == "/result":
      if len(parts) != 3 or parts[2] not in ("win", "lose"):
        raise ValueError("Используй /result ID win или /result ID lose")
      ref = signal_reference(parts[1])
      event_id = f"admin:{msg.chat.id}:{msg.message_id}"
      enqueue_event(
          event_id,
          {
              "kind": "result",
              "result": parts[2],
              "signal_id": ref,
              "players": None,
              "set": None,
              "event_id": event_id,
          },
      )
      return
    if command == "/discard":
      if len(parts) == 2 and parts[1].lower() == "all":
        with lock:
          review_ids = [
              x["id"]
              for x in state["inbox"]
              if x["status"] in ("review", "failed")
          ]
        for rid in review_ids:
          finish_event(rid)
        send(f"Удалено из проверки: {len(review_ids)} событий.")
        return
      if len(parts) != 2:
        raise ValueError(
            "Используй /discard полный_ID или /discard all"
        )
      with lock:
        if not any(
            x["id"] == parts[1] and x["status"] in ("review", "failed")
            for x in state["inbox"]
        ):
          raise ValueError("не найдено события для проверки")
        finish_event(parts[1])
      send("Событие исключено из списка проверки.")
      return
    if len(parts) < 3 or parts[2] not in ("placed", "cancel"):
      raise ValueError(
          "После проверки истории: /confirm ID placed КФ или /confirm ID cancel"
      )
    ref = signal_reference(parts[1])
    odds = None
    if parts[2] == "placed":
      if len(parts) != 4:
        raise ValueError(
            "Укажи принятый сайтом коэффициент: /confirm ID placed КФ"
        )
      odds = float(parts[3].replace(",", "."))
      if not math.isfinite(odds) or odds <= 1:
        raise ValueError("неверный коэффициент")
    elif len(parts) != 3:
      raise ValueError("Используй /confirm ID cancel")
    with lock:
      b = next(
          (
              x
              for x in state["open_bets"]
              if _post_id_matches(x.get("post_id"), ref)
              and x.get("status") in ("unknown", "placing")
          ),
          None,
      )
      if b is None:
        raise ValueError("нет неизвестной ставки с этим ID")
      previous = copy.deepcopy(state)
      if odds is not None:
        b["status"] = "accepted"
        b["odds"] = odds
        state["today_real"]["bets"] += 1
      else:
        state["open_bets"].remove(b)
        b["status"] = "cancelled"
        state["closed_bets"].append(b)
      state["bank"] = None
      state["bank_updated_at"] = None
      try:
        save_state()
      except Exception:
        state.clear()
        state.update(previous)
        raise
    jobs.put({"fn": job_balance})
    send(
        "Решение сохранено. Бот продолжает работу. Результат принятой ставки:"
        " /result ID win или lose."
    )
  except (ValueError, OverflowError) as e:
    send(html.escape(str(e)))


@bot.callback_query_handler(func=lambda c: True)
def on_cb(c):
  if c.from_user.id != ADMIN_ID:
    return

  try:
    bot.answer_callback_query(c.id)
  except Exception:
    pass

  d = c.data
  if d.startswith("set21_"):
    try:
      ch = int(d[6:])
    except ValueError:
      return
    with lock:
      state["g21_channel"] = ch
      if ch in state["channels"]:
        state["channels"].remove(ch)
        state["channel_id"] = state["channels"][0] if state["channels"] else None
      save_state()
    send(f"🃏 Канал 21 очко: <code>{ch}</code>. Сигналы AUTO21 из него идут в автоставку.")
    return
  if d.startswith("setch_"):
    try:
      ch = int(d[6:])
    except ValueError:
      return
    add_channel(ch)
    return
  if d.startswith("game_") and d[5:] in GAMES:
    g = d[5:]
    with lock:
      state.setdefault("games", {})[g] = not game_on(g)
      dropped = 0 if game_on(g) else drop_pending(g)
    send(
        f"{GAMES[g]}: {'включён' if game_on(g) else 'выключен'}."
        + ("" if game_on(g) else " Новые сигналы пропускаются, открытые ставки"
           " получат результат.")
        + (f" Убрано из очереди сигналов: {dropped}." if dropped else "")
    )
  elif d == "pen_repeat":
    with lock:
      state["pen_allow_repeat"] = not state.get("pen_allow_repeat")
    send(
        "⚽ Повтор на тот же матч: ВКЛ — если две цепочки прогнозов выпали на один"
        " матч, бот поставит обе ставки."
        if state["pen_allow_repeat"] else
        "⚽ Повтор на тот же матч: ВЫКЛ — на один матч одна ставка, второй сигнал"
        " пропускается."
    )
  elif d == "pen_set_stake":
    kb = choice_keyboard([
        (f"{val} ₽", f"penstake_{val}") for val in (25, 50, 100, 200, 300, 500)
    ])
    bot.send_message(ADMIN_ID, "⚽ Первая ставка пенальти:", reply_markup=kb)
    return
  elif d.startswith("penstake_"):
    with lock:
      state["pen_base_stake"] = float(d.split("_")[1])
      state["generation"] += 1
    send(f"⚽ Лестница пенальти: {html.escape(pen_ladder_text())}")
  elif d == "pen_set_mult":
    kb = choice_keyboard(
        [(f"×{v}", f"penmult_{v}") for v in (2.0, 2.2, 2.5, 3.0)]
        + [(f"{v} шаг.", f"pensteps_{v}") for v in (1, 2, 3, 4)]
    )
    bot.send_message(ADMIN_ID, "⚽ Множитель и шаги догона пенальти:", reply_markup=kb)
    return
  elif d.startswith("penmult_"):
    with lock:
      state["pen_multiplier"] = float(d.split("_")[1])
      state["generation"] += 1
    send(f"⚽ Лестница пенальти: {html.escape(pen_ladder_text())}")
  elif d.startswith("pensteps_"):
    with lock:
      state["pen_max_steps"] = int(d.split("_")[1])
      state["generation"] += 1
    send(f"⚽ Лестница пенальти: {html.escape(pen_ladder_text())}")
  elif d == "toggle":
    with lock:
      state["running"] = not state["running"]
      state["generation"] += 1
  elif d == "closeall":
    try:
      closed_n, inbox_n, resumed = close_all_hanging()
    except Exception as e:
      send("Не удалось закрыть: " + html.escape(str(e)))
      return
    send(closeall_text(closed_n, inbox_n, resumed), reply_markup=panel())
    return
  elif d == "dry":
    if state["dry"]:
      kb = types.InlineKeyboardMarkup()
      kb.add(
          types.InlineKeyboardButton(
              "✅ Да, ставить реальные деньги", callback_data="real_yes"
          ),
          types.InlineKeyboardButton("Отмена", callback_data="real_no"),
      )
      bot.send_message(
          ADMIN_ID,
          f"⚠️ Включить РЕАЛЬНЫЕ ставки?\nПервая ставка {money(get_base_stake())},"
          f" ×{get_multiplier()}, до {get_max_steps()} шагов, стоп за день"
          f" {money(get_daily_loss_limit())}.",
          reply_markup=kb,
      )
      return
    with lock:
      state["dry"] = True
      state["generation"] += 1
  elif d in ("real_yes", "real_no"):
    if d == "real_yes":
      with lock:
        state["dry"] = False
        state["generation"] += 1
      save_state()
      send(" Реальный режим включён. Проверь лестницу сумм перед первым сигналом.")
    else:
      send("Переключение отменено.")
    send(status_text(), reply_markup=panel())
    return
  elif d == "test":
    jobs.put({"fn": job_test})
    send("Проверяю браузер…")
  elif d == "reset_ch":
    with lock:
      if state["open_bets"] or state["inbox"]:
        send("Сначала разбери открытые ставки и события через /pending")
        return
      state["channel_id"] = None
      state["channels"] = []
      state["generation"] += 1
    send("Список теннисных каналов очищен. ⚽ Пенальти Авто остаётся подключён.")
  elif d == "bank":
    if not state["dry"]:
      jobs.put({"fn": job_balance, "notify": True})
      send("Обновляю баланс сайта…")
      return

  elif d == "set_stake":
    kb = choice_keyboard([
        (f"{val} ₽", f"stake_{val}")
        for val in (25, 50, 100, 150, 200, 300)
    ])
    bot.send_message(
        ADMIN_ID,
        "Выбери сумму первой ставки.\nСвоя сумма: /stake 75",
        reply_markup=kb,
    )
    return

  elif d.startswith("stake_"):
    try:
      val = float(d.split("_")[1])
      if val <= 0:
        raise ValueError
      with lock:
        state["base_stake"] = val
        state["generation"] += 1
      send(f"Первая ставка установлена: {money(val)} ₽")
    except Exception:
      send("Неверная сумма")
      return

  elif d == "set_mult":
    kb = choice_keyboard([
        (f"×{val}", f"mult_{val}") for val in (2.0, 2.5, 3.0)
    ])
    bot.send_message(ADMIN_ID, "Выбери множитель догона:", reply_markup=kb)
    return

  elif d.startswith("mult_"):
    try:
      val = float(d.split("_")[1])
      if val < 1.1:
        raise ValueError
      with lock:
        state["multiplier"] = val
        state["generation"] += 1
      send(f"Множитель догона установлен: ×{val}")
    except Exception:
      send("Неверный множитель")
      return

  elif d == "set_steps":
    kb = choice_keyboard(
        [(str(val), f"steps_{val}") for val in range(1, 6)],
        row_width=5,
    )
    bot.send_message(ADMIN_ID, "Максимум шагов догона (1–5):", reply_markup=kb)
    return

  elif d.startswith("steps_"):
    try:
      val = int(d.split("_")[1])
      if not 1 <= val <= 5:
        raise ValueError
      with lock:
        state["max_steps"] = val
        state["generation"] += 1
      send(f"Максимум шагов догона: {val}")
    except Exception:
      send("Неверное значение шагов")
      return

  elif d == "set_min_odds":
    kb = choice_keyboard([
        (str(val), f"minodds_{val}")
        for val in (1.15, 1.20, 1.25, 1.30, 1.40, 1.50)
    ])
    bot.send_message(ADMIN_ID, "Минимальный коэффициент:", reply_markup=kb)
    return

  elif d.startswith("minodds_"):
    try:
      val = float(d.split("_")[1])
      if val < 1.01:
        raise ValueError
      with lock:
        state["min_odds"] = val
        state["generation"] += 1
      send(f"Минимальный КФ установлен: {val}")
    except Exception:
      send("Неверный коэффициент")
      return

  elif d == "set_limit":
    kb = choice_keyboard([
        ("без лимита" if val == 0 else f"{val} ₽", f"limit_{val}")
        for val in (2000, 5000, 10000, 20000, 50000, 0)
    ])
    bot.send_message(ADMIN_ID, "Дневной стоп-лосс (своя сумма: /limit 7500, выключить: /limit 0):", reply_markup=kb)
    return

  elif d.startswith("limit_"):
    try:
      val = float(d.split("_")[1])
      if 0 < val < 100:
        raise ValueError
      with lock:
        state["daily_loss_limit"] = val
        state["generation"] += 1
      send(f"Дневной стоп-лосс: {limit_text()}")
    except Exception:
      send("Неверное значение лимита")
      return

  elif d == "open_bets":
    with lock:
      bets = list(state["open_bets"])
    if not bets:
      send("Открытых ставок нет.")
    else:
      lines = []
      for b in bets:
        mode = "🧪" if b.get("dry") else "💰"
        lines.append(
            f"{mode} {b.get('post_id', '?')}\n"
            f"{b.get('players', '?')} | {describe(b)} @ {b.get('odds')}\n"
            f"Сумма: {money(b.get('stake', 0))} | Статус: {b.get('status', '?')}"
        )
      text = "\n\n".join(lines)
      for offset in range(0, len(text), 3500):
        send(text[offset:offset + 3500], parse_mode=None)
    return

  elif d == "reset_stats":
    kb = types.InlineKeyboardMarkup()
    kb.add(
        types.InlineKeyboardButton("✅ Да, сбросить", callback_data="reset_stats_yes"),
        types.InlineKeyboardButton("Отмена", callback_data="back"),
    )
    bot.send_message(
        ADMIN_ID,
        "Сбросить статистику за сегодня (ставки/профит)?\n"
        "Открытые ставки и история не трогаются.",
        reply_markup=kb,
    )
    return

  elif d == "reset_stats_yes":
    with lock:
      empty = {"bets": 0, "win": 0, "lose": 0, "profit": 0.0}
      state["today_dry"] = dict(empty)
      state["today_real"] = dict(empty)
      save_state()
    send("Статистика за сегодня сброшена.")
    send(status_text(), reply_markup=panel())
    return

  elif d == "back":
    send(status_text(), reply_markup=panel())
    return

  save_state()
  try:
    bot.edit_message_text(
        status_text(), c.message.chat.id, c.message.message_id, reply_markup=panel()
    )
  except Exception:
    pass


def send_daily_reports():
  with lock:
    pending = list(state["pending_reports"])
  for report in pending:
    if not send(report["text"]):
      break
    with lock:
      state["pending_reports"].remove(report)
      state["report_sent_for"] = report["day"]
      save_state()


def compact_status():
  with lock:
    snap = copy.deepcopy(state)
  t = snap["today_dry" if snap["dry"] else "today_real"]
  bank = snap["virtual_bank"] if snap["dry"] else snap["bank"]
  bank_txt = money(bank) if bank is not None else "—"
  mode = "🧪 сухой" if snap["dry"] else "💰 реальный"
  open_n = len(snap["open_bets"])
  lines = [
      f"⏱ {mode}",
      f"Банк: {bank_txt}",
      f"Сегодня: {t['bets']} ставок, {t['win']}✅ / {t['lose']}❌, {money(t['profit'])}",
      f"Открытых: {open_n}",
  ]
  if open_n:
    for b in snap["open_bets"][:8]:
      lines.append(
          "· "
          + html.escape(str(b.get("players", "?"))[:40])
          + " | "
          + html.escape(describe(b))
          + f" | {money(b.get('stake', 0))}"
      )
    if open_n > 8:
      lines.append(f"· …и ещё {open_n - 8}")
  return "\n".join(lines)


def daily_report_loop():
  last_status_at = 0
  STATUS_EVERY = 10 * 60
  while True:
    try:
      roll_day()
      send_daily_reports()
      now = time.time()
      if now - last_status_at >= STATUS_EVERY:
        send(compact_status())
        last_status_at = now
    except Exception:
      traceback.print_exc()
    time.sleep(30)


if __name__ == "__main__":
  roll_day()
  # Сигналы, не поставленные до перезапуска, не берём — бот ждёт новые.
  # Результаты оставляем: по ним закрываются открытые ставки.
  with lock:
    old_signals = [
        x for x in state["inbox"] if x["status"] == "pending" and x["kind"] == "signal"
    ]
    for item in old_signals:
      state["inbox"].remove(item)
      state["processed_posts"].append(item["id"])
    state["processed_posts"] = state["processed_posts"][-2000:]
  save_state()
  for item in state["inbox"]:
    if item["status"] == "pending":
      jobs.put(event_job(item))
  threading.Thread(target=browser_worker, daemon=True).start()
  threading.Thread(target=daily_report_loop, daemon=True).start()
  threading.Thread(target=health_loop, daemon=True).start()
  threading.Thread(target=watchdog_loop, daemon=True).start()
  try:
    hello = bot.send_message(
        ADMIN_ID,
        f" Автоставка запущена, версия {BOT_VERSION} (автопауза отключена)"
        + (f"\n⏭ Старых сигналов из очереди убрано: {len(old_signals)}" if old_signals else "")
        + "\nСигналы, отправленные до запуска, пропускаются — жду новые."
        + "\n\n" + status_text(),
        reply_markup=panel(),
    )
    # время сервера Telegram: не зависит от часов компьютера
    START_TS = float(hello.date)
  except Exception as e:
    print("send error:", e)
    START_TS = time.time()
  print("Бот успешно запущен и ожидает постов...")

  while True:
    try:
      bot.infinity_polling(
          allowed_updates=[
              "message",
              "channel_post",
              "edited_channel_post",
              "callback_query",
          ],
          timeout=60,
          long_polling_timeout=60,
      )
    except Exception as e:
      print(f"⚠️ Ошибка сети/полинга: {e}. Переподключение через 5 секунд...")
      time.sleep(5)
