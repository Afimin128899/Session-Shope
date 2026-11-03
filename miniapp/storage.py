"""Safe projections of the shared inventory and an authoritative checkout."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import aiomysql

from database.db import _get_pool
from database.admin_tools import _transaction
from database import quality, coupons


class CheckoutError(ValueError):
    def __init__(self, message, code='conflict'):
        super().__init__(message)
        self.code = code


def mask_phone(phone):
    phone = str(phone or '')
    return phone[:4] + ' ••• ' + phone[-3:] if len(phone) > 7 else '••• •••'


def money(value):
    return Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


async def pricing(cur, user_id):
    await cur.execute('SELECT referrer_id FROM referrals WHERE referral_id = %s', (user_id,))
    ref = await cur.fetchone()
    if not ref or ref['referrer_id'] == user_id:
        return None, Decimal('0'), Decimal('0')
    await cur.execute('SELECT discount_pct, bonus_pct FROM referral_settings WHERE id = 1')
    settings = await cur.fetchone() or {'discount_pct': 5, 'bonus_pct': 5}
    discount, bonus = Decimal(str(settings['discount_pct'])), Decimal(str(settings['bonus_pct']))
    if not 0 <= discount <= 100 or not 0 <= bonus <= 100:
        raise CheckoutError('Настройки скидки временно недоступны.', 'unavailable')
    return ref['referrer_id'], discount, bonus


async def catalog(user_id, category='', query='', sort='new', page=0, *, min_price=None, max_price=None, favorites=False, cart=False, premium=None, min_age=None, account_id=None):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            _, discount, _ = await pricing(cur, user_id)
            await cur.execute(
                "SELECT c.slug,c.name,COUNT(a.id) AS count FROM categories c LEFT JOIN accounts a "
                "ON a.country=c.slug AND a.status='available' AND NOT EXISTS "
                "(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s) "
                'WHERE c.is_active=1 GROUP BY c.slug,c.name ORDER BY c.sort_order,c.name', (user_id,),
            )
            categories = list(await cur.fetchall())
            conditions, params = [], [user_id, user_id]
            if account_id is not None:
                conditions.append('a.id=%s'); params.append(account_id)
            if cart:
                conditions.append('t.user_id IS NOT NULL')
            elif favorites:
                conditions.append('f.user_id IS NOT NULL')
            else:
                conditions += ['c.is_active=1', "a.status='available'", '(r.user_id IS NULL OR r.user_id=%s)']
                params.append(user_id)
            if premium is not None:
                conditions.append('a.is_premium=%s');params.append(premium)
            if min_age is not None:
                conditions.append('a.registration_date<=DATE_SUB(UTC_DATE(),INTERVAL %s DAY)');params.append(min_age)
            if category:
                conditions.append('c.slug=%s'); params.append(category)
            if query:
                term = '%' + query.replace('=', '==').replace('%', '=%').replace('_', '=_') + '%'
                numeric = query.removeprefix('#').removeprefix('SBA-')
                if numeric.isascii() and numeric.isdigit() and len(numeric)<=18:
                    conditions.append("(c.name LIKE %s ESCAPE '=' OR a.id=%s OR a.telegram_user_id=%s)")
                    params += [term, int(numeric), int(numeric)]
                else:
                    conditions.append("c.name LIKE %s ESCAPE '='"); params.append(term)
            factor = 1 - discount / 100
            for bound, comparator in [(min_price, '>='), (max_price, '<=')]:
                if bound is not None:
                    conditions.append(f'ROUND(a.price * %s,2){comparator}%s'); params += [factor, bound]
            ordering = {
                'new': 'a.id DESC', 'price_asc': 'a.price ASC,a.id DESC', 'price_desc': 'a.price DESC,a.id DESC',
                'discount': 'CASE WHEN a.compare_price>a.price THEN 1-a.price/a.compare_price ELSE 0 END DESC,a.id DESC',
            }[sort]
            await cur.execute(
                'SELECT a.id,a.telegram_user_id,a.number,a.price,a.compare_price,a.status,a.password,a.registration_date,a.features_note,a.is_premium,a.attributes_checked_at,a.warranty_hours,c.is_active,c.slug,c.name,'
                'f.user_id AS favorite,t.user_id AS in_cart,r.user_id AS reserved_by,r.expires_at '
                'FROM accounts a JOIN categories c ON c.slug=a.country '
                'LEFT JOIN account_favorites f ON f.account_id=a.id AND f.user_id=%s '
                'LEFT JOIN shopping_cart t ON t.account_id=a.id AND t.user_id=%s '
                'LEFT JOIN account_reservations r ON r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() '
                'WHERE ' + ' AND '.join(conditions) + f' ORDER BY {ordering} LIMIT 25 OFFSET %s', (*params,page*24),
            )
            rows = list(await cur.fetchall())
            items=[]
            for row in rows[:24]:
                price=money(Decimal(str(row['price']))*factor)
                before=max(Decimal(str(row['price'])),Decimal(str(row['compare_price'] or 0)))
                reduction=money((1-price/before)*100) if before>0 else Decimal('0')
                items.append({'id':row['id'],'product_id':f"SBA-{row['id']:06d}", 'telegram_user_id':str(row['telegram_user_id']) if row['telegram_user_id'] else None,
                              'category':row['slug'],'name':row['name'],'phone':mask_phone(row['number']),
                              'price':str(price),'original_price':str(before),'discount':str(reduction),
                              'favorite':bool(row['favorite']), 'in_cart':bool(row['in_cart']),
                              'characteristics':quality.characteristics(row),
                              'available':bool(row['is_active']) and row['status']=='available' and row['reserved_by'] in (None,user_id),
                              'reserved_until':row['expires_at'].replace(tzinfo=timezone.utc).isoformat() if row['reserved_by']==user_id else None})
            return {'categories':categories,'has_more':len(rows)>24,'items':items}


async def access_settings():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT `key`, `value` FROM settings WHERE `key` IN ('maintenance_mode', 'sub_channel_id', 'sub_channel_enabled', 'sub_channel_url')")
            return {row['key']: row['value'] for row in await cur.fetchall()}


_UNSET = object()


async def checkout(user_id, account_id, quoted_price, *, warranty_hours=_UNSET):
    async with _transaction() as cur:
        await cur.execute(
            "SELECT a.id, a.price, a.country, a.warranty_hours FROM accounts a JOIN categories c ON c.slug = a.country "
            "WHERE a.id = %s AND a.status = 'available' AND c.is_active = 1 FOR UPDATE", (account_id,),
        )
        account = await cur.fetchone()
        if account is None:
            raise CheckoutError('Этот аккаунт уже куплен. Обновите каталог.', 'sold')
        if warranty_hours is not _UNSET and account['warranty_hours'] != warranty_hours:
            raise CheckoutError('Условия гарантии изменились. Подтвердите покупку заново.', 'terms_changed')
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (account_id,))
        reservation = await cur.fetchone()
        if reservation and reservation['user_id'] != user_id:
            raise CheckoutError('Аккаунт зарезервирован другим покупателем.', 'reserved')
        referrer, discount, bonus_pct = await pricing(cur, user_id)
        base = Decimal(str(account['price']))
        actual_price = money(base * (1 - discount / 100))
        if base <= 0 or actual_price < 0:
            raise CheckoutError('Некорректная цена товара.', 'unavailable')
        if actual_price != quoted_price:
            raise CheckoutError('Цена изменилась. Обновите каталог и подтвердите покупку заново.', 'price_changed')
        # Stable lock ordering includes the referrer to avoid reciprocal-referral deadlocks.
        users = sorted({user_id, referrer} - {None})
        await cur.execute('SELECT id, balance FROM users WHERE id IN (' + ','.join(['%s'] * len(users)) + ') ORDER BY id FOR UPDATE', tuple(users))
        balances = {row['id']: row['balance'] for row in await cur.fetchall()}
        if user_id not in balances or Decimal(str(balances[user_id])) < actual_price:
            raise CheckoutError('Недостаточно средств. Пополните баланс в боте.', 'insufficient_balance')
        await cur.execute('UPDATE users SET balance = balance - %s WHERE id = %s', (actual_price, user_id))
        await cur.execute("UPDATE accounts SET status = 'sold' WHERE id = %s", (account_id,))
        await cur.execute(
            'INSERT INTO purchases (user_id, account_id, date, currency, paid_amount) VALUES (%s, %s, %s, %s, %s)',
            (user_id, account_id, datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d %H:%M:%S'), 'RUB', actual_price),
        )
        order_id = cur.lastrowid
        await quality.snapshot(cur, order_id)
        if referrer in balances:
            bonus = (base * bonus_pct / 100).quantize(Decimal('0.00000001'))
            await cur.execute('UPDATE users SET balance = balance + %s WHERE id = %s', (bonus, referrer))
        await cur.execute(
            'UPDATE purchases SET referrer_id = %s, referral_bonus = %s WHERE id = %s',
            (referrer if referrer in balances else None, bonus if referrer in balances else 0, order_id),
        )
        await cur.execute('DELETE FROM shopping_cart WHERE user_id=%s AND account_id=%s',(user_id,account_id))
        await cur.execute('DELETE FROM account_reservations WHERE account_id=%s',(account_id,))
        return {'id': order_id, 'paid_amount': str(actual_price), 'balance': str(Decimal(str(balances[user_id])) - actual_price)}


async def orders(user_id, page=0, query=''):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                'SELECT p.id, p.date, p.currency, p.paid_amount, p.status, a.number, c.name, '
                't.id AS ticket_id, t.status AS ticket_status FROM purchases p '
                'LEFT JOIN accounts a ON a.id = p.account_id LEFT JOIN categories c ON c.slug = a.country '
                'LEFT JOIN support_tickets t ON t.purchase_id = p.id WHERE p.user_id = %s '
                "AND (CAST(p.id AS CHAR)=%s OR c.name LIKE %s OR a.country=%s OR p.date LIKE %s OR %s='') ORDER BY p.id DESC LIMIT 25 OFFSET %s", (user_id,query,'%'+query+'%',query,query+'%',query,page*24),
            )
            rows = list(await cur.fetchall())
            for row in rows:
                row['name'] = row['name'] or 'Аккаунт'
            return {'items': rows[:24], 'has_more': len(rows) > 24}


async def checkout_cart(user_id, requested, promo_code=None, expected_total=None):
    if not requested or len(requested)>20 or len({item['account_id'] for item in requested})!=len(requested):
        raise CheckoutError('Выберите от 1 до 20 разных аккаунтов.', 'invalid_cart')
    quotes={item['account_id']:Decimal(item['price']) for item in requested}
    ids=sorted(quotes)
    placeholders=','.join(['%s']*len(ids))
    async with _transaction() as cur:
        await cur.execute("SELECT a.id,a.price,a.warranty_hours FROM accounts a JOIN categories c ON c.slug=a.country WHERE a.id IN ("+placeholders+") AND a.status='available' AND c.is_active=1 ORDER BY a.id FOR UPDATE",tuple(ids))
        accounts=list(await cur.fetchall())
        if len(accounts)!=len(ids):
            raise CheckoutError('Один из аккаунтов уже недоступен. Корзина не оплачена.', 'sold')
        terms={item['account_id']:item for item in requested}
        if any('warranty_hours' in terms[row['id']] and terms[row['id']]['warranty_hours'] != row['warranty_hours'] for row in accounts):
            raise CheckoutError('Условия гарантии изменились. Обновите корзину.', 'terms_changed')
        await cur.execute('SELECT account_id,user_id FROM account_reservations WHERE account_id IN ('+placeholders+') AND expires_at>UTC_TIMESTAMP() ORDER BY account_id FOR UPDATE',tuple(ids))
        holds={row['account_id']:row['user_id'] for row in await cur.fetchall()}
        if any(holds.get(account)!=user_id for account in ids):
            raise CheckoutError('Резерв истёк или принадлежит другому покупателю. Обновите резерв.', 'reservation_expired')
        referrer,discount,bonus_pct=await pricing(cur,user_id)
        prices={row['id']:money(Decimal(str(row['price']))*(1-discount/100)) for row in accounts}
        if any(Decimal(str(row['price'])) <= 0 for row in accounts):
            raise CheckoutError('Некорректная цена товара.', 'unavailable')
        if any(prices[account]!=quotes[account] or prices[account]<0 for account in ids):
            raise CheckoutError('Цена изменилась. Проверьте корзину и подтвердите заново.', 'price_changed')
        await cur.execute("SELECT `key`,`value` FROM settings WHERE `key` IN ('wholesale_min_total','wholesale_pct')")
        wholesale={r['key']:r['value'] for r in await cur.fetchall()}
        rate=Decimal(wholesale.get('wholesale_pct','15')) if sum(prices.values(),Decimal(0))>=Decimal(wholesale.get('wholesale_min_total','500')) else Decimal(0)
        if not 0<=rate<=50: raise CheckoutError('Настройки опта недоступны.')
        if rate:
            prices={key:money(value*(1-rate/100)) for key,value in prices.items()}
        promo = None
        if promo_code:
            try:
                promo = await coupons.validate(cur,user_id,promo_code,lock=True)
            except ValueError as exc:
                raise CheckoutError(str(exc),'invalid_promo') from None
            if promo['kind'] != 'discount':
                raise CheckoutError('Балансовый промокод сначала активируйте в профиле.', 'invalid_promo')
            prices = {key: money(value*(1-Decimal(str(promo['value']))/100)) for key,value in prices.items()}
            if expected_total is None or sum(prices.values(),Decimal('0')) != Decimal(str(expected_total)):
                raise CheckoutError('Условия промокода изменились. Проверьте новую сумму.', 'price_changed')
        if rate and (expected_total is None or sum(prices.values(),Decimal('0'))!=Decimal(str(expected_total))):
            raise CheckoutError('Оптовые условия изменились. Обновите корзину.','price_changed')
        users=sorted({user_id,referrer}-{None})
        await cur.execute('SELECT id,balance FROM users WHERE id IN ('+','.join(['%s']*len(users))+') ORDER BY id FOR UPDATE',tuple(users))
        balances={row['id']:Decimal(str(row['balance'])) for row in await cur.fetchall()}
        total=sum(prices.values(),Decimal('0'))
        if user_id not in balances or balances[user_id]<total:
            raise CheckoutError('Недостаточно средств для всей корзины.', 'insufficient_balance')
        await cur.execute('SELECT account_id FROM shopping_cart WHERE user_id=%s AND account_id IN ('+placeholders+') FOR UPDATE',(user_id,*ids))
        if {row['account_id'] for row in await cur.fetchall()}!=set(ids):
            raise CheckoutError('Корзина изменилась. Обновите страницу.', 'cart_changed')
        if promo:
            await coupons.consume(cur,user_id,promo)
        await cur.execute('UPDATE users SET balance=balance-%s WHERE id=%s',(total,user_id))
        order_ids=[]
        bonus_total=Decimal('0')
        for account in accounts:
            bonus=(Decimal(str(account['price']))*bonus_pct/100).quantize(Decimal('0.00000001')) if referrer in balances else Decimal('0')
            bonus_total+=bonus
            await cur.execute("UPDATE accounts SET status='sold' WHERE id=%s",(account['id'],))
            await cur.execute('INSERT INTO purchases (user_id,account_id,date,currency,paid_amount,referrer_id,referral_bonus) VALUES (%s,%s,%s,%s,%s,%s,%s)',
                              (user_id,account['id'],datetime.now(ZoneInfo('Europe/Moscow')).strftime('%Y-%m-%d %H:%M:%S'),'RUB',prices[account['id']],referrer if referrer in balances else None,bonus))
            purchase_id = cur.lastrowid
            await quality.snapshot(cur,purchase_id)
            order_ids.append(purchase_id)
        if referrer in balances:
            await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s',(bonus_total,referrer))
        await cur.execute('DELETE FROM shopping_cart WHERE user_id=%s AND account_id IN ('+placeholders+')',(user_id,*ids))
        await cur.execute('DELETE FROM account_reservations WHERE account_id IN ('+placeholders+')',tuple(ids))
        return {'order_ids':order_ids,'paid_amount':str(total),'balance':str(balances[user_id]-total)}
