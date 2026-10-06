import os
import logging
from dotenv import load_dotenv

load_dotenv()

_REQUIRED_VARS = [
    "BOT_TOKEN",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "DB_HOST",
    "DB_USER",
    "DB_PASSWORD",
    "DB_NAME",
]

missing_vars = [var for var in _REQUIRED_VARS if not os.getenv(var, "").strip()]
if missing_vars:
    raise RuntimeError(
        "Отсутствуют обязательные переменные окружения: " + ", ".join(missing_vars)
    )

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = [
    int(value.strip())
    for value in os.getenv("ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
]

LAVE_PAY_API_KEY = os.getenv("LAVE_PAY_API_KEY", "").strip()
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN", "").strip()
XROCKET_API_KEY = os.getenv("XROCKET_API_KEY", "").strip()

SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "").strip()
REVIEWS_LINK = os.getenv("REVIEWS_LINK", "").strip()
TONKEEPER_WALLET = os.getenv("TONKEEPER_WALLET", "").strip()
RUB_DETAILS = os.getenv("RUB_DETAILS", "").strip()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0").strip() or 0)
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "").strip()

DB_HOST = os.getenv("DB_HOST", "127.0.0.1").strip()
DB_PORT = int(os.getenv("DB_PORT", "3306").strip())
DB_USER = os.getenv("DB_USER", "root").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "tg_shop").strip()

DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "db": DB_NAME,
    "autocommit": True,
}

USDT_RUB_RATE = float(os.getenv("USDT_RUB_RATE", "100.0"))
TON_FALLBACK_RATE = float(os.getenv("TON_FALLBACK_RATE", "1.0"))
USDT_FALLBACK_RATE = float(os.getenv("USDT_FALLBACK_RATE", "1.0"))
