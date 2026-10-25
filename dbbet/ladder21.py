# -*- coding: utf-8 -*-
"""Калькулятор догона для 21 очко с учётом максимальной ставки сайта.

Ставка каждого шага — минимальная, при которой заход покрывает все прошлые
проигрыши цепочки и даёт целевую прибыль:
    ставка = (проигрыш_цепочки + цель) / (КФ - 1)
Если такая ставка больше лимита сайта — цепочка дальше невозможна.

  python ladder21.py --kf 47 --max 970 --base 50
  python ladder21.py --kf 13.3 --max 3650 --base 100 --profit 500
"""
import argparse
import math

MIN_STAKE = 10  # минимальная ставка на DB Bet


def recovery_stake(lost, profit, kf, round_to=1):
  stake = (lost + profit) / (kf - 1)
  return max(MIN_STAKE, math.ceil(stake / round_to) * round_to)


def ladder(kf, max_stake, base, profit=None, steps=None, round_to=1):
  """Список (шаг, ставка, проигрыш_до_шага, прибыль_при_заходе) до лимита сайта."""
  if profit is None:
    profit = base * (kf - 1)  # как от ровной первой ставки
  rows, lost, n = [], 0.0, 1
  while steps is None or n <= steps:
    stake = recovery_stake(lost, profit, kf, round_to)
    if stake > max_stake:
      break
    rows.append((n, stake, lost, stake * kf - stake - lost))
    lost += stake
    n += 1
  return rows


def main():
  ap = argparse.ArgumentParser(description="Догон 21 очко в пределах лимита ставки")
  ap.add_argument("--kf", type=float, required=True, help="коэффициент исхода")
  ap.add_argument("--max", type=float, required=True, help="максимальная ставка на сайте")
  ap.add_argument("--base", type=float, default=10, help="первая ставка")
  ap.add_argument("--profit", type=float, help="цель цепочки (по умолчанию как с первой ставки)")
  ap.add_argument("--steps", type=int, help="ограничить число шагов")
  ap.add_argument("--round", type=int, default=1, help="округление ставки вверх, ₽")
  a = ap.parse_args()
  rows = ladder(a.kf, a.max, a.base, a.profit, a.steps, a.round)
  for n, stake, lost, win in rows:
    print(f"шаг {n:>3}: ставка {stake:>7.0f}   проиграно до него {lost:>8.0f}   заход даст {win:>+8.0f}")
  if rows:
    total = rows[-1][2] + rows[-1][1]
    print(f"Шагов до лимита {a.max:.0f} ₽: {len(rows)}. Если не зайдёт ни разу — минус {total:.0f} ₽.")


if __name__ == "__main__":
  main()
