"""Inventory operations, stock alerts and controlled warranty replacement."""
from decimal import Decimal
from database.admin_tools import _transaction, _record
from database.db import _get_pool
import aiomysql


async def init_schema(cur):
    for key,value in [('wholesale_min_total','500'),('wholesale_pct','15'),('refund_approval_threshold','600')]:
        await cur.execute('INSERT IGNORE INTO settings(`key`,`value`) VALUES(%s,%s)',(key,value))
    for sql in [
        '''CREATE TABLE IF NOT EXISTS replacement_orders (
            purchase_id INT PRIMARY KEY, old_account_id INT NOT NULL,new_account_id INT NOT NULL UNIQUE,
            admin_id BIGINT NOT NULL,reason VARCHAR(500) NOT NULL,created_at DATETIME NOT NULL,
            FOREIGN KEY(purchase_id) REFERENCES purchases(id)) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS refund_approvals (
            purchase_id INT PRIMARY KEY,requester BIGINT NOT NULL,approver BIGINT DEFAULT NULL,
            reason VARCHAR(500) NOT NULL,amount DECIMAL(18,8) NOT NULL,currency VARCHAR(16) NOT NULL,
            created_at DATETIME NOT NULL,approved_at DATETIME DEFAULT NULL,
            FOREIGN KEY(purchase_id) REFERENCES purchases(id)) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS stock_alerts (
            category VARCHAR(64) PRIMARY KEY,low_state TINYINT NOT NULL DEFAULT 0,
            last_sent DATETIME DEFAULT NULL) ENGINE=InnoDB''',
    ]: await cur.execute(sql)
    await cur.execute("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='support_messages' AND COLUMN_NAME='photo_id'")
    if not await cur.fetchone(): await cur.execute('ALTER TABLE support_messages ADD COLUMN photo_id VARCHAR(255) DEFAULT NULL')


async def rules():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT `key`,`value` FROM settings WHERE `key` IN ('wholesale_min_total','wholesale_pct','low_stock_limit')")
            values={r['key']:r['value'] for r in await cur.fetchall()}
    return {'minimum':str(Decimal(values.get('wholesale_min_total','500'))),'percent':str(Decimal(values.get('wholesale_pct','15'))),'low_stock':int(Decimal(values.get('low_stock_limit','3')))}


async def bulk_edit(admin,ids,field,value):
    if not ids or len(ids)>100 or len(set(ids))!=len(ids) or any(type(i)is not int or i<=0 for i in ids): raise ValueError('Укажите до 100 разных ID.')
    if field=='price':
        value=Decimal(value)
        if not value.is_finite() or not 0<value<=99999999 or value!=value.quantize(Decimal('.01')): raise ValueError('Проверьте цену.')
    elif field=='warranty_hours':
        value=int(value)
        if not 0<=value<=8760: raise ValueError('Срок: 0–8760 ч.')
    elif field=='features_note':
        if not 1<=len(value)<=500: raise ValueError('Описание: 1–500 символов.')
    else: raise ValueError('Поле: price, warranty_hours, features_note.')
    marks=','.join(['%s']*len(ids))
    async with _transaction() as cur:
        await cur.execute(f"SELECT id FROM accounts WHERE id IN ({marks}) AND status='available' ORDER BY id FOR UPDATE",tuple(sorted(ids)))
        if len(await cur.fetchall())!=len(ids): raise ValueError('Все товары должны существовать и быть свободны. Ничего не изменено.')
        if field=='price':
            await cur.execute(f'UPDATE accounts SET compare_price=CASE WHEN price>%s THEN GREATEST(price,COALESCE(compare_price,0)) WHEN compare_price>%s THEN compare_price ELSE NULL END,price=%s WHERE id IN ({marks})',(value,value,value,*ids))
        else: await cur.execute(f'UPDATE accounts SET {field}=%s WHERE id IN ({marks})',(value,*ids))
        await _record(cur,admin,'bulk_edit','accounts','batch',{'ids':ids,'field':field,'value':str(value)})


