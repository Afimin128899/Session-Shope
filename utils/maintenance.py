from utils.i18n import tr
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from typing import Any, Awaitable, Callable

from config import ADMIN_IDS, SUPPORT_USERNAME
from database.db import get_setting


def maintenance_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr('🔄 Проверить статус'), callback_data='check_maintenance')], [InlineKeyboardButton(text=tr('🌐 Язык / Language'), callback_data='language')]]
    import re
    if re.fullmatch('@?[A-Za-z0-9_]{5,32}', SUPPORT_USERNAME or ''):
        rows.append([InlineKeyboardButton(text=tr('💬 Поддержка'), url='https://t.me/' + SUPPORT_USERNAME.lstrip('@'))])
    from utils.legal import information_button
    rows.append([information_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def is_maintenance() -> bool:
    return (await get_setting("maintenance_mode", "0")).strip() == "1"


def maintenance_text() -> str:
    from database.shop_control import maintenance_message
    return maintenance_message({})


class MaintenanceMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, dict], Awaitable[Any]],
        event: Any,
        data: dict,
    ) -> Any:
        from utils.payment_events import is_payment_event
        if is_payment_event(event):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data in {'language', 'info_menu'} or (event.data or '').startswith('language:')):
            return await handler(event, data)
        if isinstance(event, Message) and (event.text or '').split('@')[0].strip() == '/language':
            return await handler(event, data)
        user = getattr(event, "from_user", None)
        if not user:
            return await handler(event, data)

        try:
            is_admin = int(user.id) in [int(x) for x in ADMIN_IDS]
        except Exception:
            is_admin = False

        maintenance = False if is_admin else await is_maintenance()
        if isinstance(event, CallbackQuery) and event.data == 'check_maintenance' and not maintenance:
            from utils.nav import edit_main, answer_safe
            if data.get('state'):
                await data['state'].clear()
            await edit_main(event)
            await answer_safe(event, tr('Бот снова доступен!'))
            return None
        if not maintenance:
            return await handler(event, data)

        from miniapp.storage import access_settings
        from database.shop_control import maintenance_message
        text = maintenance_message(await access_settings())

        if isinstance(event, Message):
            from utils.section_banners import answer_screen
            await answer_screen(event, text, section='maintenance', reply_markup=maintenance_keyboard())
            return None

        if isinstance(event, CallbackQuery):
            from utils.nav import edit_message_safe, answer_safe
            await edit_message_safe(event, text, section='maintenance', reply_markup=maintenance_keyboard())
            await answer_safe(event, tr('🛠 Технические работы ещё продолжаются.'))
            return None

        return None
