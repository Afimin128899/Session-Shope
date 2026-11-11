"""Explicit projections and shared audited operations for the web admin."""
from utils.i18n import tr
import aiomysql
from database.db import _get_pool
from database.admin_tools import _transaction, _record, _decimal


async def rows(sql,args=()):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql,args)
            return list(await cur.fetchall())


async def overview():
    result={}
    for name,sql in {
        'stock':"SELECT COUNT(*) AS n FROM accounts WHERE status='available'",
        'orders':'SELECT COUNT(*) AS n FROM purchases',
        'tickets':"SELECT COUNT(*) AS n FROM support_tickets WHERE status<>'closed'",
        'users':'SELECT COUNT(*) AS n FROM users',
        'approvals':"SELECT COUNT(*) AS n FROM refund_approvals r JOIN purchases p ON p.id=r.purchase_id WHERE p.status<>'refunded'",
    }.items(): result[name]=(await rows(sql))[0]['n']
    result['sales']=await rows("SELECT currency,SUM(paid_amount) AS amount,COUNT(*) AS n FROM purchases WHERE status<>'refunded' AND date>=DATE_FORMAT(UTC_TIMESTAMP()+INTERVAL 3 HOUR,'%%Y-%%m-%%d') GROUP BY currency")
    return result


async def stock(query='',status='available',page=0):
    condition='1=1';args=[]
    if status:
        condition+=' AND a.status=%s';args.append(status)
    if query:
        condition+=" AND (CAST(a.id AS CHAR)=%s OR CAST(a.telegram_user_id AS CHAR)=%s OR a.number LIKE %s OR c.name LIKE %s)";args += [query,query,'%'+query+'%','%'+query+'%']
    items=await rows('SELECT a.id,a.country,a.number,a.telegram_user_id,a.price,a.status,a.review_reason,a.review_admin_id,a.review_started_at,a.warranty_hours,a.registration_date,a.is_premium,a.features_note,a.spam_status,a.spam_checked_at,a.spam_lease_until,c.name FROM accounts a LEFT JOIN categories c ON c.slug=a.country WHERE '+condition+' ORDER BY a.id DESC LIMIT 31 OFFSET %s',(*args,page*30))
    from database.spam_checks import public as spam_status
    for item in items:
        item['spam_check']=spam_status(item)
        item.pop('spam_lease_until',None)
    return {'items':items[:30],'has_more':len(items)>30}


async def orders(query='',page=0):
    condition='1=1';args=[]
    if query:
        condition+=' AND (CAST(p.id AS CHAR)=%s OR CAST(p.user_id AS CHAR)=%s OR u.username LIKE %s)';args=[query,query,'%'+query+'%']
    items=await rows('SELECT p.id,p.user_id,p.account_id,p.date,p.currency,p.paid_amount,p.status,u.username,c.name,t.id AS ticket_id FROM purchases p LEFT JOIN users u ON u.id=p.user_id LEFT JOIN accounts a ON a.id=p.account_id LEFT JOIN categories c ON c.slug=a.country LEFT JOIN support_tickets t ON t.purchase_id=p.id WHERE '+condition+' ORDER BY p.id DESC LIMIT 31 OFFSET %s',(*args,page*30))
    return {'items':items[:30],'has_more':len(items)>30}


async def edit_stock(admin, account, body):
    price = _decimal(body.get('price'), '0.01', '10000.00')
    hours = body.get('warranty_hours')
    category = body.get('category')
    note = body.get('note', '')
    registered = body.get('registration_date') or None
    premium = body.get('is_premium')
    if price <= 0 or type(hours) is not int or (not 0 <= hours <= 8760) or (not isinstance(category, str)) or (len(category) > 64) or (not isinstance(note, str)) or (len(note) > 500) or (premium is not None and type(premium) is not bool):
        raise ValueError(tr('Проверьте характеристики.'))
    if registered:
        from datetime import date, datetime
        from zoneinfo import ZoneInfo
        registered = date.fromisoformat(registered)
        if not date(2013, 8, 1) <= registered <= datetime.now(ZoneInfo('Europe/Moscow')).date():
            raise ValueError(tr('Проверьте дату регистрации.'))
    async with _transaction() as cur:
        await cur.execute("SELECT id,number,country,spam_status,spam_checked_at FROM accounts WHERE id=%s AND status IN ('available','review') FOR UPDATE", (account,))
        account_row = await cur.fetchone()
        if not account_row:
            raise ValueError(tr('Редактирование доступно только для свободного товара.'))
        from utils.commerce_policy import require_phone, category as check_category
        require_phone(account_row['number'])
        from database.auto_categories import validate_selection
        validate_selection(account_row['number'], account_row.get('spam_status'), account_row.get('spam_checked_at'), category, account_row.get('country'))
        pending_category = category == account_row.get('country') and category.startswith('auto-') and category.endswith('-pending')
        if not pending_category:
            await check_category(cur, category)
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (account,))
        if await cur.fetchone():
            raise ValueError(tr('Товар зарезервирован покупателем. Дождитесь окончания резерва.'))
        if not (category == account_row.get('country') and category.startswith('auto-') and category.endswith('-pending')):
            await cur.execute('SELECT slug FROM categories WHERE slug=%s AND is_active=1', (category,))
            if not await cur.fetchone():
                raise ValueError(tr('Категория недоступна.'))
        await cur.execute('UPDATE accounts SET compare_price=CASE WHEN price>%s THEN GREATEST(price,COALESCE(compare_price,0)) WHEN compare_price>%s THEN compare_price ELSE NULL END,\n            price=%s,country=%s,warranty_hours=%s,registration_date=%s,is_premium=%s,features_note=%s,attributes_checked_at=UTC_TIMESTAMP() WHERE id=%s', (price, price, price, category, hours, registered, premium, note.strip(), account))
        await _record(cur, admin, 'web_stock_edit', 'account', account, {'price': str(price), 'category': category, 'warranty_hours': hours})


