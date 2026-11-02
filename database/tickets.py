"""Transactional support conversation storage. User operations enforce ownership."""
import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction, _record

MAX_MESSAGE_LENGTH = 500


def validate_body(body):
    body = body.strip()
    if not body or len(body) > MAX_MESSAGE_LENGTH:
        raise ValueError('Введите сообщение от 1 до 500 символов.')
    return body


async def _message(cur, ticket_id, author_id, role, body):
    await cur.execute(
        'INSERT INTO support_messages (ticket_id, author_id, author_role, body, created_at) '
        'VALUES (%s, %s, %s, %s, UTC_TIMESTAMP())',
        (ticket_id, author_id, role, body),
    )


async def ticket_for_order(purchase_id, user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT id FROM support_tickets WHERE purchase_id = %s AND user_id = %s',
                (purchase_id, user_id),
            )
            return await cur.fetchone()


async def create_ticket(user_id, purchase_id, body):
    body = validate_body(body)
    async with _transaction() as cur:
        # Serializes concurrent submissions for a single order.
        await cur.execute('SELECT id FROM purchases WHERE id = %s AND user_id = %s FOR UPDATE', (purchase_id, user_id))
        if await cur.fetchone() is None:
            raise ValueError('Покупка не найдена.')
        await cur.execute('SELECT id FROM support_tickets WHERE purchase_id = %s FOR UPDATE', (purchase_id,))
        ticket = await cur.fetchone()
        if ticket:
            ticket_id = ticket['id']
            await cur.execute("UPDATE support_tickets SET status = 'open', updated_at = UTC_TIMESTAMP() WHERE id = %s", (ticket_id,))
        else:
            await cur.execute(
                'INSERT INTO support_tickets (purchase_id, user_id, status, created_at, updated_at) '
                "VALUES (%s, %s, 'open', UTC_TIMESTAMP(), UTC_TIMESTAMP())",
                (purchase_id, user_id),
            )
            ticket_id = cur.lastrowid
        await _message(cur, ticket_id, user_id, 'user', body)
        return ticket_id


async def get_ticket(ticket_id, user_id=None):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT id, purchase_id, user_id, status, created_at, updated_at FROM support_tickets '
                'WHERE id = %s' + (' AND user_id = %s' if user_id is not None else ''),
                (ticket_id, user_id) if user_id is not None else (ticket_id,),
            )
            return await cur.fetchone()


async def history(ticket_id, user_id=None, before_id=0):
    # Join and filter ownership in the same query, not just in the view handler.
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            conditions, params = ['m.ticket_id = %s'], [ticket_id]
            if user_id is not None:
                conditions.append('t.user_id = %s')
                params.append(user_id)
            if before_id:
                conditions.append('m.id < %s')
                params.append(before_id)
            await cur.execute(
                'SELECT m.id, m.author_role, m.body, m.created_at FROM support_messages m '
                'JOIN support_tickets t ON t.id = m.ticket_id WHERE ' + ' AND '.join(conditions) +
                ' ORDER BY m.id DESC LIMIT 2', tuple(params),
            )
            return await cur.fetchall()


async def inbox(user_id=None, closed=False, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            conditions, params = [], []
            if user_id is not None:
                conditions.append('user_id = %s')
                params.append(user_id)
            else:
                conditions.append("status = 'closed'" if closed else "status <> 'closed'")
            params.append(max(0, min(page, 10000)) * 5)
            await cur.execute(
                'SELECT id, purchase_id, user_id, status FROM support_tickets WHERE ' +
                ' AND '.join(conditions) + ' ORDER BY id DESC LIMIT 6 OFFSET %s', tuple(params),
            )
            return await cur.fetchall()


async def reply(ticket_id, author_id, body, admin=False):
    body = validate_body(body)
    async with _transaction() as cur:
        await cur.execute(
            'SELECT id, user_id FROM support_tickets WHERE id = %s' +
            ('' if admin else ' AND user_id = %s') + ' FOR UPDATE',
            (ticket_id,) if admin else (ticket_id, author_id),
        )
        ticket = await cur.fetchone()
        if ticket is None:
            raise ValueError('Обращение не найдено.')
        await _message(cur, ticket_id, author_id, 'admin' if admin else 'user', body)
        await cur.execute('UPDATE support_tickets SET status = %s, updated_at = UTC_TIMESTAMP() WHERE id = %s',
                          ('waiting_user' if admin else 'open', ticket_id))
        if admin:
            await _record(cur, author_id, 'ticket_reply', 'ticket', ticket_id, {'recipient_id': ticket['user_id']})
        return ticket['user_id']


async def close_ticket(ticket_id, admin_id):
    async with _transaction() as cur:
        await cur.execute('SELECT user_id, status FROM support_tickets WHERE id = %s FOR UPDATE', (ticket_id,))
        ticket = await cur.fetchone()
        if ticket is None:
            raise ValueError('Обращение не найдено.')
        if ticket['status'] == 'closed':
            return None
        await cur.execute("UPDATE support_tickets SET status = 'closed', updated_at = UTC_TIMESTAMP() WHERE id = %s", (ticket_id,))
        await _message(cur, ticket_id, admin_id, 'system', 'Обращение закрыто поддержкой.')
        await _record(cur, admin_id, 'ticket_close', 'ticket', ticket_id, {'before': ticket['status'], 'after': 'closed'})
        return ticket['user_id']
