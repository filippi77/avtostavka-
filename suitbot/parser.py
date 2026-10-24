"""Разбор постов канала статистики баккары.

Формат поста (пример):
    #N207. 7(J♦️ 7♣️) - ✅9(2♦️ 7♥️) #T16 🔵 #R

Первая скобка — карты игрока, вторая — карты банкира, число перед скобкой —
очки руки. Пока игра идёт, в посте стоят маркеры ⏰ / ▶, после завершения
пост редактируется в финальный вид.
"""

import re
from dataclasses import dataclass

SUITS = "♠♣♥♦"

SUIT_ALIASES = {
    "♠": "♠", "пики": "♠", "пика": "♠", "п": "♠",
    "♣": "♣", "крести": "♣", "трефы": "♣", "треф": "♣", "к": "♣",
    "♥": "♥", "черви": "♥", "червы": "♥", "черв": "♥", "ч": "♥",
    "♦": "♦", "буби": "♦", "бубны": "♦", "бубен": "♦", "б": "♦",
}

SIDE_ALIASES = {
    "игрок": "P", "и": "P", "p": "P", "player": "P",
    "банкир": "B", "банк": "B", "b": "B", "banker": "B",
    "ничья": "T", "н": "T", "t": "T", "tie": "T",
}

IN_PROGRESS_MARKERS = ("⏰", "▶")

_GAME_RE = re.compile(
    r"#N(\d+)\.?\s*"
    r"[✅▶⏰\s]*(?P<p_pts>\d+)\s*\((?P<p_cards>[^)]*)\)"
    r"\s*-\s*"
    r"[✅▶⏰\s]*(?P<b_pts>\d+)\s*\((?P<b_cards>[^)]*)\)"
)
_CARD_RE = re.compile(r"(10|[2-9AJQKТВДК])\s*([♠♣♥♦])")
_GAME_NUM_RE = re.compile(r"#N(\d+)")


@dataclass(frozen=True)
class GameResult:
    number: int
    player_points: int
    banker_points: int
    player_cards: tuple[tuple[str, str], ...]
    banker_cards: tuple[tuple[str, str], ...]
    finished: bool

    @property
    def player_suits(self) -> set[str]:
        return {suit for _, suit in self.player_cards}

    @property
    def winner(self) -> str:
        if self.player_points > self.banker_points:
            return "P"
        if self.banker_points > self.player_points:
            return "B"
        return "T"


def _clean(text: str) -> str:
    # Вариационный селектор превращает ♥ в ♥️ — для разбора он не нужен.
    return text.replace("️", "")


def _cards(raw: str) -> tuple[tuple[str, str], ...]:
    return tuple((rank, suit) for rank, suit in _CARD_RE.findall(raw))


def parse_game(text: str | None) -> GameResult | None:
    if not text:
        return None
    text = _clean(text)
    m = _GAME_RE.search(text)
    if not m:
        return None
    return GameResult(
        number=int(m.group(1)),
        player_points=int(m.group("p_pts")),
        banker_points=int(m.group("b_pts")),
        player_cards=_cards(m.group("p_cards")),
        banker_cards=_cards(m.group("b_cards")),
        finished=not any(marker in text for marker in IN_PROGRESS_MARKERS),
    )


def parse_game_number(text: str | None) -> int | None:
    """Номер игры из любого поста, в том числе ещё не начавшейся раздачи."""
    if not text:
        return None
    m = _GAME_NUM_RE.search(text)
    return int(m.group(1)) if m else None


def parse_pick(word: str) -> tuple[str, str] | None:
    """Возвращает (тип ставки, выбор): ("suit", "♥") или ("side", "P")."""
    word = _clean(word).strip().lower()
    if word in SUIT_ALIASES:
        return "suit", SUIT_ALIASES[word]
    if word in SIDE_ALIASES:
        return "side", SIDE_ALIASES[word]
    return None


def bet_wins(kind: str, pick: str, result: GameResult) -> bool:
    if kind == "suit":
        return pick in result.player_suits
    if kind == "side":
        return pick == result.winner
    raise ValueError(f"unknown bet kind: {kind}")
