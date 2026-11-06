"""Exactly-once Telegram Stars ledger: one Star credits exactly 1.20 RUB."""
from utils.i18n import tr
import hashlib
import re
from decimal import Decimal
from uuid import uuid4

import aiomysql

from database.admin_tools import _transaction
from database.db import _get_pool

STARS_RATE = Decimal('1.20')
MAX_STARS = 10000  # Historical receipt/reconciliation ceiling; do not discard paid invoices.
BALANCE_LIMIT = Decimal('9999999999.99999999')
PAYLOAD_PREFIX = 'sband_stars:'
_ID = re.compile(r'[0-9a-f]{32}\Z')


def parse_count(value):
    if isinstance(value, str):
        value = value.strip()
        if not value.isascii() or not value.isdecimal() or len(value) > 5:
            raise ValueError(tr('Введите целое количество звёзд от 1 до 10 000.'))
        value = int(value)
    if type(value) is not int or not 1 <= value <= MAX_STARS:
        raise ValueError(tr('Введите целое количество звёзд от 1 до 10 000.'))
    return value


def parse_new_count(value):
    return parse_count(value)


def invoice_id(payload):
    if not isinstance(payload, str) or not payload.startswith(PAYLOAD_PREFIX):
        raise ValueError(tr('Неизвестный счёт Stars.'))
    return _invoice_id(payload[len(PAYLOAD_PREFIX):])


def _invoice_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(tr('Неизвестный счёт Stars.'))
    return value


def _user_id(value):
    if type(value) is not int or not 0 < value <= 9223372036854775807:
        raise ValueError(tr('Некорректный плательщик.'))
    return value


def _charge_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 255 or any((not 33 <= ord(c) <= 126 for c in value)):
        raise ValueError(tr('Некорректный номер платежа Telegram.'))
    return value


async def init_schema(cur, database):
    await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, 'payment_invoices', 'stars_count'))
    if not await cur.fetchone():
        await cur.execute('ALTER TABLE payment_invoices ADD COLUMN stars_count INT DEFAULT NULL')
    await cur.execute('''CREATE TABLE IF NOT EXISTS star_payments (
        charge_id VARCHAR(255) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        invoice_id CHAR(32) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
        user_id BIGINT NOT NULL, stars INT NOT NULL, amount_rub DECIMAL(18,2) NOT NULL,
        paid_seen TINYINT NOT NULL DEFAULT 0, refunded_seen TINYINT NOT NULL DEFAULT 0,
        credited_amount DECIMAL(18,2) NOT NULL DEFAULT 0,
        created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
        KEY star_invoice(invoice_id), FOREIGN KEY(user_id) REFERENCES users(id)
    ) ENGINE=InnoDB''')


async def register_invoice(user_id, stars):
    user_id, stars = _user_id(user_id), parse_new_count(stars)
    identity, amount = uuid4().hex, (stars * STARS_RATE).quantize(Decimal('0.01'))
    async with _transaction() as cur:
        await cur.execute('''INSERT INTO payment_invoices
            (provider,invoice_id,user_id,amount_rub,stars_count,created_at,expires_at,next_check_at)
            VALUES('stars',%s,%s,%s,%s,UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 1 HOUR),UTC_TIMESTAMP())''', (identity, user_id, amount, stars))
    return {'invoice_id': identity, 'stars': stars, 'amount': str(amount)}


def _validate_invoice(row, user_id, stars):
    if not row or row['user_id'] != user_id or row.get('stars_count') != stars:
        raise ValueError(tr('Счёт Stars не принадлежит плательщику или сумма не совпадает.'))
    amount = stars * STARS_RATE
    if Decimal(str(row['amount_rub'])) != amount:
        raise ValueError(tr('Не удалось подтвердить курс счёта Stars.'))
    return amount


