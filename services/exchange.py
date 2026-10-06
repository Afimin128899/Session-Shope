import logging

from config import USDT_RUB_RATE


async def get_rub_usdt_rate() -> float:
    return USDT_RUB_RATE if USDT_RUB_RATE > 0 else 100.0


async def convert_rub_to_usdt(rub_amount: float) -> float:
    rate = await get_rub_usdt_rate()
    return round(float(rub_amount) / rate, 2)


async def convert_to_rub(amount: float, asset: str) -> float:
    asset = str(asset or "RUB").upper()
    amount = float(amount)
    if amount <= 0:
        return 0.0
    if asset == "RUB":
        return round(amount, 2)
    if asset in ("USD", "USDT"):
        return round(amount * await get_rub_usdt_rate(), 2)
    logging.warning("[exchange] Unsupported asset for RUB conversion: %s", asset)
    return 0.0
