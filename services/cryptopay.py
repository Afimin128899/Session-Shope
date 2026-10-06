import logging
import aiohttp

from config import CRYPTO_PAY_TOKEN

BASE_URL = "https://pay.crypt.bot/api"


async def _request(method: str, path: str, payload: dict | None = None) -> dict | None:
    if not CRYPTO_PAY_TOKEN:
        logging.error("[cryptopay] CRYPTO_PAY_TOKEN is not configured")
        return None

    headers = {"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN}
    async with aiohttp.ClientSession() as session:
        async with session.request(method, f"{BASE_URL}{path}", headers=headers, json=payload) as r:
            data = await r.json()
            if data.get("ok"):
                return data.get("result")
            logging.warning("[cryptopay] %s", data)
            return None


async def create_invoice(amount: float, description: str, payload: str):
    return await _request("POST", "/createInvoice", {
        "currency_type": "fiat",
        "fiat": "RUB",
        "amount": f"{amount:.2f}",
        "description": description,
        "payload": payload,
    })


async def get_invoice(invoice_id: int):
    return await _request("GET", "/getInvoices", {"invoice_ids": invoice_id})
