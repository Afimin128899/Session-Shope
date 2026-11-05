"""Native Stars invoices and disk-backed replay of trusted Telegram receipts."""
from utils.i18n import tr
import asyncio
from contextlib import suppress
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
from aiogram.types import LabeledPrice
from database import stars as ledger

logger=logging.getLogger(__name__)


def fields(row):
    return dict(title=tr('Пополнение Sband ACCS'),description=tr('{0} ⭐ → {1} ₽. Курс: 1 ⭐ = 1,20 ₽.', row['stars'],row['amount']),payload='sband_stars:'+row['invoice_id'],currency='XTR',provider_token='',prices=[LabeledPrice(label=tr('Пополнение баланса'),amount=row['stars'])])


async def create_invoice(bot, user_id, count):
    if bot is None:
        raise ValueError(tr('Откройте оплату в Telegram-боте.'))
    row = await ledger.register_invoice(user_id, ledger.parse_count(count))
    url = await bot.create_invoice_link(**fields(row))
    from urllib.parse import urlsplit
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in {'t.me', 'telegram.me'} or parsed.username or parsed.password:
        raise ValueError(tr('Telegram не вернул ссылку на оплату.'))
    return {'provider': 'stars', 'invoice_id': row['invoice_id'], 'pay_url': url, 'amount': row['amount'], 'stars': row['stars'], 'rate': '1.20', 'currency': 'XTR'}


async def send_invoice(bot,user_id,count):
    row=await ledger.register_invoice(user_id,ledger.parse_count(count))
    await bot.send_invoice(chat_id=user_id,start_parameter='sband_stars',**fields(row))
    return row


def directory():
    return Path(os.getenv('STARS_RECEIPTS_DIR','data/star-receipts'))


def save_receipt(event):
    root=directory();root.mkdir(mode=0o700,parents=True,exist_ok=True)
    target=root/(hashlib.sha256((event['kind']+':'+event['charge_id']).encode()).hexdigest()+'.json')
    descriptor,name=tempfile.mkstemp(prefix='.receipt-',dir=root)
    try:
        with os.fdopen(descriptor,'w') as handle:
            json.dump(event,handle);handle.flush();os.fsync(handle.fileno())
        os.replace(name,target)
        descriptor=os.open(root,os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)
    finally:
        with suppress(FileNotFoundError): os.unlink(name)
    return target


async def apply(event):
    if event['kind']=='paid': return await ledger.credit_payment(event['user_id'],event['invoice_id'],event['stars'],event['charge_id'])
    if event['kind']=='refunded': return await ledger.refund_payment(event['invoice_id'],event['stars'],event['charge_id'],user_id=event['user_id'])
    raise ValueError('Invalid receipt')


async def accept(event):
    path=await asyncio.to_thread(save_receipt,event)
    amount=await apply(event)
    await asyncio.to_thread(path.unlink,missing_ok=True)
    return amount


async def replay(bot):
    if not directory().exists(): return
    for path in sorted(directory().glob('*.json'),key=lambda p:p.stat().st_mtime)[:100]:
        try:
            event=json.loads(await asyncio.to_thread(path.read_text))
            amount=await apply(event)
            await asyncio.to_thread(path.unlink,missing_ok=True)
        except Exception:
            with suppress(OSError): await asyncio.to_thread(os.utime,path,None)
            logger.warning('Stars receipt replay deferred')
            continue
        if amount is not None and event['kind']=='paid':
            from utils.notification_language import send_translated
            with suppress(Exception): await send_translated(bot,event['user_id'],'⭐ Зачислено {0} ₽.',f'{amount:.2f}')


async def stars_worker(bot):
    while True:
        try: await replay(bot)
        except Exception: logger.warning('Stars replay unavailable')
        await asyncio.sleep(10)
