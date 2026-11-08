import os
from dataclasses import dataclass, field


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


def _chats(raw: str) -> set[int | str]:
    """Список чатов через запятую: числовые id или @username (хранится без @, в нижнем регистре)."""
    items = (x for x in raw.replace(" ", "").split(",") if x)
    return {int(x) if x.lstrip("-").isdigit() else x.lstrip("@").lower() for x in items}


@dataclass(frozen=True)
class Config:
    token: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    db_path: str = os.getenv("DB_PATH", "suitbot.sqlite3")
    # Каналы, из которых принимаются результаты: id или @username. Пусто — любой
    # источник с постами формата "#N123. ...". Лучше указать канал статистики.
    result_sources: set[int | str] = field(default_factory=lambda: _chats(os.getenv("RESULT_SOURCES", "")))
    admins: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMINS", "")))

    chips_per_star: int = int(os.getenv("CHIPS_PER_STAR", "100"))
    # Пакеты для покупки, в звёздах (минимум у Telegram — 1 звезда).
    star_packs: tuple[int, ...] = tuple(int(x) for x in os.getenv("STAR_PACKS", "1,5,10,50").split(",") if x.strip())
    # Контакт для вопросов по оплате (команда /paysupport, её требует Telegram).
    support_contact: str = os.getenv("SUPPORT_CONTACT", "")
    start_balance: int = int(os.getenv("START_BALANCE", "500"))
    # Бонус: сколько фишек и как часто (в днях) можно забирать.
    bonus_amount: int = int(os.getenv("BONUS_AMOUNT", "300"))
    bonus_period_days: int = int(os.getenv("BONUS_PERIOD_DAYS", "7"))
    min_bet: int = int(os.getenv("MIN_BET", "10"))
    max_bet: int = int(os.getenv("MAX_BET", "10000"))

    # Насколько игр вперёд можно ставить и после какого номера счётчик игр
    # начинается заново (проверьте по своему каналу).
    max_games_ahead: int = int(os.getenv("MAX_GAMES_AHEAD", "20"))
    game_number_wrap: int = int(os.getenv("GAME_NUMBER_WRAP", "1440"))
    # Ставки, которые так и не дождались результата, возвращаются.
    bet_ttl_hours: int = int(os.getenv("BET_TTL_HOURS", "6"))
    # Страховка на случай, если канал публикует пост игры только после её конца:
    # ставки на следующую игру закрываются через столько секунд после поста
    # предыдущей. 0 — закрывать только по посту самой игры.
    bet_window_seconds: int = int(os.getenv("BET_WINDOW_SECONDS", "0"))
    # Режим закрытия: "auto" — по среднему интервалу между играми минус запас до старта следующей,
    # число — секунд после поста предыдущей игры, 0 — только по посту самой игры. Меняется в /admin.
    bet_window_default: str = os.getenv("BET_WINDOW", "auto")
    bet_reserve_seconds: int = int(os.getenv("BET_RESERVE_SECONDS", "20"))
    # Сброс балансов из /admin: сколько фишек получает каждый игрок.
    reset_amount: int = int(os.getenv("RESET_AMOUNT", "5000"))

    # Подписка на канал, без которой нельзя ставить, брать бонус и вступать в турнир.
    # Бот должен быть админом этого канала, иначе Telegram не покажет ему подписчиков.
    required_channel: str = os.getenv("REQUIRED_CHANNEL", "")  # @username или -100…
    required_channel_url: str = os.getenv("REQUIRED_CHANNEL_URL", "")

    # Коэффициенты выплат (ставка × коэффициент при выигрыше).
    payout_suit: float = float(os.getenv("PAYOUT_SUIT", "1.9"))
    payout_player: float = float(os.getenv("PAYOUT_PLAYER", "1.95"))
    payout_banker: float = float(os.getenv("PAYOUT_BANKER", "1.95"))
    payout_tie: float = float(os.getenv("PAYOUT_TIE", "8"))
    payout_cards: float = float(os.getenv("PAYOUT_CARDS", "1.9"))  # ставка на 2 или 3 карты

    # Карточки игр с кнопками: как часто публиковать (каждую N-ю игру, 0 — выключено;
    # меняется из /admin). Карточка на игру N+1 выходит сразу, как появился пост игры N.
    card_every: int = int(os.getenv("CARD_EVERY", "1"))

    # Турнир: всем поровну бесплатных фишек, призы раздаёт владелец.
    # Запускается из /admin; TOURNAMENT_AUTO=1 — ещё и автоматически каждый понедельник.
    tournament_enabled: bool = os.getenv("TOURNAMENT_ENABLED", "1") == "1"
    tournament_auto: bool = os.getenv("TOURNAMENT_AUTO", "0") == "1"
    tournament_tz: str = os.getenv("TOURNAMENT_TZ", "Europe/Moscow")
    tournament_start_chips: int = int(os.getenv("TOURNAMENT_START_CHIPS", "1000"))
    tournament_max_bet: int = int(os.getenv("TOURNAMENT_MAX_BET", "500"))
    # Чтобы попасть в призы: сделать минимум ставок и быть в боте не меньше N дней
    # к концу турнира (защита от свежих мультиаккаунтов).
    tournament_min_bets: int = int(os.getenv("TOURNAMENT_MIN_BETS", "20"))
    tournament_min_days_in_bot: int = int(os.getenv("TOURNAMENT_MIN_DAYS_IN_BOT", "0"))
    tournament_prizes: tuple[str, ...] = tuple(
        p.strip() for p in os.getenv(
            "TOURNAMENT_PRIZES", "200 ⭐|100 ⭐|50 ⭐"
        ).split("|") if p.strip()
    )
    # Куда объявлять начало и итоги, кроме чата, выбранного командой /setchat.
    tournament_chats: set[int] = field(default_factory=lambda: _ids(os.getenv("TOURNAMENT_CHATS", "")))

    # Какую игру ведёт бот: baccarat (масти по постам статистики баккары)
    # или penalty (П1/П2 и тотал по постам FIFA Penalty).
    game: str = os.getenv("GAME", "baccarat")
    # Пенальти: когда закрывать ставки на серию N, если канал ещё не обновил её счёт.
    # Между сериями пауза ~4 минуты, поэтому по умолчанию — через PENALTY_START_DELAY
    # секунд после конца серии N-1 (с запасом до старта). PENALTY_CLOSE_ON_PREV_FINISH=1 —
    # закрывать сразу после конца предыдущей серии.
    penalty_close_on_prev_finish: bool = os.getenv("PENALTY_CLOSE_ON_PREV_FINISH", "0") == "1"
    penalty_start_delay: int = int(os.getenv("PENALTY_START_DELAY", "180"))

    # Язык для игроков по умолчанию (ru | uz); меняется в /admin.
    lang: str = os.getenv("BOT_LANG", "ru")

    # Дуэли: включаются и выключаются в /admin, здесь — значение по умолчанию.
    duels_enabled: bool = os.getenv("DUELS_ENABLED", "1") == "1"
    # Сколько игр может длиться дуэль (выбирает вызывающий) и длина по умолчанию.
    duel_game_options: tuple[int, ...] = tuple(int(x) for x in os.getenv("DUEL_GAME_OPTIONS", "1,3,5,10").split(","))
    duel_games: int = int(os.getenv("DUEL_GAMES", "10"))
    duel_min_stake: int = int(os.getenv("DUEL_MIN_STAKE", "50"))
    duel_max_stake: int = int(os.getenv("DUEL_MAX_STAKE", "10000"))
    duel_accept_minutes: int = int(os.getenv("DUEL_ACCEPT_MINUTES", "10"))
    # Если канал пропустил номера игр, дуэль не зависнет: через столько часов
    # она завершится с текущим счётом.
    duel_max_hours: int = int(os.getenv("DUEL_MAX_HOURS", "3"))

    # Крутилка 🎰 раз в сутки: выигрыш за 777, за три одинаковых, за две, за промах.
    spin_prizes: tuple[int, ...] = tuple(int(x) for x in os.getenv("SPIN_PRIZES", "1000,300,50,10").split(","))

    # «Актив недели»: очки за сообщения в чате (не чаще раза в минуту, от 3 слов),
    # ответы другим, ставки и дуэли. В конце недели — топ и список для призов.
    activity_enabled: bool = os.getenv("ACTIVITY_ENABLED", "1") == "1"
    activity_prizes: tuple[str, ...] = tuple(
        p.strip() for p in os.getenv("ACTIVITY_PRIZES", "100 ⭐|50 ⭐|25 ⭐").split("|") if p.strip()
    )
    activity_min_points: int = int(os.getenv("ACTIVITY_MIN_POINTS", "20"))
    activity_min_words: int = int(os.getenv("ACTIVITY_MIN_WORDS", "3"))
    activity_msg_cooldown: int = int(os.getenv("ACTIVITY_MSG_COOLDOWN", "60"))

    # Внезапные раздачи: несколько раз в день в случайное время в эти часы.
    drops_enabled: bool = os.getenv("DROPS_ENABLED", "1") == "1"
    drops_per_day: int = int(os.getenv("DROPS_PER_DAY", "4"))
    drop_hours: tuple[int, int] = tuple(int(x) for x in os.getenv("DROP_HOURS", "10-23").split("-"))  # type: ignore[assignment]
    drop_amount: int = int(os.getenv("DROP_AMOUNT", "300"))
    drop_winners: int = int(os.getenv("DROP_WINNERS", "3"))
    drop_minutes: int = int(os.getenv("DROP_MINUTES", "10"))
    drop_stars_prize: str = os.getenv("DROP_STARS_PRIZE", "50 ⭐")

    # Магазин за фишки (в личке с ботом).
    shop_enabled: bool = os.getenv("SHOP_ENABLED", "1") == "1"
    shop_badges: tuple[str, ...] = tuple(os.getenv("SHOP_BADGES", "💎,🐉,🦁,⚡️,🔥,🍀,🎩,🦅").split(","))
    shop_badge_price: int = int(os.getenv("SHOP_BADGE_PRICE", "1000"))
    shop_title_price: int = int(os.getenv("SHOP_TITLE_PRICE", "10000"))
    shop_custom_title_price: int = int(os.getenv("SHOP_CUSTOM_TITLE_PRICE", "15000"))
    shop_title_days: int = int(os.getenv("SHOP_TITLE_DAYS", "7"))
    shop_vip_price: int = int(os.getenv("SHOP_VIP_PRICE", "5000"))
    shop_vip_days: int = int(os.getenv("SHOP_VIP_DAYS", "7"))
    vip_max_bet: int = int(os.getenv("VIP_MAX_BET", "100000"))
    shop_spin_price: int = int(os.getenv("SHOP_SPIN_PRICE", "100"))

    def payout(self, kind: str, pick: str) -> float:
        if kind == "suit":
            return self.payout_suit
        if kind == "cards":
            return self.payout_cards
        return {"P": self.payout_player, "B": self.payout_banker, "T": self.payout_tie}[pick]
