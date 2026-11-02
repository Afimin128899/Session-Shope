"""Private history derived from authoritative finance rows and atomic promo events."""
from datetime import datetime, timezone
import aiomysql
from database.db import _get_pool

LABELS = {'purchase':'Покупка','payment':'Пополнение','refund':'Возврат',
          'balance_code':'Промокод на баланс','discount_code':'Промокод скидки'}


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS customer_events (
        id BIGINT AUTO_INCREMENT PRIMARY KEY, user_id BIGINT NOT NULL,
        kind VARCHAR(32) NOT NULL, reference VARCHAR(64) NOT NULL,
        amount DECIMAL(18,8) NOT NULL, currency VARCHAR(16) NOT NULL,
        created_at DATETIME NOT NULL,
        KEY customer_event_time(user_id,created_at),
        FOREIGN KEY(user_id) REFERENCES users(id)
    ) ENGINE=InnoDB''')


async def promo_event(cur,user_id,promo):
    kind='discount_code' if promo['kind']=='discount' else 'balance_code'
    await cur.execute('''INSERT INTO customer_events(user_id,kind,reference,amount,currency,created_at)
        VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP())''',
        (user_id,kind,promo['code'],promo['value'],'PCT' if promo['kind']=='discount' else 'RUB'))


async def history(user_id,page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('''SELECT * FROM (
                SELECT CONVERT(CONCAT('purchase:',id) USING utf8mb4) COLLATE utf8mb4_unicode_ci AS event_key,
                    _utf8mb4'purchase' COLLATE utf8mb4_unicode_ci AS kind,
                    CAST(id AS CHAR CHARACTER SET utf8mb4) COLLATE utf8mb4_unicode_ci AS reference,
                    paid_amount AS amount,CONVERT(currency USING utf8mb4) COLLATE utf8mb4_unicode_ci AS currency,
                    DATE_SUB(STR_TO_DATE(date,'%%Y-%%m-%%d %%H:%%i:%%s'),INTERVAL 3 HOUR) AS occurred_at
                    FROM purchases WHERE user_id=%s
                UNION ALL
                SELECT CONCAT('payment:',id),'payment',method,amount,currency,
                    DATE_ADD(CAST('1970-01-01' AS DATETIME),INTERVAL UNIX_TIMESTAMP(created_at) SECOND)
                    FROM payment_logs WHERE user_id=%s
                UNION ALL
                SELECT CONCAT('refund:',purchase_id),'refund',CAST(purchase_id AS CHAR),amount,currency,created_at
                    FROM order_refunds WHERE user_id=%s
                UNION ALL
                SELECT CONCAT('promo:',id),kind,reference,amount,currency,created_at
                    FROM customer_events WHERE user_id=%s
            ) events ORDER BY occurred_at DESC,event_key DESC LIMIT 21 OFFSET %s''',
            (user_id,user_id,user_id,user_id,max(0,min(page,1000))*20))
            rows=list(await cur.fetchall())
            for row in rows[:20]:
                row['label']=LABELS.get(row['kind'],'Операция')
                stamp=row['occurred_at']
                if isinstance(stamp,str):
                    try: stamp=datetime.fromisoformat(stamp)
                    except ValueError: stamp=None
                row['occurred_at']=stamp.replace(tzinfo=timezone.utc).isoformat() if stamp else None
            return {'items':rows[:20],'has_more':len(rows)>20,
                    'note':'История промокодов сохраняется с версии 4.1. Пополнения указаны без бонусов. Старые даты без точного времени не восстанавливаются.'}
