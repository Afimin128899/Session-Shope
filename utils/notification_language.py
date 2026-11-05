"""Resolve recipient language after financial/support work has committed."""
import asyncio
from contextlib import asynccontextmanager

from utils.i18n import LANGUAGE, tr


@asynccontextmanager
async def recipient_language(user_id):
    value = 'ru'
    try:
        from database.preferences import get_language
        value = await asyncio.wait_for(get_language(user_id), timeout=2)
    except Exception:
        # A preference lookup must never prevent a payment receipt from being sent.
        pass
    token = LANGUAGE.set(value)
    try:
        yield
    finally:
        LANGUAGE.reset(token)


async def send_translated(bot, user_id, source, *values, **options):
    async with recipient_language(user_id):
        return await bot.send_message(user_id, tr(source, *values), **options)
