"""Platega SBP: authenticated polling only; redirect/callback never credits a wallet."""
import logging
from decimal import Decimal, InvalidOperation
from uuid import UUID

import aiohttp
import config
from utils.commerce_policy import money

BASE_URL = 'https://app.platega.io'
RETURN_URL = 'https://sbandsub.space/'
logger = logging.getLogger(__name__)


async def _request(method, path, payload=None):
    merchant = getattr(config, 'PLATEGA_MERCHANT_ID', '')
    secret = getattr(config, 'PLATEGA_SECRET', '')
    if not merchant or not secret:
        return None
    try:
        headers = {'X-MerchantId': merchant, 'X-Secret': secret, 'Content-Type': 'application/json', 'Accept': 'application/json'}
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request(method, BASE_URL + path, headers=headers, json=payload, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    logger.warning('Platega returned HTTP %s', response.status)
                    return None
                result = await response.json(content_type=None)
                return result if isinstance(result, dict) else None
    except Exception:
        # Never log request bodies, buyer identifiers, keys or provider response bodies.
        logger.warning('Platega request failed')
        return None


def identity(value):
    try:
        if not isinstance(value, str):
            return None
        return str(UUID(value)) if str(UUID(value)) == value.lower() else None
    except ValueError:
        return None


async def create_invoice(amount, description, payload, user_id):
    amount = money(amount, minimum=Decimal('1'))
    if type(user_id) is not int or not 0 < user_id <= 9223372036854775807:
        raise ValueError('Invalid Telegram payer')
    result = await _request('POST', '/transaction/process', {
        'paymentMethod': 2,
        # The merchant memo also places paymentMethod inside paymentDetails.
        # Supply the same SBP value in both positions for that contract version.
        'paymentDetails': {'paymentMethod': 2, 'amount': float(amount), 'currency': 'RUB'},
        'description': description[:256], 'return': RETURN_URL, 'failedUrl': RETURN_URL,
        'payload': payload, 'metadata': {'user_email': f'{user_id}@telegram.org'},
    })
    if not result or not identity(result.get('transactionId')):
        return None
    return {**result, 'id': identity(result['transactionId']), 'pay_url': result.get('redirect')}


async def get_invoice(invoice_id):
    value = identity(invoice_id)
    if not value:
        return None
    result = await _request('GET', '/transaction/' + value)
    return result if result and identity(result.get('id')) == value else None


def is_paid(invoice):
    return isinstance(invoice, dict) and invoice.get('status') == 'CONFIRMED'


def verify(invoice, row):
    details = invoice.get('paymentDetails')
    try:
        amount = Decimal(str(details['amount']))
        valid = (amount.is_finite() and amount == Decimal(str(row['amount_rub'])) and details.get('currency') == 'RUB')
    except (TypeError, KeyError, InvalidOperation):
        valid = False
    merchant = invoice.get('merchantId', invoice.get('mechantId'))
    if merchant is not None and str(merchant).lower() != getattr(config, 'PLATEGA_MERCHANT_ID', '').lower():
        valid = False
    if not valid:
        raise ValueError('Platega amount, currency or merchant mismatch')
