import logging

import aiohttp

from config import CRYPTO_PAY_TOKEN

BASE_URL = "https://pay.crypt.bot/api"


async def _request(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    if not CRYPTO_PAY_TOKEN:
        logging.error("[cryptopay] CRYPTO_PAY_TOKEN is not configured")
        return None

    headers = {
        "Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    try:
        async with aiohttp.ClientSession(trust_env=True, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.request(
                method,
                f"{BASE_URL}{path}",
                headers=headers,
                json=payload,
                params=params,
            ) as response:
                data = await response.json(content_type=None)
                if not data.get("ok"):
                    logging.warning("[cryptopay] HTTP %s: %s", response.status, data)
                    return None
                return data.get("result")
    except Exception:
        logging.exception("[cryptopay] request failed")
        return None


async def create_invoice(amount_rub: float, description: str, payload: str):
    return await _request("POST", "/createInvoice", {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": f"{amount_rub:.2f}",
        "description": description[:1024],
        "payload": payload,
        "expires_in": 3600,
        "allow_comments": False,
        "allow_anonymous": False,
    })


async def get_invoice(invoice_id: str):
    result = await _request("GET", "/getInvoices", params={"invoice_ids": str(invoice_id), "count": 1})
    if isinstance(result, dict):
        result = result.get('items', [])
    if isinstance(result, list):
        return next((invoice for invoice in result if str(invoice.get('invoice_id')) == str(invoice_id)), None)
    return None


def is_paid(invoice: dict | None) -> bool:
    return bool(invoice and str(invoice.get("status", "")).lower() == "paid")
