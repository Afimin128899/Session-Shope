"""Purchase assurances and verified-owner reviews, shared by bot and Mini App."""
from utils.i18n import tr
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
import aiomysql
from database.db import _get_pool
from database.admin_tools import _transaction, _record

POLICY = 'Гарантия на проблемы со входом в пределах указанного срока. Опишите проблему в обращении по заказу; решение принимает поддержка после проверки.'


async def init_schema(cur, database):
    from database.direct_chat import init_schema as init_direct_chat
    await init_direct_chat(cur)
    columns = {
        'accounts': [('warranty_hours','INT DEFAULT NULL'), ('registration_date','DATE DEFAULT NULL'),
                     ('features_note','VARCHAR(500) DEFAULT NULL'), ('is_premium','TINYINT DEFAULT NULL'),
                     ('attributes_checked_at','DATETIME DEFAULT NULL')],
        'purchases': [('warranty_hours','INT DEFAULT NULL'), ('warranty_until','DATETIME DEFAULT NULL'),
                      ('warranty_policy','VARCHAR(500) DEFAULT NULL'), ('attributes_snapshot','TEXT DEFAULT NULL')],
        'promocodes': [('kind',"VARCHAR(16) NOT NULL DEFAULT 'balance'")],
        'support_tickets': [('warranty_claimed_at','DATETIME DEFAULT NULL')],
    }
    for table, entries in columns.items():
        for column, definition in entries:
            await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s',(database,table,column))
            if not await cur.fetchone():
                await cur.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    await cur.execute('''CREATE TABLE IF NOT EXISTS purchase_reviews (
        purchase_id INT PRIMARY KEY, user_id BIGINT NOT NULL,
        rating TINYINT NOT NULL, body VARCHAR(500) NOT NULL,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        FOREIGN KEY(purchase_id) REFERENCES purchases(id) ON DELETE RESTRICT,
        FOREIGN KEY(user_id) REFERENCES users(id), KEY review_time(updated_at)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS operational_incidents (
        incident_key VARCHAR(64) PRIMARY KEY, active TINYINT NOT NULL,
        first_seen DATETIME NOT NULL, last_seen DATETIME NOT NULL,
        failures INT NOT NULL DEFAULT 1
    ) ENGINE=InnoDB''')

    from database.activity import init_schema as init_activity
    await init_activity(cur)
    from database.expansion import init_schema as expand_schema
    await expand_schema(cur)
    from database.imports import init_schema as import_schema
    await import_schema(cur)
    from database.spam_checks import init_schema as spam_schema
    await spam_schema(cur, database)
    from database.shop_control import init_schema as control_schema
    await control_schema(cur, database)


async def snapshot(cur, purchase_id):
    # Called with the inventory row locked and in the purchase transaction.
    await cur.execute('''UPDATE purchases p JOIN accounts a ON a.id=p.account_id
        SET p.warranty_hours=a.warranty_hours,
            p.warranty_until=CASE WHEN a.warranty_hours>0 THEN DATE_ADD(UTC_TIMESTAMP(),INTERVAL a.warranty_hours HOUR) ELSE NULL END,
            p.warranty_policy=%s,
            p.attributes_snapshot=JSON_OBJECT('country',a.country,'registration_date',a.registration_date,
                'is_premium',a.is_premium,'features_note',a.features_note,'checked_at',a.attributes_checked_at,
                'spam_status',a.spam_status,'spam_checked_at',a.spam_checked_at,
                'two_fa',CASE WHEN a.password IS NOT NULL AND a.password NOT IN ('','-') THEN 'Пароль указан' ELSE 'Пароль не указан' END)
        WHERE p.id=%s''',(POLICY,purchase_id))


def warranty(row):
    until = row.get('warranty_until')
    if isinstance(until, str):
        until = datetime.fromisoformat(until)
    hours = row.get('warranty_hours')
    active = bool(until and until.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc) and (row.get('status') != 'refunded'))
    return {'hours': hours, 'until': until.replace(tzinfo=timezone.utc).isoformat() if until else None, 'active': active, 'policy': tr(POLICY) if row.get('warranty_policy') == POLICY else row.get('warranty_policy') or '', 'label': tr('Возврат оформлен') if row.get('status') == 'refunded' else tr('Срок не сохранён') if hours is None else tr('Без гарантии') if hours == 0 else tr('Действует') if active else tr('Срок истёк')}


