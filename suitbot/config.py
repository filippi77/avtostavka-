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

    chips_per_star: int = int(os.getenv("CHIPS_PER_STAR", "10"))
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

    # Подписка на канал, без которой нельзя ставить, брать бонус и вступать в турнир.
    # Бот должен быть админом этого канала, иначе Telegram не покажет ему подписчиков.
    required_channel: str = os.getenv("REQUIRED_CHANNEL", "")  # @username или -100…
    required_channel_url: str = os.getenv("REQUIRED_CHANNEL_URL", "")

    # Коэффициенты выплат (ставка × коэффициент при выигрыше).
    payout_suit: float = float(os.getenv("PAYOUT_SUIT", "1.9"))
    payout_player: float = float(os.getenv("PAYOUT_PLAYER", "1.95"))
    payout_banker: float = float(os.getenv("PAYOUT_BANKER", "1.95"))
    payout_tie: float = float(os.getenv("PAYOUT_TIE", "8"))

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

    def payout(self, kind: str, pick: str) -> float:
        if kind == "suit":
            return self.payout_suit
        return {"P": self.payout_player, "B": self.payout_banker, "T": self.payout_tie}[pick]
