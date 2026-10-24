"""Генерирует синтетическую историю для бэктеста.

    python examples/make_history.py examples/history_odds.json examples/history_results.json
"""

import json
import random
import sys
from datetime import datetime, timedelta, timezone


def make(n: int = 3000, seed: int = 7):
    rnd = random.Random(seed)
    start = datetime(2026, 1, 1, 18, tzinfo=timezone.utc)
    odds, results = [], {}
    for i in range(n):
        # «Истинные» вероятности исходов матча.
        home = rnd.uniform(0.25, 0.6)
        draw = rnd.uniform(0.2, 0.3)
        away = 1 - home - draw
        true = {"home": home, "draw": draw, "away": away}
        sharp = {k: round(1 / (p * 1.025), 2) for k, p in true.items()}
        # Мягкий букмекер: маржа больше, но котировки шумные — иногда выше справедливых.
        soft = {k: round(1 / (p * rnd.uniform(0.94, 1.12)), 2) for k, p in true.items()}
        eid = f"m{i}"
        odds.append({
            "id": eid, "name": f"Матч {i}", "sport": "soccer",
            "start_time": (start + timedelta(hours=6 * i)).isoformat(),
            "markets": {"h2h": {"pinnacle": sharp, "softbook": soft}},
        })
        r = rnd.random()
        results[eid] = {"h2h": "home" if r < home else "draw" if r < home + draw else "away"}
    return odds, results


if __name__ == "__main__":
    o, r = make()
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(o, fh, ensure_ascii=False)
    with open(sys.argv[2], "w", encoding="utf-8") as fh:
        json.dump(r, fh, ensure_ascii=False)
