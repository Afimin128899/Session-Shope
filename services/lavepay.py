"""Laveshka merchant API, following the published laveshka-wallet/lave-pay SDK."""
import logging
import math
from urllib.parse import quote

import aiohttp

from config import LAVE_PAY_API_KEY

BASE_URL = 'https://api.laveshka.io/merchant/v1'
logger = logging.getLogger(__name__)


async def _request(method, path, payload=None):
    if not LAVE_PAY_API_KEY:
        logger.warning('Laveshka merchant API key is not configured')
        return None
    headers = {'X-Api-Key': LAVE_PAY_API_KEY, 'Accept': 'application/json', 'Content-Type': 'application/json'}
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request(method, BASE_URL + path, headers=headers, json=payload, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    logger.warning('Laveshka returned HTTP %s', response.status)
                    return None
                body = await response.json(content_type=None)
                if not isinstance(body, dict) or body.get('ok') is not True:
                    logger.warning('Laveshka returned an invalid or rejected response')
                    return None
                data = body.get('data')
                return data if isinstance(data, dict) else None
    except Exception:
        logger.warning('Laveshka request failed')
        return None


async def create_invoice(amount_usd, description, order_id, payload, ttl=3600):
    try:
        amount = float(amount_usd)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(amount_usd, bool) or not math.isfinite(amount) or amount <= 0:
        return None
    return await _request('POST', '/invoices', {
        'amount': f'{amount:.2f}', 'currency': 'USD', 'description': description[:256],
        'order_id': order_id, 'payload': payload, 'ttl': ttl,
    })


async def get_invoice(invoice_id):
    if isinstance(invoice_id, bool) or not isinstance(invoice_id, (str, int)) or not 1 <= len(str(invoice_id)) <= 128 or str(invoice_id) in {'.', '..'}:
        return None
    return await _request('GET', '/invoices/' + quote(str(invoice_id), safe=''))


def is_paid(invoice):
    return isinstance(invoice, dict) and str(invoice.get('status', '')).lower() == 'paid'
