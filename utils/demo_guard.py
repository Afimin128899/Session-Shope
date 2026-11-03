from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery,Message
from services.demo import STORE
from utils.payment_events import is_payment_event


class DemoGuard(BaseMiddleware):
    async def __call__(self,handler,event,data):
        if is_payment_event(event):return await handler(event,data)
        user=getattr(event,'from_user',None)
        if not user or not STORE.active(user.id):return await handler(event,data)
        from config import ADMIN_IDS
        if user.id not in ADMIN_IDS:
            STORE.exit(user.id);return await handler(event,data)
        if isinstance(event,CallbackQuery):
            if (event.data or '').startswith('demo:'):return await handler(event,data)
            await event.answer('Сначала выйдите из тестового режима кнопкой «В рабочий магазин» или /menu.',show_alert=True)
            return
        if isinstance(event,Message):
            if event.text and event.text.split()[0].split('@')[0] in {'/start','/menu','/cancel'}:
                STORE.exit(user.id)
                await event.answer('Тестовый режим закрыт. Открывается рабочее меню.')
                return await handler(event,data)
            await event.answer('Сейчас открыт тестовый магазин. Используйте его кнопки или /menu для выхода.')
            return
        return await handler(event,data)
