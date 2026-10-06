from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_HASH, TELEGRAM_API_ID

def create_client(session_str: str) -> TelegramClient:
    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        raise ValueError("API_ID/HASH не найдены в конфиге")
    return TelegramClient(
        StringSession(session_str.strip()),
        int(TELEGRAM_API_ID),
        TELEGRAM_API_HASH,
        device_model="PC 64bit",
        system_version="Windows 10",
        app_version="4.16.8 x64",
        lang_code="ru",
        system_lang_code="ru-RU",
    )
