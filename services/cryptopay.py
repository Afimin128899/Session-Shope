"""Crypto Pay fiat-RUB invoices; HTTP/envelope failures never become payments."""
import logging
import math

import aiohttp

from config import CRYPTO_PAY_TOKEN

BASE_URL = 'https://pay.crypt.bot/api'
logger = logging.getLogger(__name__)


async def _request(method, path, payload=None, params=None):
    if not CRYPTO_PAY_TOKEN:
        logger.warning('Crypto Pay API token is not configured')
        return None
    headers = {'Crypto-Pay-API-Token': CRYPTO_PAY_TOKEN, 'Accept': 'application/json', 'Content-Type': 'application/json'}
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request(method, BASE_URL + path, headers=headers, json=payload, params=params, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    logger.warning('Crypto Pay returned HTTP %s', response.status)
                    return None
                data = await response.json(content_type=None)
                if not isinstance(data, dict) or data.get('ok') is not True:
                    logger.warning('Crypto Pay returned an invalid or rejected response')
                    return None
                return data.get('result')
    except Exception:
        logger.warning('Crypto Pay request failed')
        return None


async def create_invoice(amount_rub, description, payload):
    try:
        amount = float(amount_rub)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(amount_rub, bool) or not math.isfinite(amount) or amount <= 0:
        return None
    return await _request('POST', '/createInvoice', {
        'currency_type': 'fiat', 'fiat': 'RUB', 'amount': f'{amount:.2f}',
        'description': description[:1024], 'payload': payload, 'expires_in': 3600,
        'allow_comments': False, 'allow_anonymous': False,
    })


async def get_invoice(invoice_id):
    if isinstance(invoice_id, bool) or not isinstance(invoice_id, (str, int)) or not 1 <= len(str(invoice_id)) <= 128:
        return None
    result = await _request('GET', '/getInvoices', params={'invoice_ids': str(invoice_id), 'count': 1})
    if isinstance(result, dict):
        result = result.get('items', [])
    if isinstance(result, list):
        return next((invoice for invoice in result if isinstance(invoice, dict) and str(invoice.get('invoice_id')) == str(invoice_id)), None)
    return None


def is_paid(invoice):
    return isinstance(invoice, dict) and str(invoice.get('status', '')).lower() == 'paid'
