"""Audited shop revocation and explicit Telegram authorization cleanup."""
from utils.i18n import tr
from database.admin_tools import _transaction, _record


def customer_view(row):
    if row and row.get('access_revoked_at'):
        row = dict(row)
        for key in ('data', 'password', 'code'):
            row[key] = None
    return row


async def revoke(admin, purchase, reason):
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
        raise ValueError(tr('Причина: 3–500 символов.'))
    async with _transaction() as cur:
        await cur.execute('SELECT id,status,access_revoked_at FROM purchases WHERE id=%s FOR UPDATE', (purchase,))
        row = await cur.fetchone()
        if not row or row['status'] not in {'issued', 'completed'}:
            raise ValueError(tr('Заказ недоступен.'))
        if row.get('access_revoked_at'):
            return False
        await cur.execute('UPDATE purchases SET access_revoked_at=UTC_TIMESTAMP(),access_revoked_by=%s,access_revoked_reason=%s WHERE id=%s', (admin, reason.strip(), purchase))
        await _record(cur, admin, 'order_access_revoked', 'order', purchase, {'reason': reason.strip()})
        return True


async def terminate(admin, purchase):
    # Serialize cleanup against completion, refunds and replacement. Telegram calls
    # have a bounded timeout; shop revocation persists even if Telegram rejects it.
    from services.session_audit import clean_other_sessions
    async with _transaction() as cur:
        await cur.execute('SELECT account_id,status,access_revoked_at FROM purchases WHERE id=%s FOR UPDATE', (purchase,))
        order = await cur.fetchone()
        if not order or not order.get('access_revoked_at') or order['status'] != 'issued':
            raise ValueError(tr('Сначала отзовите доступ через магазин. Нужен выданный заказ с активной сессией.'))
        await cur.execute('SELECT data,telegram_user_id FROM accounts WHERE id=%s FOR UPDATE', (order['account_id'],))
        account = await cur.fetchone()
        if not account or not account.get('telegram_user_id') or not account.get('data') or account['data'].startswith('✅'):
            raise ValueError(tr('Сессия магазина недоступна. Завершить сеансы Telegram невозможно.'))
        result = await clean_other_sessions(account['data'], account['telegram_user_id'])
        await _record(cur, admin, 'order_telegram_sessions', 'order', purchase, result)
        return result
