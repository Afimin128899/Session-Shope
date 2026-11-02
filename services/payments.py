"""Authenticated provider polling; every invoice is credited by the atomic DB path."""
import asyncio
from decimal import Decimal, InvalidOperation
import logging
from urllib.parse import urlsplit
from uuid import uuid4

import config
from database import commerce, db
from services import cryptopay, xrocket, lavepay
from services.exchange import convert_rub_to_usdt
from services.operations import payment_health

logger=logging.getLogger(__name__)
PROVIDERS={'crypto':cryptopay,'xrocket':xrocket,'lave':lavepay}


def methods():
    return [{'id':key,'name':name,'enabled':bool(getattr(config,variable,''))} for key,name,variable in [
        ('crypto','Crypto Pay','CRYPTO_PAY_TOKEN'),('xrocket','xRocket','XROCKET_API_KEY'),('lave','Lave Pay','LAVE_PAY_API_KEY')]]


def invoice_payload(provider, invoice):
    if provider=='xrocket':
        callback=invoice.get('callback') or {}
        value=callback.get('payload') or {}
        return str(value.get('orderId','')) if isinstance(value,dict) else str(value)
    return str(invoice.get('payload',''))


async def create_deposit(user_id, username, provider, amount):
    try:
        amount=Decimal(str(amount))
        if not amount.is_finite() or not Decimal('10')<=amount<=Decimal('1000000') or amount!=amount.quantize(Decimal('.01')):
            raise ValueError
    except (InvalidOperation,ValueError):
        raise ValueError('Сумма должна быть от 10 до 1 000 000 ₽, до двух знаков после запятой.') from None
    if provider not in PROVIDERS or not next(method['enabled'] for method in methods() if method['id']==provider):
        raise ValueError('Этот платёжный сервис пока не настроен.')
    payload=f'rub_topup:{user_id}:{amount:.2f}'
    order_id=f'topup-{user_id}-{uuid4().hex}'
    if provider=='crypto':
        invoice=await cryptopay.create_invoice(float(amount),f'Пополнение на {amount:.2f} ₽',payload)
        invoice_id=invoice.get('invoice_id') if invoice else None
        url=invoice.get('bot_invoice_url') if invoice else None
    elif provider=='xrocket':
        invoice=await xrocket.create_invoice(await convert_rub_to_usdt(float(amount)),f'Пополнение на {amount:.2f} ₽',order_id,payload,user_id,username)
        invoice_id=invoice.get('id') if invoice else None
        url=(invoice.get('links') or {}).get('telegramBotLink') if invoice else None
    else:
        invoice=await lavepay.create_invoice(await convert_rub_to_usdt(float(amount)),f'Пополнение на {amount:.2f} ₽',order_id,payload)
        invoice_id=invoice.get('id') if invoice else None
        url=invoice.get('pay_url') if invoice else None
    if not invoice_id or not isinstance(url,str) or urlsplit(url).scheme!='https' or not urlsplit(url).hostname or urlsplit(url).username or urlsplit(url).password or len(str(invoice_id))>128:
        await _health(provider,False)
        raise ValueError('Платёжный сервис не вернул корректный счёт. Попробуйте позже.')
    await commerce.register_invoice(provider,str(invoice_id),user_id,amount)
    await _health(provider,True)
    return {'provider':provider,'invoice_id':str(invoice_id),'pay_url':url,'amount':str(amount)}


async def settle_invoice(row, invoice):
    provider=row['provider']
    if not PROVIDERS[provider].is_paid(invoice):
        if str(invoice.get('status','')).lower() in {'expired','cancelled','canceled'}:
            await commerce.finish_invoice(provider,row['invoice_id'],'expired')
        return None
    reported=invoice.get('invoice_id' if provider=='crypto' else 'id')
    if reported is None or str(reported)!=str(row['invoice_id']):
        raise ValueError('Invoice identity mismatch')
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
                    await bot.send_message(row['user_id'],f'✅ Оплата подтверждена автоматически. На баланс зачислено {credited[0]:.2f} ₽.')
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
