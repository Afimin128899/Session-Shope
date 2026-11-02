"""Safe projections of the shared inventory and an authoritative checkout."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction


class CheckoutError(ValueError):
    def __init__(self, message, code='conflict'):
        super().__init__(message)
        self.code = code


def mask_phone(phone):
    phone = str(phone or '')
    return phone[:4] + ' ••• ' + phone[-3:] if len(phone) > 7 else '••• •••'


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


async def pricing(cur, user_id):
    await cur.execute('SELECT referrer_id FROM referrals WHERE referral_id = %s', (user_id,))
    ref = await cur.fetchone()
    if not ref or ref['referrer_id'] == user_id:
        return None, Decimal('0'), Decimal('0')
    await cur.execute('SELECT discount_pct, bonus_pct FROM referral_settings WHERE id = 1')
    settings = await cur.fetchone() or {'discount_pct': 5, 'bonus_pct': 5}
    discount, bonus = Decimal(str(settings['discount_pct'])), Decimal(str(settings['bonus_pct']))
    if not 0 <= discount <= 100 or not 0 <= bonus <= 100:
        raise CheckoutError('Настройки скидки временно недоступны.', 'unavailable')
    return ref['referrer_id'], discount, bonus


async def catalog(user_id, category='', query='', sort='new', page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            _, discount, _ = await pricing(cur, user_id)
            await cur.execute(
                "SELECT c.slug, c.name, COUNT(a.id) AS count FROM categories c "
                "LEFT JOIN accounts a ON a.country = c.slug AND a.status = 'available' "
                'WHERE c.is_active = 1 GROUP BY c.slug, c.name ORDER BY c.sort_order, c.name'
            )
            categories = list(await cur.fetchall())
            conditions, params = ["a.status = 'available'", 'c.is_active = 1'], []
            if category:
                conditions.append('c.slug = %s')
                params.append(category)
            if query:
                # Search category names, not undisclosed full phone numbers.
                conditions.append("c.name LIKE %s ESCAPE '='")
                params.append('%' + query.replace('=', '==').replace('%', '=%').replace('_', '=_') + '%')
            ordering = {'new': 'a.id DESC', 'price_asc': 'a.price ASC, a.id DESC', 'price_desc': 'a.price DESC, a.id DESC'}[sort]
            await cur.execute(
                'SELECT a.id, a.number, a.price, c.slug, c.name FROM accounts a '
                'JOIN categories c ON c.slug = a.country WHERE ' + ' AND '.join(conditions) +
                f' ORDER BY {ordering} LIMIT 25 OFFSET %s', (*params, page * 24),
            )
            accounts = list(await cur.fetchall())
            return {'categories': categories, 'has_more': len(accounts) > 24, 'items': [
                {'id': row['id'], 'category': row['slug'], 'name': row['name'], 'phone': mask_phone(row['number']),
                 'price': str(money(Decimal(str(row['price'])) * (1 - discount / 100))),
                 'original_price': str(row['price']), 'discount': str(discount)} for row in accounts[:24]
            ]}


async def access_settings():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT `key`, `value` FROM settings WHERE `key` IN ('maintenance_mode', 'sub_channel_id', 'sub_channel_enabled', 'sub_channel_url')")
            return {row['key']: row['value'] for row in await cur.fetchall()}


async def checkout(user_id, account_id, quoted_price):
    async with _transaction() as cur:
        await cur.execute(
            "SELECT a.id, a.price, a.country FROM accounts a JOIN categories c ON c.slug = a.country "
            "WHERE a.id = %s AND a.status = 'available' AND c.is_active = 1 FOR UPDATE", (account_id,),
        )
        account = await cur.fetchone()
        if account is None:
            raise CheckoutError('Этот аккаунт уже куплен. Обновите каталог.', 'sold')
        referrer, discount, bonus_pct = await pricing(cur, user_id)
        base = Decimal(str(account['price']))
        actual_price = money(base * (1 - discount / 100))
        if base <= 0 or actual_price < 0:
            raise CheckoutError('Некорректная цена товара.', 'unavailable')
        if actual_price != quoted_price:
            raise CheckoutError('Цена изменилась. Обновите каталог и подтвердите покупку заново.', 'price_changed')
        # Stable lock ordering includes the referrer to avoid reciprocal-referral deadlocks.
        users = sorted({user_id, referrer} - {None})
        await cur.execute('SELECT id, balance FROM users WHERE id IN (' + ','.join(['%s'] * len(users)) + ') ORDER BY id FOR UPDATE', tuple(users))
        balances = {row['id']: row['balance'] for row in await cur.fetchall()}
        if user_id not in balances or Decimal(str(balances[user_id])) < actual_price:
            raise CheckoutError('Недостаточно средств. Пополните баланс в боте.', 'insufficient_balance')
        await cur.execute('UPDATE users SET balance = balance - %s WHERE id = %s', (actual_price, user_id))
        await cur.execute("UPDATE accounts SET status = 'sold' WHERE id = %s", (account_id,))
        await cur.execute(
            'INSERT INTO purchases (user_id, account_id, date, currency, paid_amount) VALUES (%s, %s, %s, %s, %s)',
            (user_id, account_id, datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d %H:%M:%S'), 'RUB', actual_price),
        )
        order_id = cur.lastrowid
        if referrer in balances:
            bonus = (base * bonus_pct / 100).quantize(Decimal('0.00000001'))
            await cur.execute('UPDATE users SET balance = balance + %s WHERE id = %s', (bonus, referrer))
        await cur.execute(
            'UPDATE purchases SET referrer_id = %s, referral_bonus = %s WHERE id = %s',
            (referrer if referrer in balances else None, bonus if referrer in balances else 0, order_id),
        )
        return {'id': order_id, 'paid_amount': str(actual_price), 'balance': str(Decimal(str(balances[user_id])) - actual_price)}


async def orders(user_id, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT p.id, p.date, p.currency, p.paid_amount, p.status, a.number, c.name, '
                't.id AS ticket_id, t.status AS ticket_status FROM purchases p '
                'LEFT JOIN accounts a ON a.id = p.account_id LEFT JOIN categories c ON c.slug = a.country '
                'LEFT JOIN support_tickets t ON t.purchase_id = p.id WHERE p.user_id = %s '
                'ORDER BY p.id DESC LIMIT 25 OFFSET %s', (user_id, page * 24),
            )
            rows = list(await cur.fetchall())
            for row in rows:
                row['name'] = row['name'] or 'Аккаунт'
            return {'items': rows[:24], 'has_more': len(rows) > 24}
