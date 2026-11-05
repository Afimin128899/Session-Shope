"""Keep a first-start referral while the user completes mandatory subscription."""


async def pending(state):
    if state is None or not hasattr(state, 'get_data'):
        return None
    data = await state.get_data()
    value = data.get('pending_referrer') if isinstance(data, dict) else None
    return value if type(value) is int and 0 < value <= 9223372036854775807 else None


async def remember(message, state):
    parts = (message.text or '').strip().split(maxsplit=1)
    if len(parts) != 2 or parts[0].split('@')[0] != '/start' or not parts[1].startswith('ref_'):
        return
    value = parts[1][4:]
    if not value.isascii() or not value.isdigit() or len(value) > 19 or not 0 < int(value) <= 9223372036854775807 or int(value) == message.from_user.id or state is None:
        return
    if await pending(state) is None:
        await state.update_data(pending_referrer=int(value))


async def complete(user, state):
    referrer = await pending(state)
    if referrer is not None:
        from database.db import create_user_with_referrer
        await create_user_with_referrer(user.id, referrer, getattr(user, 'username', None))
        await state.update_data(pending_referrer=None)
