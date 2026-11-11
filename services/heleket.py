"""Heleket payment API; exact-byte signatures and authenticated polling only.

Contract: official @heleket-payment/sdk 0.1.0 (Heleket/nodejs-sdk).
Redirects and browser callbacks never credit a wallet.
"""
import base64
import hashlib
import json
import logging
from decimal import Decimal, InvalidOperation
from uuid import UUID
from urllib.parse import urlsplit

import aiohttp
import config

BASE_URL = 'https://api.heleket.com'
logger = logging.getLogger(__name__)


def identity(value):
    try:
        return str(UUID(value)) if isinstance(value, str) and str(UUID(value)) == value.lower() else None
    except ValueError:
        return None


async def _request(path, payload):
    merchant = getattr(config, 'HELEKET_MERCHANT_ID', '')
    key = getattr(config, 'HELEKET_PAYMENT_KEY', '')
    if not merchant or not key:
        return None
    body = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    signature = hashlib.md5(base64.b64encode(body) + key.encode('utf-8')).hexdigest()
    headers = {'merchant': merchant, 'sign': signature, 'Content-Type': 'application/json', 'Accept': 'application/json'}
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request('POST', BASE_URL + path, headers=headers, data=body, allow_redirects=False) as reply:
                if not 200 <= reply.status < 300:
                    logger.warning('Heleket returned HTTP %s', reply.status)
                    return None
                data = await reply.json(content_type=None)
                if not isinstance(data, dict) or type(data.get('state')) is not int or data['state'] != 0 or not isinstance(data.get('result'), dict):
                    logger.warning('Heleket rejected the response')
                    return None
                return data['result']
    except Exception:
        logger.warning('Heleket request failed')
        return None


def normalise(invoice):
    if not isinstance(invoice, dict) or not identity(invoice.get('uuid')):
        return None
    return {**invoice, 'id': identity(invoice['uuid']), 'pay_url': invoice.get('url'),
            'payload': invoice.get('additional_data'),
            'status': invoice.get('payment_status') or invoice.get('status')}


async def create_invoice(amount, order_id, payload):
    amount = Decimal(str(amount))
    if not amount.is_finite() or not Decimal('50') <= amount <= Decimal('1000000') or amount != amount.quantize(Decimal('.01')):
        raise ValueError('Invalid Heleket amount')
    body = {'amount': f'{amount:.2f}', 'currency': 'RUB', 'order_id': order_id,
            'additional_data': payload, 'lifetime': 3600, 'accuracy_payment_percent': '0'}
    return_url = getattr(config, 'MINIAPP_URL', '')
    parsed = urlsplit(return_url)
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
        body['url_return'] = return_url
    return normalise(await _request('/v1/payment', body))


async def get_invoice(invoice_id):
    value = identity(invoice_id)
    if not value:
        return None
    result = normalise(await _request('/v1/payment/info', {'uuid': value}))
    return result if result and result['id'] == value else None


def is_paid(invoice):
    return isinstance(invoice, dict) and invoice.get('status') in {'paid', 'paid_over'} and invoice.get('is_final') is True


def verify(invoice, row):
    try:
        actual = Decimal(str(invoice['amount']))
        valid = actual.is_finite() and actual == Decimal(str(row['amount_rub'])) and invoice.get('currency') == 'RUB'
    except (KeyError, InvalidOperation, ValueError):
        valid = False
    if not valid:
        raise ValueError('Heleket amount or currency mismatch')