async def categories():
    return await rows('SELECT slug,name,is_active,sort_order FROM categories ORDER BY sort_order,name')


async def save_category(admin, body):
    import re
    slug = body.get('slug')
    name = body.get('name')
    active = body.get('active', True)
    if not isinstance(slug, str) or not re.fullmatch('[a-z0-9_-]{1,32}', slug) or (not isinstance(name, str)) or (not 1 <= len(name.strip()) <= 64) or (type(active) is not bool):
        raise ValueError(tr('Проверьте название и код категории.'))
    from utils.commerce_policy import require_category
    require_category(slug, name)
    async with _transaction() as cur:
        await cur.execute('INSERT INTO categories(slug,name,is_active) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE name=VALUES(name),is_active=VALUES(is_active)', (slug, name.strip(), active))
        await _record(cur, admin, 'web_category', 'category', slug, {'name': name.strip(), 'active': active})


async def settings():
    allowed=('wholesale_min_total','wholesale_pct','refund_approval_threshold','low_stock_limit','support_hours','support_eta','maintenance_mode','sales_paused','sales_pause_reason','maintenance_reason','maintenance_eta','platega_stub')
    result={r['key']:r['value'] for r in await rows('SELECT `key`,`value` FROM settings WHERE `key` IN ('+','.join(['%s']*len(allowed))+')',allowed)}
    from database import referrals
    values = await referrals.settings()
    result.update({key: str(values[field]) for key, field in referrals.SETTING_FIELDS.items()})
    return result


async def save_settings(admin, body):
    from decimal import Decimal
    allowed = {'wholesale_min_total': (1, 10000), 'wholesale_pct': (0, 50), 'refund_approval_threshold': (0, 10000), 'low_stock_limit': (0, 10000)}
    from database import referrals
    referral_values = referrals.validate_settings({k:v for k,v in body.items() if k in referrals.SETTING_FIELDS})
    values = {}
    for key, value in body.items():
        if key in referrals.SETTING_FIELDS:
            continue
        if key in allowed:
            amount = _decimal(value, '0.01', '99999999')
            if not Decimal(str(allowed[key][0])) <= amount <= Decimal(str(allowed[key][1])) or (key == 'low_stock_limit' and amount != int(amount)):
                raise ValueError(tr('Проверьте числовые настройки.'))
            values[key] = str(int(amount)) if key == 'low_stock_limit' else str(amount)
        elif key in {'support_hours', 'support_eta', 'sales_pause_reason', 'maintenance_reason', 'maintenance_eta'} and isinstance(value, str) and (1 <= len(value.strip()) <= 200):
            values[key] = value.strip()
        elif key in {'maintenance_mode', 'sales_paused', 'platega_stub'} and value in ('0', '1'):
            values[key] = value
        else:
            raise ValueError(tr('Неизвестная настройка.'))
    if not values and not referral_values:
        raise ValueError(tr('Нет изменений.'))
    async with _transaction() as cur:
        for key, value in sorted(values.items()):
            await cur.execute('INSERT INTO settings(`key`,`value`) VALUES(%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)', (key, value))
        if referral_values:
            await referrals.save_settings(cur, admin, referral_values)
        if values:
            await _record(cur, admin, 'web_settings', 'settings', 'shop', values)


async def create_balance_promo(admin, code, value, limit):
    from database.coupons import code as normalize
    code = normalize(code)
    amount = _decimal(value, '0.01', '10000.00')
    if len(code.encode()) > 40 or amount <= 0 or type(limit) is not int or (not 1 <= limit <= 1000000):
        raise ValueError(tr('Проверьте код, сумму и лимит.'))
    async with _transaction() as cur:
        await cur.execute('SELECT code FROM promocodes WHERE code=%s FOR UPDATE', (code,))
        if await cur.fetchone():
            raise ValueError(tr('Промокод уже существует.'))
        await cur.execute("INSERT INTO promocodes(code,value,max_uses,kind) VALUES(%s,%s,%s,'balance')", (code, amount, limit))
        await _record(cur, admin, 'web_balance_promo', 'promo', code, {'amount': str(amount), 'limit': limit})


async def disable_promo(admin, code):
    if not isinstance(code, str) or not 1 <= len(code) <= 255:
        raise ValueError(tr('Некорректный код.'))
    async with _transaction() as cur:
        await cur.execute('SELECT code FROM promocodes WHERE code=%s FOR UPDATE', (code,))
        if not await cur.fetchone():
            raise ValueError(tr('Промокод не найден.'))
        await cur.execute('UPDATE promocodes SET max_uses=uses WHERE code=%s', (code,))
        await _record(cur, admin, 'web_promo_disable', 'promo', code[:64], {})


async def payment_invoices(query='', status='', page=0):
    conditions, args = ['1=1'], []
    if status:
        conditions.append('p.status=%s')
        args.append(status)
    if query:
        conditions.append('(CAST(p.user_id AS CHAR)=%s OR p.invoice_id=%s OR u.username LIKE %s)')
        args += [query, query, '%' + query + '%']
    items = await rows('SELECT p.provider,p.invoice_id,p.user_id,p.amount_rub,p.credited_amount,p.status,'
                       'p.created_at,p.expires_at,u.username FROM payment_invoices p '
                       'LEFT JOIN users u ON u.id=p.user_id WHERE ' + ' AND '.join(conditions) +
                       ' ORDER BY p.created_at DESC,p.provider,p.invoice_id LIMIT 31 OFFSET %s', (*args, page * 30))
    return {'items': items[:30], 'has_more': len(items) > 30}
