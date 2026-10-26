# -*- coding: utf-8 -*-
"""Анализ базы матчей настольного тенниса (h2h_db.json бота «Настолка Аут»).

  python tt/analyze_h2h.py путь/к/h2h_db.json

1. Рейтинг Эло игроков по ходу времени: насколько он предсказывает победителя
   (проверка только на матчах, которые идут ПОСЛЕ обучения).
2. Тотал сета меньше 18.5 (стратегия «Настолки Аут»): помогает ли «форма» игроков
   угадывать такие сеты лучше, чем средняя частота, и хватает ли этого против КФ.
"""
import collections
import json
import math
import sys


def load(path):
  out = []
  for m in json.load(open(path, encoding="utf-8"))["matches"]:
    sets = [tuple(s) for s in m.get("sets") or []]
    a = sum(1 for p, q in sets if p > q)
    b = len(sets) - a
    # только корректные матчи до 3 побед, где счёт совпадает с сетами
    if (a, b) != (m["w1"], m["w2"]) or max(a, b) != 3 or min(a, b) > 2:
      continue
    out.append({"p1": m["p1"], "p2": m["p2"], "w1": a, "w2": b, "sets": sets, "ts": m["ts"]})
  out.sort(key=lambda x: x["ts"])
  return out


# ---------- 1. Эло ----------

def elo_test(matches, k=8.0, train_share=0.5, min_games=5):
  rating = collections.defaultdict(lambda: 1500.0)
  games = collections.Counter()
  split = int(len(matches) * train_share)
  rows = []  # (вероятность победы p1 по рейтингу, победил ли p1)
  for i, m in enumerate(matches):
    r1, r2 = rating[m["p1"]], rating[m["p2"]]
    e1 = 1 / (1 + 10 ** ((r2 - r1) / 400))
    won = 1.0 if m["w1"] > m["w2"] else 0.0
    if i >= split and games[m["p1"]] >= min_games and games[m["p2"]] >= min_games:
      rows.append((e1, won))
    # поправка сильнее при разгроме 3:0
    margin = 1.0 + 0.25 * abs(m["w1"] - m["w2"])
    rating[m["p1"]] += k * margin * (won - e1)
    rating[m["p2"]] -= k * margin * (won - e1)
    games[m["p1"]] += 1
    games[m["p2"]] += 1
  return rows


def report_elo(rows):
  n = len(rows)
  acc = sum(1 for p, w in rows if (p >= 0.5) == (w == 1.0)) / n
  brier = sum((p - w) ** 2 for p, w in rows) / n
  ll = -sum(w * math.log(max(p, 1e-9)) + (1 - w) * math.log(max(1 - p, 1e-9)) for p, w in rows) / n
  print(f"Проверка на {n} матчах (вторая половина базы, у обоих ≥5 игр до матча)")
  print(f"  Рейтинг угадывает победителя: {acc:.1%}")
  print(f"  Брайер {brier:.4f} (монетка 0.2500), лог-лосс {ll:.4f} (монетка 0.6931)")
  print("  Калибровка (рейтинг говорит → на деле выиграл фаворит рейтинга):")
  bins = collections.defaultdict(list)
  for p, w in rows:
    fav_p, fav_w = (p, w) if p >= 0.5 else (1 - p, 1 - w)
    bins[min(int(fav_p * 10), 9)].append((fav_p, fav_w))
  for b in sorted(bins):
    v = bins[b]
    print(f"    {b * 10}–{b * 10 + 10}%: матчей {len(v):5d}, ожидалось {sum(x for x, _ in v) / len(v):.1%},"
          f" выиграл {sum(y for _, y in v) / len(v):.1%}")


# ---------- 2. Тотал сета < 18.5 ----------

def under(s):
  return s[0] + s[1] <= 18


def totals_test(matches, first_sets=3, min_form=4, odds=1.88):
  """Для каждого из первых сетов: доля «меньше 18.5» у обоих игроков в прошлых
  матчах (форма) → как часто сет на деле ушёл в меньше."""
  hist = collections.defaultdict(lambda: [0, 0])  # игрок → [сетов меньше, всего сетов]
  base = [0, 0]
  buckets = collections.defaultdict(lambda: [0, 0])
  for m in matches:
    sets = m["sets"][:first_sets]
    f1, f2 = hist[m["p1"]], hist[m["p2"]]
    have = f1[1] >= min_form * first_sets and f2[1] >= min_form * first_sets
    form = (f1[0] / f1[1] + f2[0] / f2[1]) / 2 if have else None
    for s in sets:
      u = under(s)
      base[0] += u
      base[1] += 1
      if form is not None:
        b = buckets[min(int(form * 10), 9)]
        b[0] += u
        b[1] += 1
    for s in m["sets"][:first_sets]:
      for p in (m["p1"], m["p2"]):
        hist[p][0] += under(s)
        hist[p][1] += 1
  be = 1 / odds
  print(f"\nТотал сета меньше 18.5 (сеты 1–{first_sets}): в среднем {base[0] / base[1]:.1%} сетов"
        f" из {base[1]}; для безубытка при КФ {odds} нужно {be:.1%}")
  print("  Форма обоих игроков (их доля таких сетов раньше) → как вышло на деле:")
  for b in sorted(buckets):
    hit, n = buckets[b]
    if n < 30:
      continue
    rate = hit / n
    roi = rate * odds - 1
    print(f"    форма {b * 10}–{b * 10 + 10}%: сетов {n:5d}, меньше 18.5 — {rate:.1%},"
          f" доход на ставку при КФ {odds}: {roi:+.1%}")


def main():
  path = sys.argv[1] if len(sys.argv) > 1 else "h2h_db.json"
  matches = load(path)
  print(f"Корректных матчей: {len(matches)}\n")
  report_elo(elo_test(matches))
  totals_test(matches)


if __name__ == "__main__":
  main()