def characteristics(row):
    from database.spam_checks import public as spam_status
    registered = row.get('registration_date')
    return {'registration_date': str(registered) if registered else None, 'is_premium': None if row.get('is_premium') is None else bool(row['is_premium']), 'note': row.get('features_note') or '', 'checked_at': str(row['attributes_checked_at']) if row.get('attributes_checked_at') else None, 'two_fa': tr('Пароль указан') if row.get('password') not in (None, '', '-') else tr('Пароль не указан'), 'warranty_hours': row.get('warranty_hours'), 'spam_check': spam_status(row)}


async def edit_characteristics(admin_id, account_id, *, hours, registered, premium, note):
    if type(hours) is not int or not 0 <= hours <= 8760 or (premium is not None and type(premium) is not bool) or (len(note) > 500):
        raise ValueError(tr('Гарантия: 0–8760 часов. Описание: до 500 символов.'))
    if registered:
        registered = date.fromisoformat(registered)
        if not date(2013, 8, 1) <= registered <= datetime.now(ZoneInfo('Europe/Moscow')).date():
            raise ValueError(tr('Проверьте дату регистрации.'))
    async with _transaction() as cur:
        await cur.execute('SELECT id FROM accounts WHERE id=%s FOR UPDATE', (account_id,))
        if not await cur.fetchone():
            raise ValueError(tr('Аккаунт не найден.'))
        await cur.execute('UPDATE accounts SET warranty_hours=%s,registration_date=%s,is_premium=%s,features_note=%s,attributes_checked_at=UTC_TIMESTAMP() WHERE id=%s', (hours, registered, premium, note.strip(), account_id))
        await _record(cur, admin_id, 'account_features', 'account', account_id, {'warranty_hours': hours, 'registration_date': str(registered) if registered else None, 'is_premium': premium})


async def save_review(user_id, purchase_id, rating, body):
    if type(rating) is not int or not 1 <= rating <= 5 or (not isinstance(body, str)) or (not 1 <= len(body.strip()) <= 500):
        raise ValueError(tr('Оценка: 1–5. Отзыв: 1–500 символов.'))
    body = body.strip()
    async with _transaction() as cur:
        await cur.execute('SELECT p.id,p.status,a.number,a.password FROM purchases p JOIN accounts a ON a.id=p.account_id WHERE p.id=%s AND p.user_id=%s FOR UPDATE', (purchase_id, user_id))
        row = await cur.fetchone()
        if not row:
            raise ValueError(tr('Покупка не найдена.'))
        password = row.get('password')
        digits = ''.join((c for c in body if c.isdigit()))
        phone = ''.join((c for c in row.get('number') or '' if c.isdigit()))
        if password and len(password) >= 4 and (password in body) or (len(phone) >= 8 and phone in digits):
            raise ValueError(tr('Не публикуйте номер или пароль аккаунта в отзыве.'))
        await cur.execute('INSERT INTO purchase_reviews(purchase_id,user_id,rating,body,created_at,updated_at)\n            VALUES(%s,%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())\n            ON DUPLICATE KEY UPDATE rating=VALUES(rating),body=VALUES(body),updated_at=UTC_TIMESTAMP()', (purchase_id, user_id, rating, body))


async def my_review(user_id,purchase_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT rating,body FROM purchase_reviews WHERE purchase_id=%s AND user_id=%s',(purchase_id,user_id))
            return await cur.fetchone()


async def reviews(page=0,per_page=20):
    per_page=max(1,min(per_page,20))
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT COUNT(*) AS count,ROUND(AVG(r.rating),2) AS average FROM purchase_reviews r JOIN purchases p ON p.id=r.purchase_id")
            summary=await cur.fetchone()
            # Public reviews intentionally contain neither Telegram IDs nor order/account IDs.
            await cur.execute("SELECT r.rating,r.body,r.updated_at FROM purchase_reviews r JOIN purchases p ON p.id=r.purchase_id ORDER BY r.updated_at DESC,r.purchase_id DESC LIMIT %s OFFSET %s",(per_page+1,page*per_page))
            rows=list(await cur.fetchall())
            return {'items':rows[:per_page],'has_more':len(rows)>per_page,**summary}
