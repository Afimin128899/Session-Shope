"""Allow direct help through shop/subscription guards, without bypassing commerce."""
from aiogram.types import CallbackQuery, Message


async def is_support_event(event, data):
    if isinstance(event, CallbackQuery):
        value = event.data or ''
        return value in {'support', 'support_end'} or value.startswith(('support_reply:', 'purchase_help:', 'quality_warranty:', 'tk_', 'tk:'))
    if isinstance(event, Message):
        text = event.text or ''
        if text.split('@')[0].split(' ')[0] == '/support':
            return True
        state = data.get('state')
        current = await state.get_state() if state else None
        if current in {'DirectSupport:message', 'DirectSupport:reply', 'Input:warranty'} and text.split('@')[0].strip() == '/cancel':
            return True
        return current in {'DirectSupport:message', 'DirectSupport:reply', 'Input:warranty'} and not text.startswith('/')
    return False
