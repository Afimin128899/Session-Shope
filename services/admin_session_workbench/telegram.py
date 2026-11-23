import asyncio
import re
import logging
from dataclasses import dataclass

from telethon import TelegramClient, errors, functions, types
from .pr1_input import normalize_phone

logging.getLogger("admin_session_workbench.telethon").setLevel(logging.CRITICAL)


class UserFacingError(Exception):
    pass


async def authorization(client):
    try:
        # Telethon.is_user_authorized() swallows RPCError; probe explicitly first
        # so revoked, deactivated and flood-limited sessions remain distinguishable.
        await client(functions.updates.GetStateRequest())
        if not await client.is_user_authorized():
            return 'Не авторизована'
        me = await client.get_me()
        return 'Аккаунт удалён' if me is None or me.deleted else 'Активна'
    except errors.AuthKeyUnregisteredError:
        return 'Не авторизована: ключ не зарегистрирован Telegram'
    except (errors.SessionRevokedError, errors.SessionExpiredError):
        return 'Отозвана'
    except errors.AuthKeyDuplicatedError:
        return 'Отозвана: ключ авторизации отклонён Telegram'
    except errors.UserDeactivatedBanError:
        return 'Ограничение Telegram: аккаунт заблокирован'
    except errors.UserDeactivatedError:
        return 'Аккаунт удалён'
    except errors.FloodWaitError:
        raise
    except (OSError, asyncio.TimeoutError):
        return 'Ошибка подключения'


class ControlledClient(TelegramClient):
    async def send_code_request(self, phone):
        # Telethon 1.41's convenience wrapper retries AuthRestart internally and
        # raises RuntimeError for SentCodeSuccess. Preserve the actual RPC result
        # and let the migration state machine control every retry.
        return await self(functions.auth.SendCodeRequest(
            phone, self.api_id, self.api_hash, types.CodeSettings()))


def make_client(path, config, api_id, api_hash):
    proxy = config.get('proxy')
    if proxy:
        if not isinstance(proxy, dict) or proxy.get('proxy_type', 'socks5') not in {'socks5', 'socks4', 'http'}:
            raise UserFacingError('Некорректный proxy в JSON')
        proxy = {k: v for k, v in proxy.items() if k in {'proxy_type', 'addr', 'port', 'username', 'password', 'rdns'}}
        if not isinstance(proxy.get('addr'), str) or not isinstance(proxy.get('port'), int):
            raise UserFacingError('Для proxy нужны addr и числовой port')
    # API credentials are exclusively supplied by environment, never uploaded JSON.
    options = {k: str(config[k]) for k in ('device_model', 'system_version', 'app_version', 'lang_code', 'system_lang_code') if k in config}
    return ControlledClient(str(path), api_id, api_hash, proxy=proxy, connection_retries=1,
                          request_retries=0, flood_sleep_threshold=0, timeout=20,
                          base_logger="admin_session_workbench.telethon", **options)


@dataclass
class Source:
    entity: object
    boundary: int
    label: str


async def resolve_service(client, address):
    try:
        return await client.get_entity(address)
    except ValueError:
        # Telethon's phone lookup searches contacts only. An existing service
        # dialog may be accessible without being in the contact list.
        async for dialog in client.iter_dialogs():
            entity = dialog.entity
            if not isinstance(entity, types.User):
                continue
            if address == 777000 and entity.id == 777000:
                return entity
            if address == '+42777' and str(getattr(entity, 'phone', '') or '').lstrip('+') == '42777':
                return entity
        raise ValueError('Служебный чат не найден') from None


async def code_sources(client):
    sources, diagnostics, seen = [], [], set()
    for address in (777000, '+42777'):
        label = str(address)
        try:
            # Resolve phone number to actual peer; +42777 is not a numeric peer ID.
            entity = await resolve_service(client, address)
            if entity.id in seen:
                continue
            seen.add(entity.id)
            last = await client.get_messages(entity, limit=1)
            sources.append(Source(entity, last[0].id if last else 0, label))
        except errors.FloodWaitError:
            raise
        except (ValueError, errors.RPCError, OSError, asyncio.TimeoutError):
            diagnostics.append(f'Чат {label} недоступен')
    return sources, diagnostics


