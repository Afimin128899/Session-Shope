"""One server-owned language choice shared by Telegram and Mini App."""
from utils.i18n import tr
from database.db import get_user, create_user, _get_pool
from utils.i18n import language, SUPPORTED


async def get_language(user_id):
    row = await get_user(user_id)
    return language(row.get('language') if row else 'ru')


async def set_language(user_id, value):
    if not isinstance(value, str) or value not in SUPPORTED:
        raise ValueError(tr('Выберите русский или английский язык.'))
    await create_user(user_id)
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('UPDATE users SET language=%s WHERE id=%s', (value, user_id))
    return value
