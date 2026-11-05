"""Atomic referral rewards. Never reward a retry, a wallet bonus or an old signup."""
import hashlib
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import aiomysql
from database.admin_tools import _transaction, _decimal, _record
from database.db import _get_pool
from utils.i18n import tr

FIELDS = ('discount_pct', 'bonus_pct', 'signup_bonus', 'deposit_pct', 'daily_limit')
DEFAULTS = {'discount_pct': Decimal('5'), 'bonus_pct': Decimal('5'),
            'signup_bonus': Decimal('3'), 'deposit_pct': Decimal('5'), 'daily_limit': Decimal('30')}
SETTING_FIELDS = {'referral_signup_bonus': 'signup_bonus', 'referral_deposit_pct': 'deposit_pct',
                  'referral_daily_limit': 'daily_limit', 'referral_purchase_pct': 'bonus_pct', 'referral_discount_pct': 'discount_pct'}


async def init_schema(cur, database):
    for field, definition in [('signup_bonus', 'DECIMAL(18,2) NOT NULL DEFAULT 3.00'),
                              ('deposit_pct', 'DECIMAL(5,2) NOT NULL DEFAULT 5.00'),
                              ('daily_limit', 'DECIMAL(18,2) NOT NULL DEFAULT 30.00')]:
        await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, 'referral_settings', field))
        if not await cur.fetchone():
            await cur.execute(f'ALTER TABLE referral_settings ADD COLUMN {field} {definition}')
    await cur.execute('''CREATE TABLE IF NOT EXISTS referral_rewards (
        event_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        kind VARCHAR(16) NOT NULL, provider VARCHAR(16) NOT NULL, reference VARCHAR(255) NOT NULL,
        user_id BIGINT NOT NULL, referrer_id BIGINT NOT NULL,
        base_amount DECIMAL(18,8) NOT NULL, rate DECIMAL(5,2) NOT NULL,
        amount DECIMAL(18,8) NOT NULL, reversed TINYINT NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL, reversed_at DATETIME DEFAULT NULL,
        KEY referral_recipient(referrer_id,created_at), KEY referral_customer(user_id)
    ) ENGINE=InnoDB''')
    for field, definition in [('requested_amount','DECIMAL(18,8) DEFAULT NULL'),
                              ('limit_reason','VARCHAR(16) DEFAULT NULL'), ('reward_day','DATE DEFAULT NULL')]:
        await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, 'referral_rewards', field))
        if not await cur.fetchone():
            await cur.execute(f'ALTER TABLE referral_rewards ADD COLUMN {field} {definition}')
    await cur.execute('''CREATE TABLE IF NOT EXISTS referral_daily_totals (
        referrer_id BIGINT NOT NULL, reward_day DATE NOT NULL, issued DECIMAL(18,8) NOT NULL DEFAULT 0,
        PRIMARY KEY(referrer_id,reward_day)) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS referral_blocks (
        user_id BIGINT PRIMARY KEY, blocked TINYINT NOT NULL DEFAULT 1,
        reason VARCHAR(500) NOT NULL, admin_id BIGINT NOT NULL, updated_at DATETIME NOT NULL
    ) ENGINE=InnoDB''')


def row(value, fields):
    return value if isinstance(value, dict) else dict(zip(fields, value))


async def read_settings(cur, *, lock=False):
    await cur.execute('SELECT ' + ','.join(FIELDS) + ' FROM referral_settings WHERE id=1' + (' LOCK IN SHARE MODE' if lock else ''))
    found = await cur.fetchone()
    result = {key: Decimal(str(value)) for key, value in {**DEFAULTS, **(row(found, FIELDS) if found else {})}.items()}
    if any(not value.is_finite() or not 0 <= value <= (10000 if key in {'signup_bonus','daily_limit'} else 100) for key,value in result.items()):
        raise ValueError(tr('Настройки реферальной программы временно недоступны.'))
    return result


async def settings():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            return await read_settings(cur)


