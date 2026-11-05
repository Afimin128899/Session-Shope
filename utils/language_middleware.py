"""Set request-local UI language; no global language or cross-user state."""
from aiogram import BaseMiddleware
from database.preferences import get_language
from utils.i18n import LANGUAGE
from utils.payment_events import is_payment_event


class LanguageMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if is_payment_event(event):
            return await handler(event, data)
        user = getattr(event, 'from_user', None)
        value = await get_language(user.id) if user else 'ru'
        token = LANGUAGE.set(value)
        try:
            return await handler(event, data)
        finally:
            LANGUAGE.reset(token)
