"""Режим пенальти (GAME=penalty): разбор постов канала и ставки на серию.

Формат поста (пример):
    ⏳ #N44 #t_05_35
    Манчестер Сити (0:0) Ювентус
    П1 1.92 | П2 1.89
    ТБ 4.5 1.66 | ТМ 4.5 2.09

Канал публикует посты на пару игр вперёд со счётом (0:0) и коэффициентами.
Во время серии счёт в посте меняется, после конца ставится 🏁 и ✅ у победителя.
Ставки: П1 / П2 — кто выиграет серию, ТБ / ТМ — тотал голов больше / меньше
линии. Коэффициенты берутся из поста.
"""

import re
from dataclasses import dataclass, field

_TEAMS_RE = re.compile(r"^\s*(?:✅\s*)?(?P<home>.+?)\s*\((?P<a>\d+)\s*:\s*(?P<b>\d+)\)\s*(?P<away>.+?)\s*(?:✅\s*)?$", re.M)
_WIN_RE = re.compile(r"П1\s*(?P<p1>\d+(?:[.,]\d+)?)\s*\|\s*П2\s*(?P<p2>\d+(?:[.,]\d+)?)")
_TOTAL_RE = re.compile(
    r"ТБ\s*(?P<line>\d+(?:[.,]\d+)?)\s+(?P<over>\d+(?:[.,]\d+)?)\s*\|\s*ТМ\s*\d+(?:[.,]\d+)?\s+(?P<under>\d+(?:[.,]\d+)?)"
)
_NUM_RE = re.compile(r"#N(\d+)")

WIN_ALIASES = {"п1": "1", "p1": "1", "1": "1", "п2": "2", "p2": "2", "2": "2"}
TOTAL_ALIASES = {
    "тб": "O", "tb": "O", "больше": "O", "over": "O", "ko'p": "O",
    "тм": "U", "tm": "U", "меньше": "U", "under": "U", "kam": "U",
}


def _num(raw: str) -> float:
    return float(raw.replace(",", "."))


@dataclass(frozen=True)
class PenaltyPost:
    number: int
    home: str
    away: str
    score: tuple[int, int]
    finished: bool
    odds: dict[str, float] = field(default_factory=dict)  # "1", "2", "O", "U"
    line: float | None = None

    @property
    def started(self) -> bool:
        """Серия уже идёт или закончилась — ставки на неё закрыты."""
        return self.finished or self.score != (0, 0)

    @property
    def winner(self) -> str | None:
        a, b = self.score
        return "1" if a > b else "2" if b > a else None

    @property
    def total(self) -> int:
        return sum(self.score)


def parse_post(text: str | None) -> PenaltyPost | None:
    if not text:
        return None
    text = text.replace("️", "")
    num, teams = _NUM_RE.search(text), _TEAMS_RE.search(text)
    if not num or not teams:
        return None
    odds: dict[str, float] = {}
    line = None
    if win := _WIN_RE.search(text):
        odds["1"], odds["2"] = _num(win["p1"]), _num(win["p2"])
    if total := _TOTAL_RE.search(text):
        line = _num(total["line"])
        odds["O"], odds["U"] = _num(total["over"]), _num(total["under"])
    return PenaltyPost(
        number=int(num.group(1)),
        home=teams["home"].strip(),
        away=teams["away"].strip(),
        score=(int(teams["a"]), int(teams["b"])),
        finished="🏁" in text,
        odds=odds,
        line=line,
    )


def parse_pick(word: str) -> tuple[str, str] | None:
    """("win", "1"|"2") или ("total", "O"|"U") — линию тотала добавляет betting из поста игры."""
    word = word.strip().lower()
    if word in WIN_ALIASES:
        return "win", WIN_ALIASES[word]
    if word in TOTAL_ALIASES:
        return "total", TOTAL_ALIASES[word]
    return None


def bet_wins(kind: str, pick: str, post: PenaltyPost) -> bool:
    if kind == "win":
        return pick == post.winner
    if kind == "total":
        side, line = pick[0], float(pick[1:])
        return post.total > line if side == "O" else post.total < line
    raise ValueError(f"unknown penalty bet kind: {kind}")
