"""Read Telegram's account freeze state without changing the account."""
import asyncio
from telethon.errors import FrozenMethodInvalidError, FrozenParticipantMissingError
from telethon.tl.functions.help import GetAppConfigRequest
from telethon.tl.types import JsonObject, JsonNumber

FROZEN_MESSAGE = 'Замороженный аккаунт отклонён. Файлы загрузки удалены, в продажу он не добавлен.'

class FrozenAccountError(Exception):
    pass

async def ensure_not_frozen(client):
    # Official app config freeze_since_date is separate from SpamBot limitations.
    try:
        response = await asyncio.wait_for(client(GetAppConfigRequest(hash=0)), timeout=10)
    except (FrozenMethodInvalidError, FrozenParticipantMissingError):
        raise FrozenAccountError(FROZEN_MESSAGE) from None
    config = getattr(response, 'config', None)
    if not isinstance(config, JsonObject):
        raise ValueError('Не удалось проверить заморозку аккаунта. Повторите загрузку.')
    for item in config.value:
        if item.key == 'freeze_since_date':
            if not isinstance(item.value, JsonNumber):
                raise ValueError('Не удалось проверить заморозку аккаунта. Повторите загрузку.')
            if item.value.value > 0:
                raise FrozenAccountError(FROZEN_MESSAGE)
