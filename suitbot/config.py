import os
from dataclasses import dataclass, field


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x}


@dataclass(frozen=True)
class Config:
    token: str = field(default_factory=lambda: os.environ["BOT_TOKEN"])
    db_path: str = os.getenv("DB_PATH", "suitbot.sqlite3")
    # Каналы/чаты, из которых принимаются результаты. Пусто — любой источник
    # с постами формата "#N123. ...". Лучше указать id канала статистики.
    result_sources: set[int] = field(default_factory=lambda: _ids(os.getenv("RESULT_SOURCES", "")))
    admins: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMINS", "")))

    chips_per_star: int = int(os.getenv("CHIPS_PER_STAR", "10"))
    start_balance: int = int(os.getenv("START_BALANCE", "500"))
    daily_bonus: int = int(os.getenv("DAILY_BONUS", "100"))
    min_bet: int = int(os.getenv("MIN_BET", "10"))
    max_bet: int = int(os.getenv("MAX_BET", "10000"))

    # Насколько игр вперёд можно ставить и после какого номера счётчик игр
    # начинается заново (проверьте по своему каналу).
    max_games_ahead: int = int(os.getenv("MAX_GAMES_AHEAD", "20"))
    game_number_wrap: int = int(os.getenv("GAME_NUMBER_WRAP", "1440"))
    # Ставки, которые так и не дождались результата, возвращаются.
    bet_ttl_hours: int = int(os.getenv("BET_TTL_HOURS", "6"))

    # Коэффициенты выплат (ставка × коэффициент при выигрыше).
    payout_suit: float = float(os.getenv("PAYOUT_SUIT", "1.9"))
    payout_player: float = float(os.getenv("PAYOUT_PLAYER", "1.95"))
    payout_banker: float = float(os.getenv("PAYOUT_BANKER", "1.95"))
    payout_tie: float = float(os.getenv("PAYOUT_TIE", "8"))

    # Недельный турнир: всем поровну бесплатных фишек, призы раздаёт владелец.
    tournament_enabled: bool = os.getenv("TOURNAMENT_ENABLED", "1") == "1"
    tournament_tz: str = os.getenv("TOURNAMENT_TZ", "Europe/Moscow")
    tournament_start_chips: int = int(os.getenv("TOURNAMENT_START_CHIPS", "1000"))
    tournament_max_bet: int = int(os.getenv("TOURNAMENT_MAX_BET", "500"))
    # Чтобы попасть в призы: сделать минимум ставок и быть в боте не меньше N дней
    # к концу турнира (защита от свежих мультиаккаунтов).
    tournament_min_bets: int = int(os.getenv("TOURNAMENT_MIN_BETS", "20"))
    tournament_min_days_in_bot: int = int(os.getenv("TOURNAMENT_MIN_DAYS_IN_BOT", "3"))
    tournament_prizes: tuple[str, ...] = tuple(
        p.strip() for p in os.getenv(
            "TOURNAMENT_PRIZES", "Telegram Premium на 3 месяца|Подарок от админа|Подарок от админа"
        ).split("|") if p.strip()
    )
    # Куда объявлять начало и итоги. Пусто — во все чаты, где были турнирные ставки.
    tournament_chats: set[int] = field(default_factory=lambda: _ids(os.getenv("TOURNAMENT_CHATS", "")))

    def payout(self, kind: str, pick: str) -> float:
        if kind == "suit":
            return self.payout_suit
        return {"P": self.payout_player, "B": self.payout_banker, "T": self.payout_tie}[pick]
