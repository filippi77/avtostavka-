"""Собирает бота в один .py-файл для запуска через менеджер скриптов.

    python tools/build_single.py .env dist/stata_bakara_bot.py

Настройки берутся из указанного .env и вшиваются в начало файла (блок SETTINGS),
поэтому готовый файл содержит токен — не коммитьте его и не публикуйте.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULES = ["i18n", "parser", "penalty", "config", "db", "betting", "access", "tournament", "rating", "duels", "cards", "admin", "bot"]

HEADER = '''#!/usr/bin/env python3
"""Бот прогнозов на масти (баккара) — всё в одном файле.

Запуск: python3 {name}
При первом запуске сам ставит библиотеки aiogram и aiosqlite.
База игроков создаётся рядом с файлом: suitbot.sqlite3.
"""

# ====================== НАСТРОЙКИ ======================
# Поменяйте значение и перезапустите бота.
SETTINGS = {settings}
# =======================================================

import importlib.abc
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
for _key, _value in SETTINGS.items():
    os.environ.setdefault(_key, str(_value))
# База всегда рядом с этим файлом, из какой бы папки его ни запустили.
_db = os.environ.get("DB_PATH", "suitbot.sqlite3")
os.environ["DB_PATH"] = _db if os.path.isabs(_db) else os.path.join(HERE, _db)


def _ensure_dependencies():
    try:
        import aiogram  # noqa: F401
        import aiosqlite  # noqa: F401
        import tzdata  # noqa: F401  часовые пояса, если их нет в системе
        return
    except ImportError:
        pass
    packages = ["aiogram>=3.13,<4", "aiosqlite>=0.20", "tzdata"]
    base = [sys.executable, "-m", "pip", "install", "--quiet"]
    for extra in ([], ["--user"], ["--break-system-packages"]):
        print("Устанавливаю библиотеки:", " ".join(packages), *extra, flush=True)
        if subprocess.call(base + extra + packages) == 0:
            importlib.invalidate_caches()
            return
    sys.exit("Не удалось установить aiogram и aiosqlite. Выполните: pip install aiogram aiosqlite")


_SOURCES = {sources}


class _EmbeddedImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Отдаёт модули пакета suitbot из строк выше, как будто это обычные файлы."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "suitbot" or fullname in _SOURCES:
            return importlib.util.spec_from_loader(fullname, self, is_package=fullname == "suitbot")
        return None

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        if module.__name__ == "suitbot":
            module.__path__ = []
            return
        exec(compile(_SOURCES[module.__name__], f"<{{module.__name__}}>", "exec"), module.__dict__)


if __name__ == "__main__":
    if not os.environ.get("BOT_TOKEN", "").split(":")[0].isdigit():
        sys.exit("Впишите токен бота в SETTINGS (строка 'BOT_TOKEN') в начале этого файла.")
    _ensure_dependencies()
    sys.meta_path.insert(0, _EmbeddedImporter())
    import asyncio

    from suitbot.bot import main

    asyncio.run(main())
'''


def read_env(path: Path) -> dict[str, str]:
    settings = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            settings[key.strip()] = value
    return settings


def build(env_path: Path, out_path: Path) -> None:
    settings = read_env(env_path)
    settings_src = "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in settings.items()) + "}"
    sources = {
        f"suitbot.{name}": (ROOT / "suitbot" / f"{name}.py").read_text(encoding="utf-8") for name in MODULES
    }
    sources_src = "{\n" + "".join(f"    {k!r}: {v!r},\n" for k, v in sources.items()) + "}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        HEADER.format(name=out_path.name, settings=settings_src, sources=sources_src), encoding="utf-8"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    build(Path(sys.argv[1]), Path(sys.argv[2]))
    print("готово:", sys.argv[2])
