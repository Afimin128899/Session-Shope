"""Bounded per-user throttling with a monotonic clock."""
import time
from collections import OrderedDict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=0.4, max_entries=10000):
        super().__init__()
        self.limit = limit
        self.max_entries = max(1, max_entries)
        self.last_request = OrderedDict()

    async def __call__(self, handler, event, data):
        from utils.payment_events import is_payment_event
        if is_payment_event(event):
            return await handler(event, data)
        user = getattr(event, 'from_user', None)
        if user:
            now = time.monotonic()
            while self.last_request and now - next(iter(self.last_request.values())) > max(60, self.limit * 2):
                self.last_request.popitem(last=False)
            last = self.last_request.get(user.id)
            if last is not None and now - last < self.limit:
                if isinstance(event, CallbackQuery):
                    from utils.nav import answer_safe
                    await answer_safe(event, 'Подождите секунду перед следующим нажатием.')
                return
            self.last_request[user.id] = now
            self.last_request.move_to_end(user.id)
            while len(self.last_request) > self.max_entries:
                self.last_request.popitem(last=False)
        return await handler(event, data)
