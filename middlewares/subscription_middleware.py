from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

from config import ADMIN_IDS
from utils.sub_check import is_user_subscribed, send_sub_prompt


class SubscriptionMiddleware(BaseMiddleware):
    """Middleware для проверки обязательной подписки на Telegram канал."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user

        if user:
            # Игнорируем администраторов
            if user.id in ADMIN_IDS:
                return await handler(event, data)

            # Игнорируем коллбэк самостоятельной проверки подписки
            if isinstance(event, CallbackQuery) and event.data == "check_sub_status":
                return await handler(event, data)

            bot = data.get("bot")
            if bot:
                subscribed = await is_user_subscribed(bot, user.id)
                if not subscribed:
                    await send_sub_prompt(event, bot)
                    return None

        return await handler(event, data)
