"""Bot shopping filters and bulk reservations over the existing shared inventory.

No schema, prices, balances or payment-provider settings are changed here.
"""
from datetime import date
from decimal import Decimal, InvalidOperation

import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction
from miniapp.storage import CheckoutError, pricing, money
from utils.commerce_policy import category_allowed
from utils.country_codes import COUNTRY_MAP
from utils.i18n import tr

MODES = {'auto', 'aged', 'premium'}
PAGE_SIZE = 8
AGED_DAYS = 30


def _iso(flag):
    return ''.join(chr(ord(c) - 0x1F1E6 + ord('a')) for c in flag)


COUNTRIES = {_iso(flag): {'name': name, 'flag': flag} for name, flag in COUNTRY_MAP.values()}
COUNTRIES['kz'] = {'name': 'Казахстан', 'flag': '🇰🇿'}
COUNTRIES['other'] = {'name': 'Другие страны', 'flag': '🌐'}
SPAM_SUFFIXES = {'clear': '', 'permanent': 'Вечный СБ', 'limited': 'Есть СБ', 'unverified': 'СБ не проверен'}
SPAM_GROUP = "CASE WHEN a.spam_status IN ('clear','permanent','limited') THEN a.spam_status ELSE 'unverified' END"


def split_nation(nation):
    if not isinstance(nation, str):
        raise ValueError(tr('Некорректный раздел каталога.'))
    parts = nation.split('~')
    if len(parts) > 2 or parts[0] not in {'all', *COUNTRIES} or (len(parts) == 2 and (parts[0] == 'all' or parts[1] not in SPAM_SUFFIXES)):
        raise ValueError(tr('Некорректный раздел каталога.'))
    return parts[0], parts[1] if len(parts) == 2 else None


def country_name(nation):
    country, status = split_nation(nation)
    name = COUNTRIES[country]['name'] if country != 'all' else tr('Все страны')
    return (name + ' ' + SPAM_SUFFIXES.get(status, '')).strip()

# Country derives from the actual phone, including +76/+77 Kazakhstan, rather
# than a manually named category. All SQL fragments are generated from constants.
DIGITS = 'a.number'
for char in ['+', ' ', '-', '(', ')']:
    DIGITS = f"REPLACE({DIGITS},'{char}','')"
DIGITS = f"(CASE WHEN LEFT({DIGITS},2)='00' THEN SUBSTRING({DIGITS},3) ELSE {DIGITS} END)"
_prefixes = {'76': 'kz', '77': 'kz'} | {key[1:]: _iso(flag) for key, (_, flag) in COUNTRY_MAP.items()}
NATION = 'CASE ' + ' '.join(f"WHEN {DIGITS} LIKE '{prefix}%%' THEN '{nation}'" for prefix, nation in sorted(_prefixes.items(), key=lambda item: (-len(item[0]), item[0]))) + " ELSE 'other' END"


def validate(mode, nation='all', year=0):
    split_nation(nation)
    if mode not in MODES or type(year) is not int or (year and not 2013 <= year <= date.today().year):
        raise ValueError(tr('Некорректный раздел каталога.'))


