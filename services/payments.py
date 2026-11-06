"""Authenticated provider polling; every invoice is credited by the atomic DB path."""
from utils.i18n import tr
import asyncio
from decimal import Decimal, InvalidOperation
import logging
from urllib.parse import urlsplit
from uuid import uuid4

import config
from database import commerce, db
from services import cryptopay, xrocket, lavepay, platega
from utils.commerce_policy import MAX_NEW_STARS
from services.exchange import convert_rub_to_usdt
from services.operations import payment_health

logger=logging.getLogger(__name__)
PROVIDERS={'crypto':cryptopay,'xrocket':xrocket,'lave':lavepay,'platega':platega}


def methods(*, sbp_stub=False):
    return [{'id':key,'name':name,'enabled':bool(getattr(config,variable,'')),'currency':'RUB','min':10,'max':1000000} for key,name,variable in [
        ('crypto','Crypto Pay','CRYPTO_PAY_TOKEN'),('xrocket','xRocket','XROCKET_API_KEY'),('lave','Laveshka (Lava Pay)','LAVE_PAY_API_KEY')]] + [{'id':'platega','name':tr('СБП · Рубли'),'enabled':sbp_stub or bool(getattr(config,'PLATEGA_MERCHANT_ID','') and getattr(config,'PLATEGA_SECRET','')),'currency':'RUB','min':1,'max':10000,'stub':sbp_stub}] + [{'id':'stars','name':'Telegram Stars ⭐','enabled':bool(getattr(config,'BOT_TOKEN','')),'unit':'XTR','rate':'1.20','min':1,'max':MAX_NEW_STARS}]


class PaymentUnavailable(ValueError):
    code = 'payment_unavailable'


async def sbp_stub_enabled():
    return await db.get_setting('platega_stub', '1') == '1'


async def get_methods():
    return methods(sbp_stub=await sbp_stub_enabled())


def invoice_payload(provider, invoice):
    if provider=='xrocket':
        if isinstance(invoice.get('payload'),str): return invoice['payload']
        callback=invoice.get('callback') or {}
        value=callback.get('payload') or {}
        return str(value.get('orderId','')) if isinstance(value,dict) else str(value)
    return str(invoice.get('payload',''))


def parse_amount(value, provider=None):
    minimum, maximum = (Decimal('1'), Decimal('10000')) if provider == 'platega' else (Decimal('10'), Decimal('1000000'))
    try:
        if isinstance(value, bool) or len(str(value)) > 40:
            raise ValueError
        amount = Decimal(str(value).strip().replace('\xa0', '').replace(' ', '').replace(',', '.'))
        if not amount.is_finite() or not minimum <= amount <= maximum or amount != amount.quantize(Decimal('.01')):
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValueError(tr('Сумма должна быть от {0} до {1} ₽, до двух знаков после запятой.', '1' if provider == 'platega' else '10', '10 000' if provider == 'platega' else '1 000 000')) from None
    return amount


async def create_deposit(user_id, username, provider, amount):
    amount = parse_amount(amount, provider)
    if provider == 'platega' and await sbp_stub_enabled():
        raise PaymentUnavailable(tr('Оплата через СБП временно недоступна. Попробуйте позже или выберите другой способ оплаты.'))
    if provider not in PROVIDERS or not next((method['enabled'] for method in methods() if method['id'] == provider)):
        raise ValueError(tr('Этот платёжный сервис пока не настроен.'))
    payload = f'rub_topup:{user_id}:{amount:.2f}'
    order_id = f'topup-{user_id}-{uuid4().hex}'
    if provider == 'crypto':
        invoice = await cryptopay.create_invoice(float(amount), f'Пополнение на {amount:.2f} ₽', payload)
        invoice_id = invoice.get('invoice_id') if invoice else None
        url = invoice.get('bot_invoice_url') if invoice else None
    elif provider == 'platega':
        invoice = await platega.create_invoice(amount, f'Пополнение SBAND ACCS на {amount:.2f} ₽', payload, user_id)
        invoice_id = invoice.get('id') if invoice else None
        url = invoice.get('pay_url') if invoice else None
    elif provider == 'xrocket':
        invoice = await xrocket.create_invoice(await convert_rub_to_usdt(float(amount)), f'Пополнение на {amount:.2f} ₽', order_id, payload, user_id, username)
        invoice_id = invoice.get('id') if invoice else None
        url = (invoice.get('links') or {}).get('telegramBotLink') or invoice.get('link') if invoice else None
    else:
        invoice = await lavepay.create_invoice(await convert_rub_to_usdt(float(amount)), f'Пополнение на {amount:.2f} ₽', order_id, payload)
        invoice_id = invoice.get('id') if invoice else None
        url = invoice.get('pay_url') if invoice else None
    if not invoice_id or not isinstance(url, str) or urlsplit(url).scheme != 'https' or (not urlsplit(url).hostname) or urlsplit(url).username or urlsplit(url).password or (len(str(invoice_id)) > 128):
        await _health(provider, False)
        raise ValueError(tr('Платёжный сервис не вернул корректный счёт. Попробуйте позже.'))
    await commerce.register_invoice(provider, str(invoice_id), user_id, amount)
    await _health(provider, True)
    return {'provider': provider, 'invoice_id': str(invoice_id), 'pay_url': url, 'amount': str(amount)}


