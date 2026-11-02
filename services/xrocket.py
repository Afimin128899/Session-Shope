import logging

import aiohttp

from config import XROCKET_API_KEY

BASE_URL = "https://pay.api.xrocket.exchange/api/v1"


async def _request(method: str, path: str, payload: dict | None = None, params: dict | None = None):
    if not XROCKET_API_KEY:
        logging.error("[xrocket] XROCKET_API_KEY is not configured")
        return None

    headers = {
        "Authorization": f"Bearer {XROCKET_API_KEY}",
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
                if response.status >= 400:
                    if isinstance(data, dict):
                        logging.warning(
                            "[xrocket] HTTP %s: type=%s title=%s detail=%s info=%s",
                            response.status,
                            data.get("type"),
                            data.get("title"),
                            data.get("detail"),
                            data.get("info"),
                        )
                    else:
                        logging.warning("[xrocket] HTTP %s: %s", response.status, data)
                    return {"_xrocket_error": data} if isinstance(data, dict) else None
                return data.get("data", data) if isinstance(data, dict) else data
    except Exception:
        logging.exception("[xrocket] request failed")
        return None


async def create_invoice(
    amount_usdt: float,
    description: str,
    client_invoice_id: str,
    payload: str,
    telegram_id: int,
    telegram_username: str | None = None,
):
    return await _request("POST", "/invoices", {
        "priceAmount": f"{amount_usdt:.6f}",
        "priceCurrency": "USDT",
        "payoutCurrency": "USDT",
        "payCurrencies": ["USDT"],
        "clientInvoiceId": client_invoice_id,
        "description": description[:1000],
        "expiresIn": 3600000,
        "callback": {"payload": {"orderId": payload}},
        "customer": {
            "telegramId": str(telegram_id),
            "telegramUsername": (telegram_username or "").lstrip("@"),
        },
    })


async def get_invoice(invoice_id: str):
    return await _request("GET", "/invoice", params={"invoiceId": invoice_id})


def is_paid(invoice: dict | None) -> bool:
    return bool(invoice and str(invoice.get("status", "")).lower() == "paid")