def validate_settings(values):
    result = {}
    for key, value in values.items():
        if key not in SETTING_FIELDS:
            raise ValueError(tr('Неизвестная настройка.'))
        amount = _decimal(value, '0.01', '10000' if key in {'referral_signup_bonus','referral_daily_limit'} else '100')
        if isinstance(value, bool) or amount < 0:
            raise ValueError(tr('Награда и проценты не могут быть отрицательными.'))
        result[key] = amount
    return result


async def save_settings(cur, admin, values):
    values = validate_settings(values)
    if not values:
        return
    # Column identifiers are selected exclusively from the constant mapping above.
    await cur.execute('UPDATE referral_settings SET ' + ','.join(SETTING_FIELDS[k] + '=%s' for k in sorted(values)) + ' WHERE id=1', tuple(values[k] for k in sorted(values)))
    await _record(cur, admin, 'referral_settings', 'settings', 'referrals', {key: str(value) for key, value in values.items()})


def event_key(kind, provider, reference):
    return hashlib.sha256(f'{kind}:{provider}:{reference}'.encode()).hexdigest()


def reward_day():
    return datetime.now(ZoneInfo('Europe/Moscow')).date()


async def historical_issued(cur, user_id, day):
    """Bootstrap today's allowance including old orders, without paying anything retroactively."""
    start = datetime.combine(day, time.min, ZoneInfo('Europe/Moscow')).astimezone(timezone.utc).replace(tzinfo=None)
    end = start + timedelta(days=1)
    await cur.execute('SELECT COALESCE(SUM(amount),0) AS issued FROM referral_rewards WHERE referrer_id=%s AND (reward_day=%s OR (reward_day IS NULL AND created_at>=%s AND created_at<%s))', (user_id, day, start, end))
    issued = Decimal(str(row(await cur.fetchone(), ('issued',))['issued']))
    await cur.execute("SELECT COALESCE(SUM(p.referral_bonus),0) AS issued FROM purchases p WHERE p.referrer_id=%s AND p.currency='RUB' AND p.date>=%s AND p.date<%s AND NOT EXISTS(SELECT 1 FROM referral_rewards r WHERE r.kind='purchase' AND r.provider='shop' AND BINARY r.reference=BINARY CAST(p.id AS CHAR))", (user_id, str(day), str(day + timedelta(days=1))))
    return issued + Decimal(str(row(await cur.fetchone(), ('issued',))['issued']))


async def allocation(cur, user_id, requested, values):
    """Recipient wallet must already be locked. Refunds never replenish the daily allowance."""
    day = reward_day()
    await cur.execute('SELECT blocked FROM referral_blocks WHERE user_id=%s LOCK IN SHARE MODE', (user_id,))
    found = await cur.fetchone()
    if found and row(found, ('blocked',))['blocked']:
        return Decimal(0), 'blocked', day
    await cur.execute('SELECT issued FROM referral_daily_totals WHERE referrer_id=%s AND reward_day=%s FOR UPDATE', (user_id, day))
    found = await cur.fetchone()
    if found:
        issued = Decimal(str(row(found, ('issued',))['issued']))
    else:
        issued = await historical_issued(cur, user_id, day)
        await cur.execute('INSERT INTO referral_daily_totals(referrer_id,reward_day,issued) VALUES(%s,%s,%s)', (user_id, day, issued))
    amount = min(requested, max(Decimal(0), values['daily_limit'] - issued))
    return amount, 'daily_limit' if amount < requested else None, day


async def credit_purchase(cur, user_id, referrer, paid, rate, purchase_id):
    requested = (Decimal(str(paid)) * Decimal(str(rate)) / 100).quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
    return await _award(cur, user_id, referrer, 'purchase', 'shop', str(purchase_id), paid, rate, requested) or Decimal(0)


async def mark_purchase_reversed(cur, purchase_id):
    await cur.execute('UPDATE referral_rewards SET reversed=1,reversed_at=UTC_TIMESTAMP() WHERE event_key=%s AND reversed=0', (event_key('purchase', 'shop', str(purchase_id)),))


