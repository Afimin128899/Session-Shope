"""Shared marketplace state. Transactions lock stock before user rows."""
from uuid import uuid4
import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction

MAX_CART = 20


async def add_to_cart(user_id, account_id):
    async with _transaction() as cur:
        await cur.execute("SELECT a.id,a.spam_lease_until>UTC_TIMESTAMP() AS spam_running FROM accounts a JOIN categories c ON c.slug=a.country WHERE a.id=%s AND a.status='available' AND c.is_active=1 FOR UPDATE", (account_id,))
        account = await cur.fetchone()
        if not account:
            raise ValueError('Аккаунт больше недоступен.')
        if account.get('spam_running'):
            raise ValueError('Аккаунт проверяется через @SpamBot. Повторите через минуту.')
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not await cur.fetchone():
            raise ValueError('Покупатель не найден.')
        await cur.execute('SELECT account_id FROM shopping_cart WHERE user_id=%s FOR UPDATE', (user_id,))
        cart_ids = {row['account_id'] for row in await cur.fetchall()}
        if account_id not in cart_ids and len(cart_ids) >= MAX_CART:
            raise ValueError('В корзине может быть не больше 20 аккаунтов.')
        await cur.execute('SELECT user_id, expires_at > UTC_TIMESTAMP() AS active FROM account_reservations WHERE account_id=%s FOR UPDATE', (account_id,))
        hold = await cur.fetchone()
        if hold and hold['active'] and hold['user_id'] != user_id:
            raise ValueError('Аккаунт временно зарезервирован другим покупателем.')
        await cur.execute('INSERT IGNORE INTO shopping_cart (user_id,account_id,created_at) VALUES (%s,%s,UTC_TIMESTAMP())', (user_id, account_id))
        # Repeated clicks and page refreshes cannot extend a live reservation.
        if not hold or not hold['active']:
            await cur.execute('INSERT INTO account_reservations (account_id,user_id,expires_at) VALUES (%s,%s,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 5 MINUTE)) ON DUPLICATE KEY UPDATE user_id=VALUES(user_id),expires_at=VALUES(expires_at)', (account_id, user_id))


async def remove_from_cart(user_id, account_id):
    async with _transaction() as cur:
        await cur.execute('SELECT id FROM accounts WHERE id=%s FOR UPDATE', (account_id,))
        await cur.execute('DELETE FROM shopping_cart WHERE user_id=%s AND account_id=%s', (user_id, account_id))
        await cur.execute('DELETE FROM account_reservations WHERE account_id=%s AND user_id=%s', (account_id, user_id))


async def favorite(user_id, account_id, enabled):
    async with _transaction() as cur:
        if not enabled:
            await cur.execute('DELETE FROM account_favorites WHERE user_id=%s AND account_id=%s', (user_id, account_id))
            return
        await cur.execute("SELECT a.price FROM accounts a JOIN categories c ON c.slug=a.country WHERE a.id=%s AND a.status='available' AND c.is_active=1 FOR UPDATE", (account_id,))
        account = await cur.fetchone()
        if not account:
            raise ValueError('Аккаунт больше недоступен.')
        await cur.execute('INSERT IGNORE INTO account_favorites (user_id,account_id,token,last_price,next_attempt_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP())', (user_id, account_id, uuid4().hex, account['price']))


async def register_invoice(provider, invoice_id, user_id, amount):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('INSERT INTO payment_invoices (provider,invoice_id,user_id,amount_rub,created_at,expires_at,next_check_at) VALUES (%s,%s,%s,%s,UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 1 HOUR),UTC_TIMESTAMP())', (provider, str(invoice_id), user_id, amount))


async def invoice(provider, invoice_id, user_id=None):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT * FROM payment_invoices WHERE provider=%s AND invoice_id=%s' + (' AND user_id=%s' if user_id is not None else ''), (provider, str(invoice_id), user_id) if user_id is not None else (provider, str(invoice_id)))
            return await cur.fetchone()


async def pending_invoices():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM payment_invoices WHERE status='pending' AND provider<>'stars' AND next_check_at<=UTC_TIMESTAMP() ORDER BY next_check_at LIMIT 25")
            return await cur.fetchall()


async def lease_invoice(provider, invoice_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE payment_invoices SET next_check_at=DATE_ADD(UTC_TIMESTAMP(),INTERVAL LEAST(3600,15*POW(2,LEAST(attempts,8))) SECOND),attempts=attempts+1 WHERE provider=%s AND invoice_id=%s AND status='pending' AND next_check_at<=UTC_TIMESTAMP()", (provider, str(invoice_id)))
            return cur.rowcount > 0


async def finish_invoice(provider, invoice_id, status, credited=None):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('UPDATE payment_invoices SET status=%s,credited_amount=COALESCE(%s,credited_amount) WHERE provider=%s AND invoice_id=%s', (status, credited, provider, str(invoice_id)))