async def read_code(client, sources, length):
    malformed = False
    available = 0
    for source in sources:
        try:
            async for message in client.iter_messages(source.entity, min_id=source.boundary, limit=30):
                if message.id <= source.boundary or message.out:
                    continue
                # Date deliberately unused: Telegram IDs define each peer's boundary.
                match = re.search(rf'(?<!\d)(\d{{{length}}})(?!\d)', message.raw_text or '')
                if match:
                    return match.group(1), 'Код найден'
                malformed = True
            available += 1
        except errors.FloodWaitError:
            raise
        except (ValueError, errors.RPCError, OSError, asyncio.TimeoutError):
            continue
    if not available:
        return None, 'Служебные чаты недоступны'
    return None, 'Ошибка распознавания нового сообщения' if malformed else 'Нет нового входящего сообщения'


async def migrate(old, new, ask, report, config, *, poll_seconds=45, sleep=asyncio.sleep):
    status = await authorization(old)
    if status != 'Активна':
        raise UserFacingError(status)
    me = await old.get_me()
    sources, diagnostics = await code_sources(old)  # Before send_code_request, per peer.
    for diagnostic in diagnostics:
        await report(diagnostic)
    if not me.phone:
        raise UserFacingError('У аккаунта нет доступного номера телефона')
    phone = normalize_phone(me.phone)
    if not phone or not phone.isascii():
        raise UserFacingError('В исходной сессии некорректный номер телефона')
    sent = await new.send_code_request(phone)
    for attempt in range(2):
        if isinstance(sent, types.auth.SentCodeSuccess):
            await report('Вход в новую авторизацию')
            await verify_new(new, me.id)
            await report('Новая авторизация подтверждена')
            return
        if not isinstance(sent, types.auth.SentCode):
            raise UserFacingError('Нестандартное подтверждение Telegram; автоматическая миграция остановлена')
        delivery = type(sent.type).__name__
        await report(f'Доставка: {delivery}')
        code = None
        if isinstance(sent.type, types.auth.SentCodeTypeApp) and sources:
            reason = 'Нет нового входящего сообщения'
            for _ in range(poll_seconds // 3):
                code, reason = await read_code(old, sources, sent.type.length)
                if code:
                    break
                await sleep(3)
            if not code:
                await report(f'Таймаут чтения: {reason}')
        elif not isinstance(sent.type, (types.auth.SentCodeTypeApp, types.auth.SentCodeTypeSms, types.auth.SentCodeTypeCall, types.auth.SentCodeTypeFlashCall, types.auth.SentCodeTypeMissedCall)):
            raise UserFacingError(f'Способ {delivery} требует подтверждения вне этого бота; исходная сессия сохранена')
        if not code:
            prompt = 'Введите код. Telegram определяет способ доставки; доставка не гарантируется.'
            can_resend = attempt == 0 and sent.next_type is not None and sent.timeout is not None
            code = await ask('code', prompt + (' Для однократного повтора после timeout введите resend.' if can_resend else ''))
            if code == 'resend':
                if not can_resend:
                    raise UserFacingError('Telegram не разрешил повторную отправку')
                await report(f'Ожидание разрешённого повтора: {sent.timeout} с')
                await sleep(max(0, sent.timeout))
                # Refresh each boundary before the one permitted resend.
                sources, diagnostics = await code_sources(old)
                sent = await new(functions.auth.ResendCodeRequest(phone, sent.phone_code_hash))
                continue
        await report('Вход в новую авторизацию')
        try:
            await new.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        except errors.SessionPasswordNeededError:
            password = config.get('twoFA') or config.get('password') or config.get('two_fa')
            if not password:
                password = await ask('password', 'Введите пароль 2FA для этой задачи.')
            try:
                await new.sign_in(password=password)
            except errors.PasswordHashInvalidError:
                password = await ask('password', 'Пароль из JSON неверен. Введите пароль 2FA.')
                await new.sign_in(password=password)
        await verify_new(new, me.id)
        await report('Новая авторизация подтверждена')
        return
    raise UserFacingError('Повторная отправка исчерпана')


async def verify_new(client, expected_id):
    if not await client.is_user_authorized():
        raise UserFacingError('Вход в новую авторизацию не подтверждён')
    me = await client.get_me()
    if me is None or me.deleted or me.id != expected_id:
        raise UserFacingError('Новая авторизация не соответствует исходному аккаунту')
