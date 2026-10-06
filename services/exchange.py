import logging

from config import TON_FALLBACK_RATE, USDT_FALLBACK_RATE


async def get_ton_usdt_rate() -> float:
    """Fetch TON/USDT rate from CryptoBot API. Falls back to public API, then TON_FALLBACK_RATE on failure."""
    from services.cryptobot import get_exchange_rates
    rate = None
    try:
        rates = await get_exchange_rates()
        if rates:
            for r in rates:
                if r.get("source") == "TON" and r.get("target") == "USDT":
                    rate = float(r["rate"])
                    break
    except Exception as e:
        logging.warning(f"[exchange] Failed to fetch TON/USDT rate from CryptoBot: {e}")

    # Если курс не получен или равен 1.0 (что говорит о неактивном мерчанте/заглушке)
    if rate is None or rate == 1.0:
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get("https://min-api.cryptocompare.com/data/price?fsym=TON&tsyms=USDT", timeout=3) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        val = float(data.get("USDT", 0))
                        if val > 0:
                            logging.info(f"[exchange] Fetched public TON/USDT rate: {val}")
                            return val
        except Exception as e:
            logging.warning(f"[exchange] Failed to fetch public rate from Cryptocompare: {e}")

    if rate is not None:
        return rate

    # В крайнем случае используем реалистичный хардкод, если даже конфиг равен 1.0
    fallback = TON_FALLBACK_RATE if TON_FALLBACK_RATE != 1.0 else 5.5
    logging.warning(f"[exchange] Using fallback TON/USDT rate: {fallback}")
    return fallback


async def get_usdt_ton_rate() -> float:
    """Fetch USDT/TON rate from CryptoBot API. Falls back to USDT_FALLBACK_RATE on failure."""
    from services.cryptobot import get_exchange_rates
    try:
        rates = await get_exchange_rates()
        if rates:
            for r in rates:
                if r.get("source") == "USDT" and r.get("target") == "TON":
                    return float(r["rate"])
    except Exception as e:
        logging.warning(f"[exchange] Failed to fetch USDT/TON rate: {e}")

    # Вычисляем обратный курс из полученного TON/USDT
    rate = await get_ton_usdt_rate()
    if rate > 0:
        return round(1.0 / rate, 8)

    fallback = USDT_FALLBACK_RATE if USDT_FALLBACK_RATE != 1.0 else 0.18
    logging.warning(f"[exchange] Using fallback USDT/TON rate: {fallback}")
    return fallback


async def convert_to_ton(amount: float, asset: str) -> float:
    """Convert an amount in the given asset to TON, rounded to 8 decimal places.

    Supported assets:
    - "TON"  — returned as-is (rounded to 8 dp)
    - "USDT" — converted via TON/USDT rate
    - other  — looks up asset->TON rate from CryptoBot, then tries asset->USDT->TON;
               returns 0.0 with a warning if no rate is found.
    """
    if asset == "TON":
        return round(amount, 8)

    if asset == "USDT":
        rate = await get_ton_usdt_rate()  # TON price in USDT; amount USDT / rate = TON
        if rate == 0:
            logging.warning("[exchange] TON/USDT rate is 0, cannot convert")
            return 0.0
        return round(amount / rate, 8)

    # Generic: try to find asset->TON or asset->USDT->TON
    from services.cryptobot import get_exchange_rates
    try:
        rates = await get_exchange_rates()
        if rates:
            # Direct asset->TON pair
            for r in rates:
                if r.get("source") == asset and r.get("target") == "TON":
                    return round(amount * float(r["rate"]), 8)

            # Two-hop: asset->USDT then USDT->TON
            asset_usdt = None
            for r in rates:
                if r.get("source") == asset and r.get("target") == "USDT":
                    asset_usdt = float(r["rate"])
                    break
            if asset_usdt:
                usdt_ton = await get_usdt_ton_rate()
                return round(amount * asset_usdt * usdt_ton, 8)
    except Exception as e:
        logging.warning(f"[exchange] Failed to convert {asset} to TON: {e}")

    logging.warning(f"[exchange] Cannot convert {asset} to TON, returning 0.0")
    return 0.0


async def get_rub_usdt_rate() -> float:
    """Возвращает курс 1 USDT ($) в Рублях (₽). По умолчанию 100.0."""
    from config import USDT_RUB_RATE
    try:
        from services.cryptobot import get_exchange_rates
        rates = await get_exchange_rates()
        if rates:
            for r in rates:
                if (r.get("source") == "USDT" and r.get("target") == "RUB") or (r.get("source") == "USD" and r.get("target") == "RUB"):
                    val = float(r["rate"])
                    if val > 0:
                        return val
    except Exception as e:
        logging.warning(f"[exchange] Failed to fetch USDT/RUB rate from CryptoBot: {e}")

    return USDT_RUB_RATE if USDT_RUB_RATE > 0 else 100.0


async def convert_rub_to_usdt(rub_amount: float) -> float:
    """Конвертирует сумму в Рублях (₽) в USDT ($)."""
    rate = await get_rub_usdt_rate()
    if rate <= 0:
        rate = 100.0
    return round(rub_amount / rate, 2)
