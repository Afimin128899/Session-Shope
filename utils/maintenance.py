from utils.i18n import tr
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from typing import Any, Awaitable, Callable

from config import ADMIN_IDS, SUPPORT_USERNAME
from database.db import get_setting
from utils.button_icons import pack_icon_for


def maintenance_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=tr('Проверить статус'), callback_data='check_maintenance', icon_custom_emoji_id=pack_icon_for('refresh'), style='primary')],
            [InlineKeyboardButton(text=tr('Написать в поддержку'), callback_data='support', icon_custom_emoji_id=pack_icon_for('support'))]]
    from utils.legal import information_button
    rows.append([information_button(), InlineKeyboardButton(text=tr('Язык'), callback_data='language', icon_custom_emoji_id=pack_icon_for('country'))])
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
        from utils.support_access import is_support_event
        if await is_support_event(event, data):
            return await handler(event, data)
        if isinstance(event, CallbackQuery) and (event.data in {'language', 'info_menu', 'profile_info'} or (event.data or '').startswith('language:')):
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
            await answer_safe(event, tr('Технические работы ещё продолжаются. Обновили информацию о статусе.'))
            return None

        return None
