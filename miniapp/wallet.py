"""Owner-scoped, read-only wallet projections; never a source for settlement."""
import aiomysql
from database.db import _get_pool

DEPOSIT_METHODS = ('crypto_pay', 'xrocket_pay', 'lave_pay', 'laveshka_pay', 'platega_pay', 'stars_pay', 'heleket_pay')


async def summary(user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            placeholders = ','.join(['%s'] * len(DEPOSIT_METHODS))
            await cur.execute(
                "SELECT COALESCE(SUM(amount),0) AS deposited FROM payment_logs "
                "WHERE user_id=%s AND currency='RUB' AND amount>0 AND method IN (" + placeholders + ')',
                (user_id, *DEPOSIT_METHODS),
            )
            deposited = (await cur.fetchone())['deposited']
            await cur.execute(
                "SELECT COALESCE(SUM(CASE WHEN currency='RUB' AND status<>'refunded' THEN paid_amount ELSE 0 END),0) AS spent,"
                "COUNT(*) AS purchase_count,COALESCE(SUM(paid_amount IS NULL),0) AS missing_amounts "
                'FROM purchases WHERE user_id=%s', (user_id,),
            )
            purchases = await cur.fetchone()
    return {'deposited': str(deposited), 'spent': str(purchases['spent']),
            'purchase_count': purchases['purchase_count'], 'missing_amounts': int(purchases['missing_amounts'])}