async def check_precheckout(user_id, payload, currency, total_amount):
    identity, user_id = (invoice_id(payload), _user_id(user_id))
    if currency != 'XTR' or type(total_amount) is not int:
        raise ValueError(tr('Валюта или сумма Stars не совпадает со счётом.'))
    stars = parse_new_count(total_amount)
    async with _transaction() as cur:
        await cur.execute("SELECT *,expires_at<=UTC_TIMESTAMP() AS expired FROM payment_invoices WHERE provider='stars' AND invoice_id=%s FOR UPDATE", (identity,))
        row = await cur.fetchone()
        _validate_invoice(row, user_id, stars)
        if row['expired'] or row['status'] != 'pending':
            raise ValueError(tr('Счёт уже оплачен, возвращён или истёк. Создайте новый счёт.'))
    return {'invoice_id': identity, 'stars': stars, 'amount': str(stars * STARS_RATE)}


async def charge_info(charge_id):
    charge_id = _charge_id(charge_id)
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT invoice_id,user_id,stars,amount_rub,paid_seen,refunded_seen,credited_amount FROM star_payments WHERE charge_id=%s', (charge_id,))
            return await cur.fetchone()


def _validate_charge(row, identity, user_id, stars):
    if row and (row['invoice_id'] not in (None, identity) or row['user_id'] != user_id or row['stars'] != stars or (Decimal(str(row['amount_rub'])) != stars * STARS_RATE)):
        raise ValueError(tr('Платёж Telegram уже привязан к другому счёту.'))


async def _invoice(cur, identity):
    await cur.execute("SELECT * FROM payment_invoices WHERE provider='stars' AND invoice_id=%s FOR UPDATE", (identity,))
    return await cur.fetchone()


async def _balance(cur, user_id, delta, charge_id, method):
    from database import referrals
    referrer = await referrals.lock_participants(cur, user_id, **({'reverse_provider':'stars','reference':charge_id} if delta < 0 else {}))
    await cur.execute('SELECT balance FROM users WHERE id=%s FOR UPDATE', (user_id,))
    row = await cur.fetchone()
    if not row:
        raise ValueError(tr('Плательщик не найден.'))
    after = Decimal(str(row['balance'])) + delta
    if not -BALANCE_LIMIT <= after <= BALANCE_LIMIT:
        raise ValueError(tr('Сумма превышает допустимый размер баланса.'))
    marker = method + '_' + hashlib.sha256(charge_id.encode('ascii')).hexdigest()
    await cur.execute('INSERT INTO used_transactions(comment) VALUES(%s)', (marker,))
    await cur.execute('UPDATE users SET balance=%s WHERE id=%s', (after, user_id))
    await cur.execute("INSERT INTO payment_logs(user_id,amount,currency,method,reference) VALUES(%s,%s,'RUB',%s,%s)", (user_id, delta, method, charge_id))
    if delta > 0:
        await referrals.credit_deposit(cur, user_id, referrer, delta, 'stars', charge_id)
    else:
        await referrals.reverse_deposit(cur, user_id, 'stars', charge_id)


async def _summarize(cur, identity):
    await cur.execute('SELECT COALESCE(SUM(credited_amount),0) AS total,COALESCE(MAX(refunded_seen),0) AS refunded FROM star_payments WHERE invoice_id=%s', (identity,))
    summary = await cur.fetchone()
    total = Decimal(str(summary['total']))
    status = 'credited' if total > 0 else 'refunded' if summary['refunded'] else 'pending'
    await cur.execute("UPDATE payment_invoices SET status=%s,credited_amount=%s WHERE provider='stars' AND invoice_id=%s", (status, total, identity))


