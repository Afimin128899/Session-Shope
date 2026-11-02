"""Admin-only reads and changes with an atomic audit trail.

Authorization is checked by handlers. This module never logs account credentials.
"""
import json
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation

import aiomysql

from database.db import _get_pool


@asynccontextmanager
async def _transaction():
    async with _get_pool().acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                yield cur
            await conn.commit()
        except BaseException:
            await conn.rollback()
            raise


async def _record(cur, admin_id, action, target_type, target_id, details):
    await cur.execute(
        "INSERT INTO admin_audit_log (admin_id, action, target_type, target_id, details, created_at) "
        "VALUES (%s, %s, %s, %s, %s, UTC_TIMESTAMP())",
        (admin_id, action, target_type, str(target_id), json.dumps(details, ensure_ascii=False)),
    )


def _decimal(value, places, maximum):
    try:
        value = Decimal(str(value))
        if not value.is_finite() or abs(value) > Decimal(maximum):
            raise ValueError('Сумма выходит за допустимые пределы.')
        rounded = value.quantize(Decimal(places))
        if rounded != value:
            raise ValueError('Слишком много знаков после запятой.')
        return rounded
    except InvalidOperation as exc:
        raise ValueError('Введите корректное число.') from exc


async def change_balance(admin_id, user_id, amount, currency, mode):
    if currency not in {'RUB', 'USDT'} or mode not in {'add', 'set'}:
        raise ValueError('Некорректная операция с балансом.')
    amount = _decimal(amount, '0.00000001', '9999999999.99999999')
    column = 'balance_usdt' if currency == 'USDT' else 'balance'
    async with _transaction() as cur:
        await cur.execute(f'SELECT {column} AS balance FROM users WHERE id = %s FOR UPDATE', (user_id,))
        user = await cur.fetchone()
        if not user:
            raise ValueError('Пользователь не найден.')
        before = Decimal(str(user['balance']))
        after = before + amount if mode == 'add' else amount
        if not Decimal('0') <= after <= Decimal('9999999999.99999999'):
            raise ValueError('Итоговый баланс не может быть отрицательным или превышать лимит.')
        await cur.execute(f'UPDATE users SET {column} = %s WHERE id = %s', (after, user_id))
        await _record(cur, admin_id, 'balance_' + mode, 'user', user_id, {
            'currency': currency, 'before': str(before), 'after': str(after),
        })


async def change_account_price(admin_id, account_id, price):
    price = _decimal(price, '0.01', '99999999.99')
    if price <= 0:
        raise ValueError('Цена должна быть больше нуля.')
    async with _transaction() as cur:
        await cur.execute('SELECT price FROM accounts WHERE id = %s FOR UPDATE', (account_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        await cur.execute('UPDATE accounts SET compare_price = CASE WHEN price>%s THEN GREATEST(price,COALESCE(compare_price,0)) WHEN compare_price>%s THEN compare_price ELSE NULL END,price=%s WHERE id=%s', (price, price, price, account_id))
        await _record(cur, admin_id, 'account_price', 'account', account_id, {
            'before': str(row['price']), 'after': str(price),
        })
        return True


async def change_category_price(admin_id, slug, price):
    price = _decimal(price, '0.01', '99999999.99')
    if price <= 0:
        raise ValueError('Цена должна быть больше нуля.')
    async with _transaction() as cur:
        await cur.execute('SELECT price FROM accounts WHERE country = %s FOR UPDATE', (slug,))
        rows = await cur.fetchall()
        if not rows:
            return 0
        prices = sorted({str(row['price']) for row in rows})
        await cur.execute('UPDATE accounts SET compare_price = CASE WHEN price>%s THEN GREATEST(price,COALESCE(compare_price,0)) WHEN compare_price>%s THEN compare_price ELSE NULL END,price=%s WHERE country=%s', (price, price, price, slug))
        updated = cur.rowcount
        await _record(cur, admin_id, 'category_price', 'category', slug, {
            'before': prices[:20], 'distinct_prices': len(prices),
            'after': str(price), 'matched': len(rows), 'updated': updated,
        })
        return updated


async def remove_account(admin_id, account_id):
    async with _transaction() as cur:
        await cur.execute('SELECT country, price, status FROM accounts WHERE id = %s FOR UPDATE', (account_id,))
        row = await cur.fetchone()
        if row is None:
            return False
        # Retain existing deletion semantics, without storing sessions or passwords.
        try:
            await cur.execute('DELETE FROM purchases WHERE account_id = %s', (account_id,))
        except aiomysql.IntegrityError as exc:
            if exc.args[0] == 1451:
                raise ValueError('Нельзя удалить товар: история поддержки и возвратов должна сохраниться.') from exc
            raise
        await cur.execute('DELETE FROM accounts WHERE id = %s', (account_id,))
        await _record(cur, admin_id, 'account_delete', 'account', account_id, {
            'category': row['country'], 'price': str(row['price']), 'status': row['status'],
        })
        return True


async def find_user(query):
    query = query.strip().lstrip('@')
    if not query or len(query) > 64:
        return None
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            if query.isascii() and query.isdigit():
                if not 0 < int(query) <= 9223372036854775807:
                    return None
                condition, value = 'id = %s', int(query)
            else:
                condition, value = 'LOWER(username) = LOWER(%s)', query
            await cur.execute(
                f'SELECT id, username, balance, balance_usdt FROM users WHERE {condition} LIMIT 1',
                (value,),
            )
            return await cur.fetchone()


async def user_orders(user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT id, date, account_id FROM purchases WHERE user_id = %s ORDER BY id DESC LIMIT 5',
                (user_id,),
            )
            return await cur.fetchall()


async def find_order(order_id):
    if not 0 < order_id <= 2147483647:
        return None
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT p.id, p.user_id, p.account_id, p.date, p.currency, u.username, "
                "a.country, p.status, p.paid_amount, p.referrer_id, p.referral_bonus, t.id AS ticket_id, t.status AS ticket_status, r.reason AS refund_reason, r.amount AS refunded_amount, (a.data = '✅ Сессия удалена (Покупка завершена)') AS completed "
                "FROM purchases p LEFT JOIN users u ON u.id = p.user_id "
                "LEFT JOIN accounts a ON a.id = p.account_id "
                "LEFT JOIN support_tickets t ON t.purchase_id = p.id "
                "LEFT JOIN order_refunds r ON r.purchase_id = p.id WHERE p.id = %s",
                (order_id,),
            )
            return await cur.fetchone()


async def audit_entries(before_id=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT id, admin_id, action, target_type, target_id, details, created_at '
                'FROM admin_audit_log ' + ('WHERE id < %s ' if before_id else '') +
                'ORDER BY id DESC LIMIT 6',
                (before_id,) if before_id else (),
            )
            return await cur.fetchall()
