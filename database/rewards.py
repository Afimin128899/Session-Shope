"""Deposit-backed promotional rewards; bonus credits never count as deposits."""
from utils.i18n import tr
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import secrets
import aiomysql
from database.admin_tools import _transaction, _record
from database.db import _get_pool

THRESHOLD=Decimal('50')
PERIOD=timedelta(days=3)


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS reward_claims (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT NOT NULL,amount DECIMAL(10,2) NOT NULL,
        created_at DATETIME NOT NULL,KEY reward_user(user_id,created_at),
        FOREIGN KEY(user_id) REFERENCES users(id)
    ) ENGINE=InnoDB''')


async def eligibility(cur,user_id,*,lock=False):
    now=datetime.now(timezone.utc).replace(tzinfo=None)
    await cur.execute('SELECT created_at FROM reward_claims WHERE user_id=%s ORDER BY id DESC LIMIT 1'+(' FOR UPDATE' if lock else ''),(user_id,))
    last=await cur.fetchone()
    next_at=last['created_at']+PERIOD if last else None
    await cur.execute("SELECT COALESCE(SUM(amount),0) AS total FROM payment_logs WHERE user_id=%s AND currency='RUB' AND method IN ('lave_pay','xrocket_pay','crypto_pay','platega_pay') AND amount>0 AND UNIX_TIMESTAMP(created_at)>%s",(user_id,int((now.replace(tzinfo=timezone.utc)-PERIOD).timestamp())))
    paid=Decimal(str((await cur.fetchone())['total']))
    await cur.execute('SELECT COALESCE(SUM(amount_rub),0) AS total FROM star_payments WHERE user_id=%s AND paid_seen=1 AND refunded_seen=0 AND created_at>DATE_SUB(UTC_TIMESTAMP(),INTERVAL 3 DAY)',(user_id,))
    paid+=Decimal(str((await cur.fetchone())['total']))
    return {'eligible':paid>=THRESHOLD and (next_at is None or next_at<=now), 'paid':str(paid),
            'minimum':'50.00','next_at':next_at.replace(tzinfo=timezone.utc).isoformat() if next_at and next_at>now else None}


async def status(user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            return await eligibility(cur,user_id)


async def claim(user_id):
    async with _transaction() as cur:
        await cur.execute('SELECT balance FROM users WHERE id=%s FOR UPDATE', (user_id,))
        user = await cur.fetchone()
        if not user:
            raise ValueError(tr('Профиль не найден. Отправьте /start.'))
        current = await eligibility(cur, user_id, lock=True)
        if not current['eligible']:
            raise ValueError(tr('Бонус доступен раз в 3 дня при подтверждённых пополнениях от 50 ₽ за последние 72 часа.'))
        amount = Decimal(secrets.randbelow(10) + 1)
        if Decimal(str(user['balance'])) + amount > Decimal('9999999999.99999999'):
            raise ValueError(tr('Достигнут лимит баланса.'))
        await cur.execute('INSERT INTO reward_claims(user_id,amount,created_at) VALUES(%s,%s,UTC_TIMESTAMP())', (user_id, amount))
        await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s', (amount, user_id))
        await _record(cur, 0, 'wheel_reward', 'user', user_id, {'amount': str(amount)})
        return {'amount': str(amount), 'balance': str(Decimal(str(user['balance'])) + amount)}
