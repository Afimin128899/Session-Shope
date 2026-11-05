"""Balance codes remain compatible; discount codes are consumed by checkout."""
from utils.i18n import tr
from decimal import Decimal, InvalidOperation
import re
from database.admin_tools import _transaction, _record
from database.db import _get_pool
import aiomysql


def code(value):
    if not isinstance(value, str) or not re.fullmatch('[A-Za-zА-Яа-яЁё0-9_-]{1,64}', value.strip()):
        raise ValueError(tr('Промокод: 1–64 буквы, цифры, дефис или подчёркивание.'))
    return value.strip().upper()


async def validate(cur, user_id, value, *, lock=False):
    value = code(value)
    await cur.execute('SELECT code,value,uses,max_uses,kind FROM promocodes WHERE code=%s' + (' FOR UPDATE' if lock else ''), (value,))
    promo = await cur.fetchone()
    if not promo or promo['max_uses'] is None or promo['uses'] >= promo['max_uses']:
        raise ValueError(tr('Промокод не найден или лимит активаций исчерпан.'))
    await cur.execute('SELECT user_id FROM used_promos WHERE code=%s AND user_id=%s' + (' FOR UPDATE' if lock else ''), (value, user_id))
    if await cur.fetchone():
        raise ValueError(tr('Вы уже использовали этот промокод.'))
    amount = Decimal(str(promo['value']))
    if not amount.is_finite() or amount <= 0 or (promo['kind'] == 'discount' and amount > 100) or (promo['kind'] not in {'balance', 'discount'}):
        raise ValueError(tr('Промокод временно недоступен.'))
    return promo


async def preview(user_id,value):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            promo=await validate(cur,user_id,value)
            return {key:promo[key] for key in ('code','kind','value')}


async def consume(cur,user_id,promo):
    await cur.execute('UPDATE promocodes SET uses=uses+1 WHERE code=%s',(promo['code'],))
    await cur.execute('INSERT INTO used_promos(user_id,code) VALUES(%s,%s)',(user_id,promo['code']))
    from database.activity import promo_event
    await promo_event(cur,user_id,promo)


async def redeem_balance(user_id, value):
    async with _transaction() as cur:
        promo = await validate(cur, user_id, value, lock=True)
        if promo['kind'] != 'balance':
            raise ValueError(tr('Этот код даёт скидку и применяется при оплате корзины.'))
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not await cur.fetchone():
            raise ValueError(tr('Покупатель не найден.'))
        await consume(cur, user_id, promo)
        await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s', (promo['value'], user_id))
        return Decimal(str(promo['value']))


async def create_discount(admin_id, value, percent, limit):
    value = code(value)
    if len(value.encode('utf-8')) > 40:
        raise ValueError(tr('Имя нового промокода: до 40 латинских символов или 20 кириллических.'))
    try:
        percent = Decimal(str(percent))
    except InvalidOperation:
        raise ValueError(tr('Проверьте процент скидки.')) from None
    if not percent.is_finite() or not 0 < percent <= 100 or percent != percent.quantize(Decimal('.01')) or (type(limit) is not int) or (not 1 <= limit <= 1000000):
        raise ValueError(tr('Скидка: 0.01–100%. Лимит: 1–1 000 000.'))
    async with _transaction() as cur:
        await cur.execute('SELECT code FROM promocodes WHERE code=%s FOR UPDATE', (value,))
        if await cur.fetchone():
            raise ValueError(tr('Промокод уже существует. Выберите другое имя.'))
        await cur.execute("INSERT INTO promocodes(code,value,max_uses,kind) VALUES(%s,%s,%s,'discount')", (value, percent, limit))
        await _record(cur, admin_id, 'discount_create', 'promo', value, {'percent': str(percent), 'max_uses': limit})