async def check_invoice(user_id, provider, invoice_id):
    if provider not in PROVIDERS or not isinstance(invoice_id, str) or (not 1 <= len(invoice_id) <= 128):
        raise ValueError(tr('Некорректный счёт.'))
    row = await commerce.invoice(provider, invoice_id, user_id)
    if not row:
        raise ValueError(tr('Счёт не найден в ваших платежах. Если вы уже оплатили старый счёт, обратитесь в поддержку.'))
    if row['status'] in {'credited', 'expired'}:
        return {'status': row['status'], 'credited': None}
    result = await PROVIDERS[provider].get_invoice(invoice_id)
    if not isinstance(result, dict) or result.get('_xrocket_error'):
        await _health(provider, False)
        raise ValueError(tr('Сервис пока не подтвердил статус. Повторите проверку позже.'))
    credited = await settle_invoice(row, result)
    await _health(provider, True)
    if credited:
        return {'status': 'credited', 'credited': credited}
    current = await commerce.invoice(provider, invoice_id, user_id)
    return {'status': current['status'] if current else 'pending', 'credited': None}


async def settle_invoice(row, invoice):
    provider=row['provider']
    if provider == 'platega' and platega.identity(invoice.get('id')) != str(row['invoice_id']):
        raise ValueError('Invoice identity mismatch')
    if not PROVIDERS[provider].is_paid(invoice):
        if str(invoice.get('status','')).lower() in {'expired','cancelled','canceled'}:
            await commerce.finish_invoice(provider,row['invoice_id'],'expired')
        return None
    reported=platega.identity(invoice.get('id')) if provider=='platega' else invoice.get('invoice_id' if provider=='crypto' else 'id')
    if reported is None or str(reported)!=str(row['invoice_id']):
        raise ValueError('Invoice identity mismatch')
    if provider == 'platega':
        platega.verify(invoice, row)
    payload=invoice_payload(provider,invoice)
    try:
        prefix,user,amount=payload.split(':')
        valid=(prefix=='rub_topup' and int(user)==row['user_id'] and Decimal(amount)==Decimal(str(row['amount_rub'])))
    except (ValueError,InvalidOperation):
        valid=False
    if not valid:
        raise ValueError('Invoice owner or amount mismatch')
    credited=await db.credit_paid_deposit(row['user_id'],row['amount_rub'],provider,row['invoice_id'])
    try:
        await commerce.finish_invoice(provider,row['invoice_id'],'credited',credited[0] if credited else None)
    except Exception:
        # A retry reconciles the marker; it must not claim that a committed credit failed.
        logger.error('Invoice state reconciliation deferred for %s',provider)
    return credited


async def _health(provider,ok):
    try:
        await payment_health(provider,ok)
    except Exception:
        logger.warning('Payment health state not saved')


async def check_pending(bot):
    for row in await commerce.pending_invoices():
        if row['provider'] not in PROVIDERS or not await commerce.lease_invoice(row['provider'],row['invoice_id']):
            continue
        try:
            invoice=await PROVIDERS[row['provider']].get_invoice(row['invoice_id'])
            if not isinstance(invoice,dict) or invoice.get("_xrocket_error"):
                await _health(row["provider"],False)
                continue
            credited=await settle_invoice(row,invoice)
            await _health(row["provider"],True)
            if credited:
                try:
                    from utils.notification_language import send_translated
                    await send_translated(bot,row['user_id'],'✅ Оплата подтверждена автоматически. На баланс зачислено {0} ₽.',f'{credited[0]:.2f}')
                except Exception:
                    logger.warning('Payment receipt notification not delivered')
        except Exception:
            try:
                await _health(row['provider'],False)
            except Exception:
                pass
            logger.error('Automatic invoice check failed for provider %s',row['provider'])


async def payment_worker(bot):
    while True:
        try:
            await check_pending(bot)
        except Exception:
            logger.error('Payment polling batch failed')
        await asyncio.sleep(15)