async def credit_payment(user_id, invoice_id, stars, charge_id):
    identity = _invoice_id(invoice_id)
    user_id, stars, charge_id = _user_id(user_id), parse_count(stars), _charge_id(charge_id)
    async with _transaction() as cur:
        row = await _invoice(cur, identity)
        amount = _validate_invoice(row, user_id, stars)
        # Real paid receipts remain valid after invoice expiry or process restart.
        await cur.execute('SELECT * FROM star_payments WHERE charge_id=%s FOR UPDATE', (charge_id,))
        payment = await cur.fetchone()
        _validate_charge(payment, identity, user_id, stars)
        if payment and payment['paid_seen']:
            return None
        if payment and payment['refunded_seen']:
            await cur.execute('UPDATE star_payments SET invoice_id=%s,paid_seen=1,updated_at=UTC_TIMESTAMP() WHERE charge_id=%s', (identity, charge_id))
            await _summarize(cur, identity)
            return None
        await cur.execute('''INSERT INTO star_payments
            (charge_id,invoice_id,user_id,stars,amount_rub,paid_seen,credited_amount,created_at,updated_at)
            VALUES(%s,%s,%s,%s,%s,1,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP())''', (charge_id, identity, user_id, stars, amount, amount))
        await _balance(cur, user_id, amount, charge_id, 'stars_pay')
        await _summarize(cur, identity)
        return amount


async def refund_payment(invoice_id, stars, charge_id, user_id=None):
    stars, charge_id = (parse_count(stars), _charge_id(charge_id))
    if invoice_id is None:
        known = await charge_info(charge_id)
        if not known or not known['invoice_id']:
            return None
        invoice_id = known['invoice_id']
    identity = _invoice_id(invoice_id)
    async with _transaction() as cur:
        invoice = await _invoice(cur, identity)
        if not invoice:
            raise ValueError(tr('Счёт возврата Stars не найден.'))
        owner = invoice['user_id']
        if user_id is not None and _user_id(user_id) != owner:
            raise ValueError(tr('Получатель возврата не совпадает со счётом.'))
        amount = _validate_invoice(invoice, owner, stars)
        await cur.execute('SELECT * FROM star_payments WHERE charge_id=%s FOR UPDATE', (charge_id,))
        payment = await cur.fetchone()
        _validate_charge(payment, identity, owner, stars)
        if payment and payment['refunded_seen']:
            return None
        if payment:
            credited = Decimal(str(payment['credited_amount']))
            if credited:
                await _balance(cur, owner, -credited, charge_id, 'stars_refund')
            await cur.execute('UPDATE star_payments SET refunded_seen=1,credited_amount=0,updated_at=UTC_TIMESTAMP() WHERE charge_id=%s', (charge_id,))
        else:
            credited = Decimal('0')
            await cur.execute('INSERT INTO star_payments\n                (charge_id,invoice_id,user_id,stars,amount_rub,refunded_seen,created_at,updated_at)\n                VALUES(%s,%s,%s,%s,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())', (charge_id, identity, owner, stars, amount))
        await _summarize(cur, identity)
        return credited or None


async def record_unmatched_refund(user_id, stars, charge_id):
    """Remember a no-payload refund before its incoming payment is recovered."""
    user_id, stars, charge_id = _user_id(user_id), parse_count(stars), _charge_id(charge_id)
    bound_invoice = None
    async with _transaction() as cur:
        # Charge-before-user agrees with normal payment/refund lock order.
        await cur.execute('SELECT * FROM star_payments WHERE charge_id=%s FOR UPDATE', (charge_id,))
        payment = await cur.fetchone()
        if payment:
            _validate_charge(payment, payment['invoice_id'], user_id, stars)
            if payment['refunded_seen']:
                return None
            bound_invoice = payment['invoice_id']
        if bound_invoice is None:
            await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
            if not await cur.fetchone():
                return None
            if payment:
                await cur.execute('UPDATE star_payments SET refunded_seen=1,updated_at=UTC_TIMESTAMP() WHERE charge_id=%s', (charge_id,))
            else:
                await cur.execute('''INSERT INTO star_payments
                    (charge_id,invoice_id,user_id,stars,amount_rub,refunded_seen,created_at,updated_at)
                    VALUES(%s,NULL,%s,%s,%s,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())''', (charge_id, user_id, stars, stars * STARS_RATE))
    # Do not acquire an invoice lock while holding the charge lock.
    if bound_invoice is not None:
        return await refund_payment(bound_invoice, stars, charge_id, user_id=user_id)
    return None
