"""Read a fresh official SpamBot reply; never appeal or test messaging strangers."""
import asyncio
import re

from telethon.errors import FloodWaitError, YouBlockedUserError, UserIsBlockedError
from telethon.tl.functions.contacts import UnblockRequest

from services.telethon_factory import create_client


def classify_reply(text):
    text = re.sub(r'\s+', ' ', str(text or '').casefold().replace('ё', 'е')).strip()
    clear = any(part in text for part in (
        'no limits are currently applied to your account',
        'no limits have been applied to your account',
        'на ваш аккаунт не наложено никаких ограничений',
        'ваш аккаунт свободен от каких-либо ограничений',
        'ваш аккаунт не ограничен',
    ))
    limited = any(part in text for part in (
        'your account is currently limited', 'your account has been limited',
        'your account is now limited', 'your account is limited until',
        'your account is permanently limited',
        'на ваш аккаунт наложены ограничения', 'ваш аккаунт ограничен',
        'на ваш аккаунт наложены временные ограничения',
        'на ваш аккаунт наложено ограничение', 'ваш аккаунт был ограничен',
        'вашему аккаунту было назначено временное ограничение',
        'вы можете отправлять сообщения только взаимным контактам',
        'you can only send messages to mutual contacts',
    ))
    return 'clear' if clear and not limited else 'limited' if limited and not clear else 'unknown'


def result(status, reason=None, retry_after=None):
    return {'status': status, 'reason': reason, 'retry_after': retry_after}


async def _conversation(client, expected_id, expected_phone):
    await client.connect()
    if not await client.is_user_authorized():
        return result('error', 'unauthorized')
    me = await client.get_me()
    digits = lambda value: ''.join(c for c in str(value or '') if c in '0123456789')
    if not me or (expected_id and me.id != expected_id) or (expected_phone and digits(me.phone) != digits(expected_phone)):
        return result('error', 'identity_mismatch')
    peer = await client.get_entity('SpamBot')
    if not getattr(peer, 'bot', False) or str(getattr(peer, 'username', '')).casefold() != 'spambot':
        return result('error', 'wrong_peer')
    async with client.conversation(peer, timeout=12, exclusive=True) as dialog:
        try:
            sent = await dialog.send_message('/start')
        except (YouBlockedUserError, UserIsBlockedError):
            await client(UnblockRequest(id=peer))
            sent = await dialog.send_message('/start')
        reply = await dialog.get_response(sent)
        if reply.sender_id != peer.id or reply.id <= sent.id:
            return result('unknown', 'unrecognized')
        status = classify_reply(reply.raw_text)
        return result(status, 'unrecognized' if status == 'unknown' else None)


async def check_session(session, *, expected_id=None, expected_phone=None):
    client = None
    try:
        if not isinstance(session, str) or len(session.strip()) < 100:
            return result('error', 'no_session')
        client = create_client(session_str=session)
        return await asyncio.wait_for(_conversation(client, expected_id, expected_phone), timeout=25)
    except FloodWaitError as exc:
        return result('error', 'flood_wait', max(1, int(exc.seconds)))
    except TimeoutError:
        return result('error', 'timeout')
    except Exception:
        # Session strings, Telegram replies and exception text never reach logs/storage.
        return result('error', 'connection')
    finally:
        if client:
            try:
                await asyncio.wait_for(client.disconnect(), timeout=5)
            except Exception:
                pass


async def spam_worker(bot):
    from database import spam_checks
    import logging
    logger = logging.getLogger(__name__)
    while True:
        lease = None
        try:
            lease = await spam_checks.claim()
            if lease:
                report = await check_session(lease['data'], expected_id=lease['telegram_user_id'], expected_phone=lease['number'])
                await spam_checks.finish(lease, report)
        except asyncio.CancelledError:
            if lease:
                await spam_checks.release(lease)
            raise
        except Exception:
            logger.warning('SpamBot check deferred; no private data logged')
        await asyncio.sleep(5 if lease else 15)
