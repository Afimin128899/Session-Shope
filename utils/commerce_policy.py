"""Rules for NEW sales and funding. Historical receipts/refunds retain their amounts."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from utils.i18n import tr

MAX_RUB = Decimal('10000.00')
MAX_NEW_STARS = 10000  # Native Stars count ceiling; the RUB 10,000 funding cap applies to SBP only.
_BLOCKED = re.compile(r'(?<![\w])(?:ru|rus|russia|russian|rf|ua|ukr|ukraine|ukrainian|россия|российская|российские|российский|рф|украина|украины|украинские|україн[аи]|украинский)(?![\w])', re.I)


def money(value, *, minimum=Decimal('0.01')):
    try:
        if isinstance(value, bool) or len(str(value)) > 40:
            raise ValueError
        amount = Decimal(str(value))
        if not amount.is_finite() or not minimum <= amount <= MAX_RUB or amount != amount.quantize(Decimal('.01')):
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        raise ValueError(tr('Сумма операции должна быть от {0} до 10 000 ₽, до двух знаков после запятой.', str(minimum))) from None
    return amount


def category_allowed(*values):
    for value in values:
        value = unicodedata.normalize('NFKC', str(value or '')).casefold()
        if '🇷🇺' in value or '🇺🇦' in value or _BLOCKED.search(value.replace('_', ' ').replace('-', ' ')):
            return False
    return True


def require_category(*values):
    if not category_allowed(*values):
        raise ValueError(tr('Добавление и продажа аккаунтов РФ и Украины запрещены.'))


def require_phone(phone):
    value = unicodedata.normalize('NFKC', str(phone or '')).strip()
    if not re.fullmatch(r'\+?[0-9 ()-]{7,25}', value):
        raise ValueError(tr('Не удалось подтвердить международный номер аккаунта.'))
    digits = re.sub('[^0-9]', '', value)
    if digits.startswith('00'):
        digits = digits[2:]
    if not 7 <= len(digits) <= 15:
        raise ValueError(tr('Не удалось подтвердить международный номер аккаунта.'))
    # +7 is shared: Kazakhstan's +76/+77 must remain available.
    if digits.startswith('380') or (digits.startswith('7') and not digits.startswith(('76', '77'))) or (len(digits) == 11 and digits.startswith('8') and not value.startswith('+')):
        raise ValueError(tr('Добавление и продажа аккаунтов РФ и Украины запрещены.'))
    return digits


def require_stock(row):
    require_category(row.get('country'), row.get('category_name'))
    require_phone(row.get('number'))
    money(row.get('price'))


async def category(cur, slug):
    require_category(slug)
    await cur.execute('SELECT slug,name,is_active FROM categories WHERE slug=%s LOCK IN SHARE MODE', (slug,))
    row = await cur.fetchone()
    if not row or not row['is_active']:
        raise ValueError(tr('Категория отключена или не существует.'))
    require_category(row['slug'], row['name'])


async def checkout(cur, ids, *, tuple_cursor=False):
    """Fresh, locked inventory projection; never trust the category chosen by an importer."""
    marks = ','.join(['%s'] * len(ids))
    await cur.execute('SELECT a.country,a.number,a.price,c.name AS category_name FROM accounts a LEFT JOIN categories c ON c.slug=a.country WHERE a.id IN (' + marks + ') ORDER BY a.id FOR UPDATE', tuple(sorted(ids)))
    rows = await cur.fetchall()
    if len(rows) != len(ids):
        raise ValueError(tr('Товар недоступен.'))
    for row in rows:
        require_stock(dict(zip(('country', 'number', 'price', 'category_name'), row)) if tuple_cursor else row)
