"""Bounded parsing for values from Telegram callbacks and text fields."""
from utils.i18n import tr


def positive_id(value):
    if not isinstance(value, str) or not value.isascii() or (not value.isdecimal()) or (len(value) > 10):
        raise ValueError(tr('Некорректный номер. Откройте меню заново.'))
    number = int(value)
    if not 0 < number <= 2147483647:
        raise ValueError(tr('Некорректный номер. Откройте меню заново.'))
    return number


def page_index(value):
    if not isinstance(value, str) or not value.isascii() or (not value.isdecimal()) or (len(value) > 6):
        raise ValueError(tr('Некорректная страница. Откройте меню заново.'))
    return min(int(value), 100000)
