"""Explicit UI template translations. Dynamic values are never translated."""
import json
import re
from contextvars import ContextVar
from pathlib import Path

LANGUAGE = ContextVar('sband_language', default='ru')
SUPPORTED = {'ru', 'en'}
_catalog_path = Path(__file__).resolve().parent.parent / 'miniapp/static/translations.json'
_translations = json.loads(_catalog_path.read_text()) if _catalog_path.is_file() else {}

# New bot navigation labels do not require changing the preserved Mini App files.
for _source, _english in {
    'Назад в настройки': 'Back to settings',
    'Назад в профиль': 'Back to profile',
    'Правила': 'Rules',
    'Язык': 'Language',
    'Информация о сервисе и язык интерфейса.': 'Store information and interface language.',
    'Выберите язык интерфейса бота.': 'Choose the bot interface language.',
    'Бот использует выбранный язык.': 'The bot uses the selected language.',
}.items():
    _translations.setdefault(_source, _english)


def _plain(source):
    if source in _translations:
        return _translations[source]
    key=source.strip()
    return source.replace(key,_translations[key],1) if key and key in _translations else source


def tr(source, *values):
    result = source
    if LANGUAGE.get() == 'en':
        if re.search(r'<[a-z!/]',source,re.I):
            parts=re.split(r'(<[^>]*>)',source)
            result=''.join(part if part.startswith('<') else _plain(part) for part in parts)
        else:
            result=_plain(source)
    return result.format(*values) if values else result


def language(value):
    return value if value in SUPPORTED else 'ru'
