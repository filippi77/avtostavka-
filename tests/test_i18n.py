import string

import pytest

from suitbot import i18n
from suitbot.parser import parse_pick


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


@pytest.mark.parametrize("key", sorted(i18n.TEXTS))
def test_translations_use_same_placeholders(key):
    ru, uz = i18n.TEXTS[key]
    assert uz.strip(), f"{key}: пустой перевод"
    assert placeholders(ru) == placeholders(uz), key


def test_switch_language():
    try:
        i18n.set_lang("uz")
        assert i18n.t("btn_balance") == "💰 Balansim"
        assert i18n.t("bonus_ok", amount=300, balance=800) == "🎁 +300 fishka! Balans: 800"
        assert i18n.variants("btn_balance") == {"💰 Мой баланс", "💰 Balansim"}
        i18n.set_lang("xx")  # неизвестный язык — русский
        assert i18n.LANG == "ru"
    finally:
        i18n.set_lang("ru")


def test_uzbek_words_in_commands():
    assert parse_pick("o'yinchi") == ("side", "P")
    assert parse_pick("O‘yinchi") == ("side", "P")
    assert parse_pick("durrang") == ("side", "T")
    assert parse_pick("chillak") == ("suit", "♣")
    assert parse_pick("g'isht") == ("suit", "♦")


@pytest.mark.parametrize("key", sorted(k for k in i18n.TEXTS if k.endswith("@pen")))
def test_penalty_texts_match_base_placeholders(key):
    base = key.removesuffix("@pen")
    if base in i18n.TEXTS:
        # пенальти-текст может не использовать часть подстановок, но не должен требовать новых
        assert placeholders(i18n.TEXTS[key][0]) <= placeholders(i18n.TEXTS[base][0]), key
