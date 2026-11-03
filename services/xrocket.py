"""xRocket adapters with explicitly selected API contracts, never POST fallback.

XROCKET_API_MODE=exchange keeps the configured exchange API contract.
XROCKET_API_MODE=tg selects the public xrocket-tg/xrocket-pay-ts-sdk contract.
"""
import logging
import math
import os
from urllib.parse import quote

import aiohttp

from config import XROCKET_API_KEY

BASE_URL = 'https://pay.api.xrocket.exchange/api/v1'
TG_BASE_URL = 'https://pay.xrocket.tg'
logger = logging.getLogger(__name__)


def _mode():
    mode = os.getenv('XROCKET_API_MODE', 'exchange').strip().lower()
    if mode not in {'exchange', 'tg'}:
        logger.warning('xRocket API mode is not configured correctly')
        return None
    return mode


async def _request(method, path, payload=None, params=None, *, mode=None):
    mode = mode or _mode()
    if not XROCKET_API_KEY or mode not in {'exchange', 'tg'}:
        logger.warning('xRocket API credentials or mode are not configured')
        return None
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    headers.update({'Rocket-Pay-Key': XROCKET_API_KEY} if mode == 'tg' else {'Authorization': f'Bearer {XROCKET_API_KEY}'})
    base = TG_BASE_URL if mode == 'tg' else BASE_URL
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request(method, base + path, headers=headers, json=payload, params=params, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    logger.warning('xRocket returned HTTP %s', response.status)
                    return None
                data = await response.json(content_type=None)
                if not isinstance(data, dict) or data.get('success') is False or data.get('ok') is False:
                    logger.warning('xRocket returned an invalid or rejected response')
                    return None
                if mode == 'tg' and data.get('success') is not True:
                    return None
                invoice = data.get('data', data)
                return invoice if isinstance(invoice, dict) else None
    except Exception:
        # API errors may include merchant secrets and token-bearing request URLs.
        logger.warning('xRocket request failed')
        return None


async def create_invoice(amount_usdt, description, client_invoice_id, payload, telegram_id, telegram_username=None):
    mode = _mode()
    if mode is None or isinstance(amount_usdt, bool):
        return None
    try:
        amount = float(amount_usdt)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(amount) or amount <= 0:
        return None
    if mode == 'tg':
        return await _request('POST', '/tg-invoices', {
            'amount': amount, 'currency': 'USDT', 'numPayments': 1,
            'description': description[:1000], 'payload': payload,
            'expiredIn': 3600, 'commentsEnabled': False,
        }, mode=mode)
    return await _request('POST', '/invoices', {
        'priceAmount': f'{amount:.6f}', 'priceCurrency': 'USDT',
        'payoutCurrency': 'USDT', 'payCurrencies': ['USDT'],
        'clientInvoiceId': client_invoice_id, 'description': description[:1000],
        'expiresIn': 3600000, 'callback': {'payload': {'orderId': payload}},
        'customer': {'telegramId': str(telegram_id), 'telegramUsername': (telegram_username or '').lstrip('@')},
    }, mode=mode)


async def get_invoice(invoice_id):
    if isinstance(invoice_id, bool) or not isinstance(invoice_id, (str, int)) or not 1 <= len(str(invoice_id)) <= 128 or str(invoice_id) in {'.', '..'}:
        return None
    mode = _mode()
    if mode is None:
        return None
    if mode == 'tg':
        return await _request('GET', '/tg-invoices/' + quote(str(invoice_id), safe=''), mode=mode)
    return await _request('GET', '/invoice', params={'invoiceId': str(invoice_id)}, mode=mode)


def is_paid(invoice):
    return isinstance(invoice, dict) and str(invoice.get('status', '')).lower() == 'paid'