async def _where(cur, user_id, mode, nation='all', year=0):
    validate(mode, nation, year)
    country, spam_status = split_nation(nation)
    await cur.execute("SELECT slug,name FROM categories WHERE is_active=1 AND slug NOT LIKE 'section-%%'")
    slugs = [row['slug'] for row in await cur.fetchall() if category_allowed(row['slug'], row['name'])]
    conditions = ["a.status='available'", 'c.is_active=1', 'a.price>0 AND a.price<=10000',
                  '(a.spam_lease_until IS NULL OR a.spam_lease_until<=UTC_TIMESTAMP())',
                  "NOT EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s)",
                  f"({NATION}) NOT IN ('ru','ua')"]
    params = [user_id]
    if slugs:
        conditions.append('a.country IN (' + ','.join(['%s'] * len(slugs)) + ')'); params.extend(slugs)
    else:
        conditions.append('1=0')
    if mode == 'auto':
        conditions.append('COALESCE(a.is_premium,0)=0')
    elif mode == 'premium':
        conditions.append('a.is_premium=1')
    elif mode == 'aged':
        conditions.append('a.registration_date<=DATE_SUB(UTC_DATE(),INTERVAL %s DAY)'); params.append(AGED_DAYS)
    if country != 'all':
        conditions.append(f'({NATION})=%s'); params.append(country)
    if spam_status is not None:
        conditions.append(f'({SPAM_GROUP})=%s'); params.append(spam_status)
    if year:
        conditions.append('YEAR(a.registration_date)=%s'); params.append(year)
    return ' FROM accounts a JOIN categories c ON c.slug=a.country WHERE ' + ' AND '.join(conditions), params


async def countries(user_id, mode, query=''):
    if not isinstance(query, str) or len(query) > 64:
        raise ValueError(tr('Поиск: до 64 символов.'))
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            where, params = await _where(cur, user_id, mode)
            await cur.execute(f'SELECT {NATION} AS nation,{SPAM_GROUP} AS spam_group,COUNT(*) AS count,MIN(a.price) AS min_price' + where + ' GROUP BY nation,spam_group', tuple(params))
            rows = list(await cur.fetchall())
            _, discount, _ = await pricing(cur, user_id)
    results = []
    for row in rows:
        identity = row['nation']; info = COUNTRIES[identity]
        selection = identity + '~' + row['spam_group']
        aliases = [country_name(selection), info['name'], identity] + [key for key, (_, flag) in COUNTRY_MAP.items() if _iso(flag) == identity]
        if identity == 'kz': aliases += ['+7', '+76', '+77']
        if query and not any(query.casefold().strip() in word.casefold() for word in aliases):
            continue
        results.append(dict(row, flag=info['flag'], name=country_name(selection), country=identity,
                            nation=selection, spam_status=row['spam_group'],
                            min_price=money(Decimal(str(row['min_price'])) * (1 - discount / 100))))
    return sorted(results, key=lambda item: (item['min_price'], item['name']))


async def years(user_id, mode, nation):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            where, params = await _where(cur, user_id, mode, nation)
            await cur.execute('SELECT YEAR(a.registration_date) AS year,COUNT(*) AS count,MIN(a.price) AS min_price' + where + ' AND YEAR(a.registration_date) BETWEEN 2013 AND YEAR(UTC_DATE()) GROUP BY YEAR(a.registration_date) ORDER BY year', tuple(params))
            rows = list(await cur.fetchall()); _, discount, _ = await pricing(cur, user_id)
            for row in rows:
                row['min_price'] = money(Decimal(str(row['min_price'])) * (1 - discount / 100))
            return rows


