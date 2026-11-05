"""Bounded bot lists: public inventory fields only, shared pricing and owner checks."""
from utils.i18n import tr
from decimal import Decimal

import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction
from miniapp.storage import pricing, money

PAGE_SIZE = 8
DELETED_SESSION = '✅ Сессия удалена (Покупка завершена)'


def bounded_page(page, count):
    return max(0, min(page, max(0, (count - 1) // PAGE_SIZE)))


async def categories(user_id, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT c.slug,c.name,c.emoji,COUNT(a.id) AS count,MIN(a.price) AS min_price "
                "FROM categories c JOIN accounts a ON a.country=c.slug AND a.status='available' "
                "WHERE c.is_active=1 AND NOT EXISTS(SELECT 1 FROM account_reservations r "
                "WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s) "
                "GROUP BY c.slug,c.name,c.emoji,c.sort_order ORDER BY c.sort_order,c.name", (user_id,),
            )
            rows = list(await cur.fetchall())
            _, discount, _ = await pricing(cur, user_id)
            page = bounded_page(page, len(rows))
            selected = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]
            for row in selected:
                row['min_price'] = money(Decimal(str(row['min_price'])) * (1 - discount / 100))
            return selected, len(rows), page


async def products(user_id, slug, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            where = ("FROM accounts a JOIN categories c ON c.slug=a.country "
                     "WHERE a.country=%s AND a.status='available' AND c.is_active=1 "
                     "AND NOT EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id "
                     "AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s)")
            await cur.execute('SELECT COUNT(*) AS n ' + where, (slug, user_id))
            count = (await cur.fetchone())['n']
            page = bounded_page(page, count)
            await cur.execute('SELECT a.id,a.number,a.price,a.spam_status,a.spam_checked_at,a.spam_lease_until ' + where + ' ORDER BY a.id DESC LIMIT %s OFFSET %s',
                              (slug, user_id, PAGE_SIZE, page * PAGE_SIZE))
            rows = list(await cur.fetchall())
            _, discount, _ = await pricing(cur, user_id)
            for row in rows:
                row['price'] = money(Decimal(str(row['price'])) * (1 - discount / 100))
            return rows, count, page


async def product(user_id, account_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT a.id,a.country,a.number,a.price,a.telegram_user_id,a.warranty_hours,"
                "a.registration_date,a.is_premium,a.spam_status,a.spam_checked_at,a.spam_lease_until,c.name,c.emoji FROM accounts a "
                "JOIN categories c ON c.slug=a.country WHERE a.id=%s AND a.status='available' "
                "AND c.is_active=1 AND NOT EXISTS(SELECT 1 FROM account_reservations r "
                "WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s)",
                (account_id, user_id),
            )
            row = await cur.fetchone()
            if row:
                _, discount, _ = await pricing(cur, user_id)
                row['price'] = money(Decimal(str(row['price'])) * (1 - discount / 100))
            return row


async def orders(user_id, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT COUNT(*) AS n FROM purchases WHERE user_id=%s', (user_id,))
            count = (await cur.fetchone())['n']
            page = bounded_page(page, count)
            await cur.execute(
                'SELECT p.id,p.date,p.status,p.paid_amount,p.currency,a.country,a.number,c.name,'
                't.status AS ticket_status FROM purchases p JOIN accounts a ON a.id=p.account_id '
                'LEFT JOIN categories c ON c.slug=a.country LEFT JOIN support_tickets t ON t.purchase_id=p.id '
                'WHERE p.user_id=%s ORDER BY p.id DESC LIMIT %s OFFSET %s',
                (user_id, PAGE_SIZE, page * PAGE_SIZE),
            )
            return list(await cur.fetchall()), count, page


async def complete_order(user_id, purchase_id):
    async with _transaction() as cur:
        await cur.execute('SELECT account_id,status FROM purchases WHERE id=%s AND user_id=%s FOR UPDATE', (purchase_id, user_id))
        row = await cur.fetchone()
        if not row or row['status'] not in {'issued', 'completed'}:
            raise ValueError(tr('Заказ недоступен или возвращён на баланс.'))
        if row['status'] == 'completed':
            return False
        await cur.execute('UPDATE accounts SET data=%s WHERE id=%s', (DELETED_SESSION, row['account_id']))
        await cur.execute("UPDATE purchases SET status='completed' WHERE id=%s", (purchase_id,))
        return True