async def set_block(admin, user_id, blocked, reason=''):
    if type(user_id) is not int or not 0 < user_id <= 9223372036854775807 or type(blocked) is not bool:
        raise ValueError(tr('Введите корректный Telegram ID.'))
    if not isinstance(reason, str) or len(reason.strip()) > 500:
        raise ValueError(tr('Причина: до 500 символов.'))
    reason = reason.strip() or tr('Блокировка администратором')
    async with _transaction() as cur:
        # Same wallet-first order as all grants. Once this transaction commits,
        # a waiting grant must observe the block. Unknown IDs can be blocked in advance.
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        await cur.fetchone()
        await cur.execute('INSERT INTO referral_blocks(user_id,blocked,reason,admin_id,updated_at) VALUES(%s,%s,%s,%s,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE blocked=VALUES(blocked),reason=VALUES(reason),admin_id=VALUES(admin_id),updated_at=VALUES(updated_at)', (user_id, blocked, reason, admin))
        await _record(cur, admin, 'referral_block' if blocked else 'referral_unblock', 'user', user_id, {'reason': reason})


async def blocks(page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT user_id,reason,updated_at FROM referral_blocks WHERE blocked=1 ORDER BY updated_at DESC,user_id LIMIT 21 OFFSET %s', (page * 20,))
            items = list(await cur.fetchall())
            return {'items': items[:20], 'has_more': len(items) > 20}


async def invited(user_id, page=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('''SELECT u.id,u.username,
                (SELECT MIN(created_at) FROM referral_rewards r WHERE r.kind='signup' AND r.user_id=u.id AND r.referrer_id=%s) AS joined_at
                FROM referrals f JOIN users u ON u.id=f.referral_id
                WHERE f.referrer_id=%s ORDER BY u.id DESC LIMIT 21 OFFSET %s''', (user_id, user_id, page * 20))
            items = list(await cur.fetchall())
            return {'items': items[:20], 'has_more': len(items) > 20}


async def lock_participants(cur, user_id, *, reverse_provider=None, reference=None):
    """Lock wallets in the same ascending order as checkout, before any balance write."""
    if reverse_provider:
        await cur.execute('SELECT referrer_id FROM referral_rewards WHERE event_key=%s', (event_key('deposit', reverse_provider, reference),))
    else:
        await cur.execute('SELECT referrer_id FROM referrals WHERE referral_id=%s', (user_id,))
    found = await cur.fetchone()
    referrer = row(found, ('referrer_id',))['referrer_id'] if found else None
    if referrer == user_id:
        referrer = None
    ids = sorted({user_id, referrer} - {None})
    await cur.execute('SELECT id FROM users WHERE id IN (' + ','.join(['%s'] * len(ids)) + ') ORDER BY id FOR UPDATE', tuple(ids))
    existing = {row(item, ('id',))['id'] for item in await cur.fetchall()}
    return referrer if referrer in existing else None


async def _award(cur, user_id, referrer, kind, provider, reference, base, rate, amount, values=None):
    if referrer is None or referrer == user_id:
        return None
    key = event_key(kind, provider, reference)
    requested = amount
    values = values or await read_settings(cur, lock=True)
    amount, reason, day = await allocation(cur, referrer, requested, values)
    await cur.execute('''INSERT IGNORE INTO referral_rewards
        (event_key,kind,provider,reference,user_id,referrer_id,base_amount,rate,amount,requested_amount,limit_reason,reward_day,created_at)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,UTC_TIMESTAMP())''', (key, kind, provider, str(reference), user_id, referrer, base, rate, amount, requested, reason, day))
    if cur.rowcount != 1:
        return None
    if amount:
        await cur.execute('UPDATE referral_daily_totals SET issued=issued+%s WHERE referrer_id=%s AND reward_day=%s', (amount, referrer, day))
        await cur.execute('UPDATE users SET balance=balance+%s WHERE id=%s', (amount, referrer))
        await cur.execute("INSERT INTO payment_logs(user_id,amount,currency,method,reference) VALUES(%s,%s,'RUB',%s,%s)", (referrer, amount, 'referral_' + kind, key))
    return amount


async def credit_deposit(cur, user_id, referrer, amount, provider, reference):
    if referrer is None:
        return None
    values = await read_settings(cur, lock=True)
    base = Decimal(str(amount))
    bonus = (base * values['deposit_pct'] / 100).quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
    return await _award(cur, user_id, referrer, 'deposit', provider, reference, base, values['deposit_pct'], bonus, values)


async def reverse_deposit(cur, user_id, provider, reference):
    key = event_key('deposit', provider, reference)
    await cur.execute('SELECT * FROM referral_rewards WHERE event_key=%s FOR UPDATE', (key,))
    found = await cur.fetchone()
    if not found:
        return None
    # Used from Stars' DictCursor after participant wallets have been locked.
    if found['user_id'] != user_id:
        raise ValueError('Referral payment owner mismatch')
    if found['reversed']:
        return None
    amount = Decimal(str(found['amount']))
    if amount:
        await cur.execute('UPDATE users SET balance=balance-%s WHERE id=%s', (amount, found['referrer_id']))
        await cur.execute("INSERT INTO payment_logs(user_id,amount,currency,method,reference) VALUES(%s,%s,'RUB','referral_reversal',%s)", (found['referrer_id'], -amount, key))
    await cur.execute('UPDATE referral_rewards SET reversed=1,reversed_at=UTC_TIMESTAMP() WHERE event_key=%s', (key,))
    return amount


async def register_user(user_id, referrer_id, username=None):
    if type(user_id) is not int or user_id <= 0:
        raise ValueError(tr('Некорректный пользователь.'))
    clean = username.lstrip('@').strip() if username else None
    async with _transaction() as cur:
        await cur.execute('INSERT IGNORE INTO users(id,balance,balance_usdt,username) VALUES(%s,0,0,%s)', (user_id, clean))
        new = cur.rowcount == 1
        if not new:
            if clean:
                await cur.execute('UPDATE users SET username=%s WHERE id=%s', (clean, user_id))
            return
        if type(referrer_id) is not int or not 0 < referrer_id <= 9223372036854775807 or referrer_id == user_id:
            return
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (referrer_id,))
        if not await cur.fetchone():
            return
        await cur.execute('INSERT INTO referrals(referral_id,referrer_id) VALUES(%s,%s)', (user_id, referrer_id))
        values = await read_settings(cur, lock=True)
        await _award(cur, user_id, referrer_id, 'signup', 'telegram', str(user_id), Decimal(0), Decimal(0), values['signup_bonus'], values)


async def summary(user_id):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            values = await read_settings(cur)
            await cur.execute('SELECT COUNT(*) AS count FROM referrals WHERE referrer_id=%s', (user_id,))
            count = (await cur.fetchone())['count']
            await cur.execute('SELECT COALESCE(SUM(CASE WHEN reversed=0 THEN amount ELSE 0 END),0) AS earned FROM referral_rewards WHERE referrer_id=%s', (user_id,))
            earned = Decimal(str((await cur.fetchone())['earned']))
            await cur.execute("SELECT COALESCE(SUM(p.referral_bonus),0) AS earned FROM purchases p WHERE p.referrer_id=%s AND p.status<>'refunded' AND p.currency='RUB' AND NOT EXISTS(SELECT 1 FROM referral_rewards r WHERE r.kind='purchase' AND r.provider='shop' AND BINARY r.reference=BINARY CAST(p.id AS CHAR))", (user_id,))
            earned += Decimal(str((await cur.fetchone())['earned']))
            day = reward_day()
            await cur.execute('SELECT issued FROM referral_daily_totals WHERE referrer_id=%s AND reward_day=%s', (user_id, day))
            found = await cur.fetchone()
            issued = Decimal(str(found['issued'])) if found else await historical_issued(cur, user_id, day)
            await cur.execute('SELECT blocked FROM referral_blocks WHERE user_id=%s', (user_id,))
            found = await cur.fetchone()
            blocked = bool(found and found['blocked'])
            return {'count': count, 'earned': str(earned), 'settings': {key: str(value) for key, value in values.items()},
                    'daily': {'day': str(day), 'limit': str(values['daily_limit']), 'issued': str(issued),
                              'remaining': str(max(Decimal(0), values['daily_limit'] - issued)), 'blocked': blocked}}