async def products(user_id, mode, nation='all', year=0, page=0, *, quantity=None):
    if type(page) is not int or not 0 <= page <= 100000 or (quantity is not None and (type(quantity) is not int or not 1 <= quantity <= 20)):
        raise ValueError(tr('Некорректный размер списка.'))
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            where, params = await _where(cur, user_id, mode, nation, year)
            await cur.execute('SELECT COUNT(*) AS n' + where, tuple(params))
            count = (await cur.fetchone())['n']; page = min(page, max(0, (count - 1) // PAGE_SIZE))
            await cur.execute('SELECT a.id,a.number,a.country,a.price,a.warranty_hours,a.spam_status,a.registration_date,a.is_premium' + where + ' ORDER BY a.price,a.id LIMIT %s OFFSET %s', (*params, quantity or PAGE_SIZE, 0 if quantity else page * PAGE_SIZE))
            rows = list(await cur.fetchall()); _, discount, _ = await pricing(cur, user_id)
            for row in rows:
                row['price'] = money(Decimal(str(row['price'])) * (1 - discount / 100))
            return rows, count, page


async def reserve_bulk(user_id, mode, nation, quantity, year=0):
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise ValueError(tr('Количество: от 1 до 20.'))
    async with _transaction() as cur:
        where, params = await _where(cur, user_id, mode, nation, year)
        await cur.execute('SELECT a.id' + where + ' ORDER BY a.price,a.id LIMIT %s', (*params, quantity))
        ids = sorted(row['id'] for row in await cur.fetchall())
        if len(ids) != quantity:
            raise CheckoutError(tr('Недостаточно свободных аккаунтов. Обновите список.'), 'sold')
        marks = ','.join(['%s'] * len(ids))
        await cur.execute('SELECT a.id,a.price,a.warranty_hours,a.spam_status,a.registration_date,a.is_premium' + where + ' AND a.id IN (' + marks + ') ORDER BY a.id FOR UPDATE', (*params, *ids))
        accounts = list(await cur.fetchall())
        if len(accounts) != quantity:
            raise CheckoutError(tr('Товары изменились или заняты. Обновите список.'), 'sold')
        from database.shop_control import check_sales
        await check_sales(cur, account_ids=ids)
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not await cur.fetchone(): raise CheckoutError(tr('Покупатель не найден.'))
        await cur.execute('SELECT account_id FROM shopping_cart WHERE user_id=%s FOR UPDATE', (user_id,))
        existing = {row['account_id'] for row in await cur.fetchall()}
        if len(existing | set(ids)) > 20:
            raise CheckoutError(tr('В корзине может быть не больше 20 аккаунтов. Уменьшите количество.'), 'cart_limit')
        await cur.execute('SELECT account_id,user_id,expires_at>UTC_TIMESTAMP() AS active FROM account_reservations WHERE account_id IN (' + marks + ') ORDER BY account_id FOR UPDATE', tuple(ids))
        if any(row['active'] and row['user_id'] != user_id for row in await cur.fetchall()):
            raise CheckoutError(tr('Один из аккаунтов зарезервирован другим покупателем.'), 'reserved')
        _, discount, _ = await pricing(cur, user_id)
        requested = [{'account_id': row['id'], 'price': str(money(Decimal(str(row['price'])) * (1 - discount / 100))),
                      'warranty_hours': row['warranty_hours'], 'spam_status': row['spam_status'],
                      'registration_date': str(row['registration_date']) if row['registration_date'] else None,
                      'is_premium': row['is_premium']} for row in accounts]
        await cur.execute("SELECT `key`,`value` FROM settings WHERE `key` IN ('wholesale_min_total','wholesale_pct')")
        settings = {row['key']: row['value'] for row in await cur.fetchall()}
        subtotal = sum((Decimal(item['price']) for item in requested), Decimal(0))
        try:
            threshold = Decimal(settings.get('wholesale_min_total', '500'))
            pct = Decimal(settings.get('wholesale_pct', '15'))
            if not threshold.is_finite() or not pct.is_finite() or not 0 <= pct <= 50: raise ValueError
            rate = pct if subtotal >= threshold else Decimal(0)
        except (ValueError, InvalidOperation):
            raise CheckoutError(tr('Настройки опта временно недоступны.')) from None
        total = sum((money(Decimal(item['price']) * (1 - rate / 100)) for item in requested), Decimal(0))
        if total > 10000: raise CheckoutError(tr('Сумма покупки не должна превышать 10 000 ₽.'), 'amount_limit')
        for identity in ids:
            await cur.execute('INSERT IGNORE INTO shopping_cart(user_id,account_id,created_at) VALUES(%s,%s,UTC_TIMESTAMP())', (user_id, identity))
            await cur.execute('INSERT INTO account_reservations(account_id,user_id,expires_at) VALUES(%s,%s,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 5 MINUTE)) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id),expires_at=VALUES(expires_at)', (identity, user_id))
        return {'items': requested, 'total': str(total), 'rate': str(rate), 'created_ids': sorted(set(ids) - existing)}
