"""Preserve an advertising source during required subscription, without rewards."""
from database.advertising import TOKEN, token_from_payload


async def pending_ad(state):
    data = await state.get_data() if state else {}
    value = data.get('pending_ad')
    return value if isinstance(value,str) and TOKEN.fullmatch(value) else None


async def remember_ad(message,state):
    parts=(message.text or '').split(maxsplit=1)
    if state and len(parts)==2 and parts[0].split('@')[0]=='/start' and not await pending_ad(state):
        token=token_from_payload(parts[1])
        if token:
            await state.update_data(pending_ad=token,pending_referrer=None)
