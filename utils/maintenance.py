from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from typing import Any, Awaitable, Callable

from config import ADMIN_IDS
from database.db import get_setting


def maintenance_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить доступность", callback_data="check_maintenance")],
    ])


async def is_maintenance() -> bool:
    return (await get_setting("maintenance_mode", "0")).strip() == "1"


def maintenance_text() -> str:
    return (
        "🔧 <b>Технические работы</b>\n\n"
        "Бот временно недоступен. Мы уже работаем над обновлением.\n\n"
        "Нажмите кнопку ниже, чтобы проверить доступность."
    )


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
            await answer_safe(event, 'Бот снова доступен!')
            return None
        if not maintenance:
            return await handler(event, data)

        if isinstance(event, Message):
            await event.answer(maintenance_text(), reply_markup=maintenance_keyboard())
            return None

        if isinstance(event, CallbackQuery):
            if event.data == "check_maintenance":
                await event.answer(
                    "🔧 Технические работы ещё продолжаются.",
                    show_alert=True,
                )
            else:
                await event.answer(
                    "🔧 Сейчас идут технические работы. Попробуйте позже.",
                    show_alert=True,
                )
            return None

        return None
