import logging
import aiohttp

from config import LAVE_PAY_API_KEY

BASE_URL = "https://laveshka.io/merchant/v1"


async def _request(method: str, path: str, payload: dict | None = None) -> dict | None:
    if not LAVE_PAY_API_KEY:
        logging.error("[lavepay] LAVE_PAY_API_KEY is not configured")
        return None

    headers = {
        "X-Api-Key": LAVE_PAY_API_KEY,
        "Content-Type": "application/json",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                f"{BASE_URL}{path}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                body = await response.json(content_type=None)
                if response.status < 200 or response.status >= 300:
                    logging.warning("[lavepay] API error %s: %s", response.status, body)
                    return None
                if not body.get("ok"):
                    logging.warning("[lavepay] API rejected request: %s", body)
                    return None
                return body.get("data")
    except Exception as exc:
        logging.exception("[lavepay] Request failed: %s", exc)
        return None


async def create_invoice(amount_usd: float, description: str, order_id: str, payload: str, ttl: int = 3600) -> dict | None:
    return await _request(
        "POST",
        "/invoices",
        {
            "amount": f"{amount_usd:.2f}",
            "description": description[:256],
            "order_id": order_id,
            "payload": payload,
            "ttl": ttl,
        },
    )


async def get_invoice(invoice_id: str | int) -> dict | None:
    return await _request("GET", f"/invoices/{invoice_id}")


def is_paid(invoice: dict | None) -> bool:
    return bool(invoice and str(invoice.get("status", "")).lower() == "paid")
