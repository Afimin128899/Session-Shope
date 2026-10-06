import time
from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit: float = 0.4):
        self.limit = limit
        self.last_request: Dict[int, float] = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id:
            now = time.time()
            last_time = self.last_request.get(user_id, 0)
            if now - last_time < self.limit:
                # User is flooding/spamming!
                if isinstance(event, CallbackQuery):
                    try:
                        await event.answer("⚠️ Пожалуйста, не спамьте кнопками!", show_alert=True)
                    except Exception:
                        pass
                return  # Block request from reaching handlers
            self.last_request[user_id] = now

        return await handler(event, data)
