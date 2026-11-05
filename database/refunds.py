"""One full balance refund per order, together with stock and commission reversal."""
from utils.i18n import tr
from decimal import Decimal

from database.admin_tools import _transaction, _record
from database.db import _get_pool
import aiomysql


async def refund_order(admin_id, purchase_id, reason):
    reason = reason.strip()
    if not 3 <= len(reason) <= 500:
        raise ValueError(tr('Укажите причину от 3 до 500 символов.'))
    async with _transaction() as cur:
        await cur.execute('SELECT id, user_id, account_id, paid_amount, currency, status, referrer_id, referral_bonus FROM purchases WHERE id = %s FOR UPDATE', (purchase_id,))
        order = await cur.fetchone()
        if order is None:
            raise ValueError(tr('Заказ не найден.'))
        if order['status'] == 'refunded':
            return None
        if order['status'] not in {'issued', 'completed'}:
            raise ValueError(tr('Возврат доступен только для оплаченного и выданного заказа.'))
        if order['paid_amount'] is None:
            raise ValueError(tr('У старого заказа не сохранена оплаченная сумма. Автоматический возврат невозможен.'))
        amount = Decimal(str(order['paid_amount']))
        currency = order['currency']
        if currency not in {'RUB', 'USDT', 'TON'} or not amount.is_finite() or amount < 0:
            raise ValueError(tr('Не удалось подтвердить сумму и валюту заказа.'))
        bonus = Decimal(str(order['referral_bonus'] or 0))
        if not bonus.is_finite() or bonus < 0:
            raise ValueError(tr('Некорректный реферальный бонус заказа.'))
        referrer = order['referrer_id']
        if referrer is None and bonus:
            raise ValueError(tr('Не найден получатель реферального бонуса.'))
        balance_col = 'balance_usdt' if currency == 'USDT' else 'balance'
        users = sorted({order['user_id'], referrer} - {None})
        await cur.execute(f'SELECT id, {balance_col} AS balance FROM users WHERE id IN (' + ','.join(['%s'] * len(users)) + ') ORDER BY id FOR UPDATE', tuple(users))
        balances = {row['id']: Decimal(str(row['balance'])) for row in await cur.fetchall()}
        if any((user not in balances for user in users)):
            raise ValueError(tr('Покупатель или получатель бонуса не найден.'))
        after = dict(balances)
        after[order['user_id']] += amount
        if referrer is not None:
            after[referrer] -= bonus
        if any((abs(value) > Decimal('9999999999.99999999') for value in after.values())):
            raise ValueError(tr('Возврат превышает допустимый размер баланса.'))
        await cur.execute('INSERT INTO order_refunds (purchase_id, admin_id, user_id, amount, currency, reason, referral_reversed, legacy_referral, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())', (purchase_id, admin_id, order['user_id'], amount, currency, reason, bonus, order['referral_bonus'] is None))
        for user, value in after.items():
            await cur.execute(f'UPDATE users SET {balance_col} = %s WHERE id = %s', (value, user))
        from database.referrals import mark_purchase_reversed
        await mark_purchase_reversed(cur, purchase_id)
        await cur.execute("UPDATE purchases SET status = 'refunded' WHERE id = %s", (purchase_id,))
        await cur.execute("UPDATE accounts SET status = 'refunded', data = '', password = NULL WHERE id = %s", (order['account_id'],))
        await cur.execute('SELECT id FROM support_tickets WHERE purchase_id = %s FOR UPDATE', (purchase_id,))
        ticket = await cur.fetchone()
        if ticket:
            await cur.execute("UPDATE support_tickets SET status = 'closed', updated_at = UTC_TIMESTAMP() WHERE id = %s", (ticket['id'],))
            await cur.execute("INSERT INTO support_messages (ticket_id, author_id, author_role, body, created_at) VALUES (%s,%s,'system',%s,UTC_TIMESTAMP())", (ticket['id'], admin_id, f'Заказ #{purchase_id}: {amount} {currency} возвращено на баланс бота.'))
        await _record(cur, admin_id, 'order_refund', 'order', purchase_id, {'amount': str(amount), 'currency': currency, 'user_id': order['user_id'], 'referral_reversed': str(bonus), 'legacy_referral': order['referral_bonus'] is None})
        return {'id': purchase_id, 'user_id': order['user_id'], 'amount': str(amount), 'currency': currency}


async def get_refund(purchase_id, user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT amount, currency, reason, created_at FROM order_refunds WHERE purchase_id = %s AND user_id = %s', (purchase_id, user_id))
            return await cur.fetchone()
