# avtostavka — бот для автоставок

Бот ищет **value-ставки** (коэффициент у букмекера выше справедливого), считает размер
ставки по банкроллу, проверяет лимиты риска, ставит, ведёт историю в SQLite и
рассчитывает ставки по результатам. Только стандартная библиотека Python 3.11+.

> По умолчанию бот работает в режиме **paper** — ставки только записываются, деньги
> не тратятся. Ставки связаны с риском потерь; соблюдайте правила площадки и законы
> своей страны.

## Как это работает

1. **Котировки** — из JSON-файла или [The Odds API](https://the-odds-api.com).
2. **Стратегия** (`strategy.py`) — по букмекерам-ориентирам (по умолчанию Pinnacle)
   снимается маржа и получается «честная» вероятность `p`. Перевес = `p * k - 1`.
   Сигнал, если `min_edge <= перевес <= max_edge`, коэффициент в `[min_odds, max_odds]`
   и до начала события подходящее время. По умолчанию — одна ставка на рынок.
3. **Размер ставки** (`staking.py`) — `fixed`, `percent` или дробный Келли
   (по умолчанию ¼ Келли) с ограничениями min/max и округлением.
4. **Риск-менеджмент** (`risk.py`):
   - защита от повторной ставки на тот же исход;
   - лимит открытых ставок и ставок в день;
   - максимум % банка на одну ставку и на одно событие;
   - дневной лимит убытка и максимальная просадка от пика — остановка торговли.
5. **Исполнение** (`providers/paper.py`) и **расчёт** по результатам.
6. **Уведомления** в Telegram (необязательно).

## Быстрый старт

```bash
cp config.example.toml config.toml
python -m avtostavka -c config.toml scan          # показать value-ставки
python -m avtostavka -c config.toml run --once    # один цикл (paper)
python -m avtostavka -c config.toml run           # бесконечный цикл
python -m avtostavka -c config.toml stats         # статистика: ROI, проходимость, просадка
```

### Бэктест

```bash
python examples/make_history.py examples/history_odds.json examples/history_results.json
python -m avtostavka -c config.toml backtest examples/history_odds.json examples/history_results.json
```

Формат файлов — см. `examples/odds.json` и `examples/results.json`. В `start_time`
можно указать ISO-время или смещение от текущего момента, например `"+3h"`.

### Реальные котировки

```toml
[provider]
odds_source = "theoddsapi"
theoddsapi_sports = ["soccer_epl", "soccer_uefa_champs_league"]
```

```bash
export ODDS_API_KEY=...
```

Результаты матчей (рынок `h2h`) подтягиваются оттуда же автоматически.

### Telegram

```bash
export TELEGRAM_BOT_TOKEN=...
```
и укажите `telegram_chat_id` в секции `[notify]`.

## Реальные ставки

Исполнитель для конкретной площадки не встроен. Унаследуйтесь от
`avtostavka.providers.base.Executor`, реализуйте `place()` через официальный API
площадки (например, биржи Betfair) и подключите его в `cli.build_engine`. После этого
выставьте `dry_run = false` и `executor = "<имя>"`. Сначала погоняйте стратегию
в paper-режиме и на бэктесте.

## Тесты

```bash
python -m unittest -v
```
