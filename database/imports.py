"""Expiring owner-bound import drafts and duplicate-safe atomic publication."""
from utils.i18n import tr
import hashlib
import json
import re
from decimal import Decimal
from uuid import uuid4
from database.admin_tools import _transaction,_record,_decimal
from database.db import _get_pool
import aiomysql


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS admin_web_actions (id CHAR(32) PRIMARY KEY,admin_id BIGINT NOT NULL,created_at DATETIME NOT NULL) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS import_batches (
        id CHAR(32) PRIMARY KEY,admin_id BIGINT NOT NULL,status VARCHAR(16) NOT NULL,
        created_at DATETIME NOT NULL,expires_at DATETIME NOT NULL,KEY import_expiry(expires_at)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS import_items (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,batch_id CHAR(32) NOT NULL,label VARCHAR(200) NOT NULL,
        state VARCHAR(16) NOT NULL,error VARCHAR(200) DEFAULT NULL,
        phone VARCHAR(64) DEFAULT NULL,telegram_id BIGINT DEFAULT NULL,premium TINYINT DEFAULT NULL,
        session_data TEXT DEFAULT NULL,fingerprint CHAR(64) DEFAULT NULL,account_id INT DEFAULT NULL,
        FOREIGN KEY(batch_id) REFERENCES import_batches(id) ON DELETE CASCADE,KEY import_batch(batch_id)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS inventory_identities (
        identity_key VARCHAR(80) PRIMARY KEY,account_id INT DEFAULT NULL,
        FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE SET NULL
    ) ENGINE=InnoDB''')


async def claim(cur, phone, telegram_id, session):
    from utils.commerce_policy import require_phone
    require_phone(phone)
    digits = re.sub('\\D', '', phone)
    fingerprint = hashlib.sha256(session.encode()).hexdigest()
    keys = ['phone:' + digits, 'session:' + fingerprint]
    if telegram_id:
        keys.append('tg:' + str(telegram_id))
    for key in sorted(keys):
        await cur.execute('INSERT IGNORE INTO inventory_identities(identity_key) VALUES(%s)', (key,))
        await cur.execute('SELECT account_id FROM inventory_identities WHERE identity_key=%s FOR UPDATE', (key,))
        row = await cur.fetchone()
        if row['account_id'] is not None:
            raise ValueError(tr('Этот аккаунт уже загружен.'))
    await cur.execute("SELECT id FROM accounts WHERE REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(number,'+',''),' ',''),'-',''),'(',''),')','')=%s OR (%s IS NOT NULL AND telegram_user_id=%s) OR data=%s LIMIT 1", (digits, telegram_id, telegram_id, session))
    if await cur.fetchone():
        raise ValueError(tr('Этот аккаунт уже есть в магазине.'))
    return keys


async def bind(cur,keys,account):
    for key in keys: await cur.execute('UPDATE inventory_identities SET account_id=%s WHERE identity_key=%s',(account,key))


async def create(admin):
    batch = uuid4().hex
    async with _transaction() as cur:
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (admin,))
        if not await cur.fetchone():
            raise ValueError(tr('Администратор не найден.'))
        await cur.execute("SELECT id FROM import_batches WHERE admin_id=%s AND status='checking' AND expires_at>UTC_TIMESTAMP()", (admin,))
        if await cur.fetchone():
            raise ValueError(tr('Уже идёт проверка архива. Дождитесь окончания или отмените её.'))
        await cur.execute("INSERT INTO import_batches VALUES(%s,%s,'checking',UTC_TIMESTAMP(),UTC_TIMESTAMP()+INTERVAL 1 HOUR)", (batch, admin))
    return batch


async def add_item(batch,label,state,*,error=None,phone=None,telegram_id=None,premium=None,session=None):
    async with _transaction() as cur:
        await cur.execute("SELECT id FROM import_batches WHERE id=%s AND status='checking' AND expires_at>UTC_TIMESTAMP() FOR UPDATE",(batch,))
        if not await cur.fetchone(): return
        await cur.execute('INSERT INTO import_items(batch_id,label,state,error,phone,telegram_id,premium,session_data,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                          (batch,label[:200],state,error,phone,telegram_id,premium,session,hashlib.sha256(session.encode()).hexdigest() if session else None))


async def finish(batch,status='ready'):
    async with _transaction() as cur:
        await cur.execute("UPDATE import_batches SET status=%s WHERE id=%s AND status='checking'",(status,batch))
        if status!='ready': await cur.execute('UPDATE import_items SET session_data=NULL WHERE batch_id=%s',(batch,))


async def preview(admin, batch):
    async with _transaction() as cur:
        await cur.execute('SELECT id,status,expires_at FROM import_batches WHERE id=%s AND admin_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (batch, admin))
        result = await cur.fetchone()
        if not result:
            raise ValueError(tr('Черновик не найден или срок истёк.'))
        await cur.execute('SELECT id,label,state,error,phone,telegram_id,premium,account_id FROM import_items WHERE batch_id=%s ORDER BY id', (batch,))
        result['items'] = list(await cur.fetchall())
        return result


async def commit(admin, batch, selections):
    if not isinstance(selections, list) or not 1 <= len(selections) <= 100:
        raise ValueError(tr('Выберите 1–100 строк.'))
    prepared = []
    seen = set()
    for item in selections:
        if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] in seen:
            raise ValueError(tr('Проверьте выбранные строки.'))
        seen.add(item['id'])
        price = _decimal(item.get('price'), '0.01', '10000.00')
        hours = item.get('warranty_hours', 24)
        category = item.get('category')
        password = item.get('password', '-')
        if price <= 0 or type(hours) is not int or (not 0 <= hours <= 8760) or (not isinstance(category, str)) or (len(category) > 64) or (not isinstance(password, str)) or (len(password) > 255):
            raise ValueError(tr('Проверьте цену, категорию и гарантию.'))
        prepared.append((item['id'], price, hours, category, password or '-'))
    async with _transaction() as cur:
        await cur.execute('SELECT status FROM import_batches WHERE id=%s AND admin_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (batch, admin))
        row = await cur.fetchone()
        if not row or row['status'] != 'ready':
            raise ValueError(tr('Черновик уже обработан или недоступен.'))
        ids = []
        for identity, price, hours, category, password in sorted(prepared):
            await cur.execute("SELECT * FROM import_items WHERE id=%s AND batch_id=%s AND state='ready' FOR UPDATE", (identity, batch))
            item = await cur.fetchone()
            if not item or not item['session_data']:
                raise ValueError(tr('Строка не готова к импорту.'))
            await cur.execute('SELECT slug FROM categories WHERE slug=%s AND is_active=1', (category,))
            if not await cur.fetchone():
                raise ValueError(tr('Категория отключена или не существует.'))
            from utils.commerce_policy import category as check_category
            await check_category(cur, category)
            keys = await claim(cur, item['phone'], item['telegram_id'], item['session_data'])
            await cur.execute("INSERT INTO accounts(country,code,number,password,price,data,telegram_user_id,warranty_hours,is_premium,attributes_checked_at)\n                VALUES(%s,'',%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())", (category, item['phone'], password, price, item['session_data'], item['telegram_id'], hours, item['premium']))
            account = cur.lastrowid
            ids.append(account)
            await bind(cur, keys, account)
            await cur.execute("UPDATE import_items SET state='imported',account_id=%s WHERE id=%s", (account, identity))
        await cur.execute("UPDATE import_batches SET status='committed' WHERE id=%s", (batch,))
        await cur.execute("UPDATE import_items SET state='discarded' WHERE batch_id=%s AND state='ready'", (batch,))
        await cur.execute('UPDATE import_items SET session_data=NULL WHERE batch_id=%s', (batch,))
        await _record(cur, admin, 'archive_import', 'batch', batch, {'count': len(ids), 'account_ids': ids})
        return ids


async def discard(admin, batch):
    async with _transaction() as cur:
        await cur.execute("SELECT id FROM import_batches WHERE id=%s AND admin_id=%s AND status<>'committed' FOR UPDATE", (batch, admin))
        if not await cur.fetchone():
            raise ValueError(tr('Черновик недоступен.'))
        await cur.execute("UPDATE import_batches SET status='discarded' WHERE id=%s", (batch,))
        await cur.execute('UPDATE import_items SET session_data=NULL WHERE batch_id=%s', (batch,))


async def cleanup():
    async with _transaction() as cur:
        await cur.execute("UPDATE import_batches SET status='expired' WHERE expires_at<=UTC_TIMESTAMP() AND status IN ('ready','checking')")
        await cur.execute("UPDATE import_items i JOIN import_batches b ON b.id=i.batch_id SET i.session_data=NULL WHERE b.status IN ('expired','discarded','failed')")
