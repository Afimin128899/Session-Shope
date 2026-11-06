"""One welcome credit for a newly registered visitor, in the signup transaction."""
from decimal import Decimal

from database.db import _get_pool
from database.admin_tools import _record

AMOUNT = Decimal('4.00')


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS welcome_bonuses (
        user_id BIGINT PRIMARY KEY, amount DECIMAL(18,8) NOT NULL,
        created_at DATETIME NOT NULL,
        FOREIGN KEY(user_id) REFERENCES users(id)
    ) ENGINE=InnoDB''')


async def credit_new_user(cur, user_id):
    """Caller has just inserted the user and owns its lock. Never backfill old users."""
    await cur.execute('INSERT INTO welcome_bonuses(user_id,amount,created_at) VALUES(%s,%s,UTC_TIMESTAMP())', (user_id, AMOUNT))
    await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s', (AMOUNT, user_id))
    await _record(cur, 0, 'welcome_bonus', 'user', user_id, {'amount': str(AMOUNT), 'currency': 'RUB'})
    return AMOUNT


async def received(user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('SELECT amount FROM welcome_bonuses WHERE user_id=%s', (user_id,))
            row = await cur.fetchone()
            return Decimal(str(row[0])) if row else Decimal(0)
