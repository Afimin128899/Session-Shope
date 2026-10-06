import logging
import aiohttp

from config import XROCKET_API_KEY

BASE_URL = "https://pay.xrocket.tg/api/v1"


async def _request(method: str, path: str, payload: dict | None = None):
    if not XROCKET_API_KEY:
        logging.error("[xrocket] XROCKET_API_KEY is not configured")
        return None

    headers = {"Authorization": f"Bearer {XROCKET_API_KEY}"}
    async with aiohttp.ClientSession() as session:
        async with session.request(method, f"{BASE_URL}{path}", headers=headers, json=payload) as r:
            data = await r.json()
            return data


async def create_invoice(amount: float, description: str, payload: str):
    return await _request("POST", "/invoice", {
        "amount": amount,
        "currency": "RUB",
        "description": description,
        "payload": payload,
    })


async def get_invoice(invoice_id: str):
    return await _request("GET", f"/invoice/{invoice_id}")