async def replace(admin,purchase,new_account,reason):
    if not 3<=len(reason.strip())<=500: raise ValueError('Причина: 3–500 символов.')
    async with _transaction() as cur:
        await cur.execute('SELECT *,warranty_until>UTC_TIMESTAMP() AS in_time FROM purchases WHERE id=%s FOR UPDATE',(purchase,))
        order=await cur.fetchone()
        if not order or order['status']=='refunded': raise ValueError('Заказ недоступен.')
        await cur.execute('SELECT id FROM support_tickets WHERE purchase_id=%s AND warranty_claimed_at IS NOT NULL',(purchase,))
        claim=await cur.fetchone()
        if not order['in_time'] and not claim: raise ValueError('Нет действующей гарантии или принятой в срок заявки.')
        await cur.execute('SELECT purchase_id FROM replacement_orders WHERE purchase_id=%s',(purchase,))
        if await cur.fetchone(): raise ValueError('По этому заказу замена уже выполнена.')
        await cur.execute('SELECT id,country,status,spam_lease_until>UTC_TIMESTAMP() AS spam_running FROM accounts WHERE id IN (%s,%s) ORDER BY id FOR UPDATE',(order['account_id'],new_account))
        accounts={r['id']:r for r in await cur.fetchall()}
        old,new=accounts.get(order['account_id']),accounts.get(new_account)
        if not old or not new or new['status']!='available' or old['country']!=new['country']: raise ValueError('Нужен свободный аккаунт той же категории.')
        if new.get('spam_running'): raise ValueError('Новый аккаунт проверяется через @SpamBot. Повторите через минуту.')
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE',(new_account,))
        hold=await cur.fetchone()
        if hold and hold['user_id']!=order['user_id']: raise ValueError('Товар зарезервирован другим покупателем.')
        await cur.execute('INSERT INTO replacement_orders VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP())',(purchase,old['id'],new_account,admin,reason.strip()))
        await cur.execute("UPDATE accounts SET status='replaced',password=NULL,data=NULL WHERE id=%s",(old['id'],))
        await cur.execute("UPDATE accounts SET status='sold' WHERE id=%s",(new_account,))
        await cur.execute("UPDATE purchases SET account_id=%s,status='issued' WHERE id=%s",(new_account,purchase))
        await cur.execute('DELETE FROM account_reservations WHERE account_id=%s',(new_account,))
        await cur.execute('DELETE FROM shopping_cart WHERE account_id=%s',(new_account,))
        await _record(cur,admin,'warranty_replace','order',purchase,{'old':old['id'],'new':new_account,'reason':reason.strip()})
        return order['user_id']


async def stock_notifications(bot,admins):
    if not admins: return
    policy=await rules()
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT c.slug,c.name,COUNT(a.id) AS n FROM categories c LEFT JOIN accounts a ON a.country=c.slug AND a.status='available' WHERE c.is_active=1 GROUP BY c.slug,c.name")
            rows=list(await cur.fetchall())
    from html import escape
    for row in rows:
        async with _transaction() as cur:
            await cur.execute('INSERT IGNORE INTO stock_alerts(category) VALUES(%s)',(row['slug'],))
            if row['n']>policy['low_stock']:
                await cur.execute('UPDATE stock_alerts SET low_state=0 WHERE category=%s',(row['slug'],));continue
            await cur.execute('UPDATE stock_alerts SET low_state=1,last_sent=UTC_TIMESTAMP() WHERE category=%s AND (low_state=0 OR last_sent<UTC_TIMESTAMP()-INTERVAL 24 HOUR)',(row['slug'],))
            claimed=cur.rowcount>0
        if claimed:
            failed=False
            for admin in set(admins):
                try: await bot.send_message(admin,f"📦 Низкий остаток: {escape(row['name'])} — {row['n']} шт.",parse_mode='HTML')
                except Exception: failed=True
            if failed:
                async with _transaction() as cur: await cur.execute('UPDATE stock_alerts SET last_sent=UTC_TIMESTAMP()-INTERVAL 23 HOUR WHERE category=%s',(row['slug'],))


async def request_refund(admin,purchase,reason):
    from database.refunds import refund_order
    pending=False
    new_request=False
    async with _transaction() as cur:
        await cur.execute('SELECT id,paid_amount,currency,status FROM purchases WHERE id=%s FOR UPDATE',(purchase,))
        order=await cur.fetchone()
        if not order or order['paid_amount'] is None: raise ValueError('Заказ недоступен.')
        if order['status']=='refunded': return None
        await cur.execute("SELECT `value` FROM settings WHERE `key`='refund_approval_threshold'")
        setting=await cur.fetchone()
        threshold=Decimal(setting['value']) if setting else Decimal(0)
        if threshold>0 and (order['currency']!='RUB' or Decimal(str(order['paid_amount']))>=threshold):
            await cur.execute('SELECT * FROM refund_approvals WHERE purchase_id=%s FOR UPDATE',(purchase,))
            existing=await cur.fetchone()
            if existing:
                if existing['reason']!=reason or existing['amount']!=order['paid_amount']: raise ValueError('Уже существует другая заявка на согласование.')
                pending=existing['approver'] is None
            else:
                await cur.execute('INSERT INTO refund_approvals(purchase_id,requester,reason,amount,currency,created_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP())',(purchase,admin,reason,order['paid_amount'],order['currency']))
                pending=True
                new_request=True
    if pending: return {'pending':True,'id':purchase,'amount':str(order['paid_amount']),'currency':order['currency'],'new_request':new_request}
    return await refund_order(admin,purchase,reason)


async def approve_refund(admin,purchase):
    async with _transaction() as cur:
        await cur.execute('SELECT * FROM refund_approvals WHERE purchase_id=%s FOR UPDATE',(purchase,))
        row=await cur.fetchone()
        if not row or row['requester']==admin: raise ValueError('Нужен другой администратор.')
        await cur.execute('SELECT paid_amount,currency FROM purchases WHERE id=%s',(purchase,))
        order=await cur.fetchone()
        if not order or order['paid_amount']!=row['amount'] or order['currency']!=row['currency']: raise ValueError('Условия возврата изменились.')
        if row['approver'] is None:
            await cur.execute('UPDATE refund_approvals SET approver=%s,approved_at=UTC_TIMESTAMP() WHERE purchase_id=%s',(admin,purchase))
            await _record(cur,admin,'refund_approve','order',purchase,{'requester':row['requester']})
    from database.refunds import refund_order
    return await refund_order(admin,purchase,row['reason'])
