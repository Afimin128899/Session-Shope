"""Read a fresh official SpamBot reply; never appeal or test messaging strangers."""
import asyncio
import re

from telethon.errors import FloodWaitError, YouBlockedUserError, UserIsBlockedError, FrozenMethodInvalidError, FrozenParticipantMissingError
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
        'на данный момент на ваш аккаунт не наложено никаких ограничений',
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
        'your account is now limited until',
        'мы были вынуждены ограничить ваш аккаунт',
    ))
    permanent = any(part in text for part in (
        'your account is permanently limited', 'your account has been permanently limited',
        'your account is permanently restricted', 'your account has been permanently restricted',
        'your account is now permanently limited',
        'permanent limitations have been applied to your account',
        'ваш аккаунт ограничен навсегда', 'ваш аккаунт заблокирован навсегда',
        'на ваш аккаунт наложены бессрочные ограничения',
        'на ваш аккаунт наложены постоянные ограничения',
    ))
    if clear and (limited or permanent):
        return 'unknown'
    return 'clear' if clear else 'permanent' if permanent else 'limited' if limited else 'unknown'


def result(status, reason=None, retry_after=None):
    return {'status': status, 'reason': reason, 'retry_after': retry_after}


async def _fresh_history(client, peer, sent):
    """Recover a fresh reply if a Telegram update was lost; never reuse old status."""
    try:
        messages = await asyncio.wait_for(client.get_messages(peer, limit=8, min_id=sent.id), timeout=4)
    except TimeoutError:
        return 'unknown'
    for reply in messages:
        if reply.sender_id == peer.id and reply.id > sent.id:
            status = classify_reply(reply.raw_text)
            if status != 'unknown':
                return status
    return 'unknown'


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
    # Always unblock the verified official bot before the first command.
    # A blocked bot does not reliably produce a send_message exception.
    await client(UnblockRequest(id=peer))
    async with client.conversation(peer, timeout=12, exclusive=True) as dialog:
        try:
            sent = await dialog.send_message('/start')
        except (YouBlockedUserError, UserIsBlockedError):
            await client(UnblockRequest(id=peer))
            sent = await dialog.send_message('/start')
        for attempt in range(2):
            try:
                reply = await dialog.get_response(sent)
                status = classify_reply(reply.raw_text) if reply.sender_id == peer.id and reply.id > sent.id else 'unknown'
            except TimeoutError:
                status = await _fresh_history(client, peer, sent)
                if status == 'unknown' and attempt:
                    raise
            if status != 'unknown' or attempt:
                break
            # Only unblock the verified official bot; retry once with a fresh reply.
            await client(UnblockRequest(id=peer))
            sent = await dialog.send_message('/start')
        return result(status, 'unrecognized' if status == 'unknown' else None)


async def check_session(session, *, expected_id=None, expected_phone=None):
    client = None
    try:
        if not isinstance(session, str) or len(session.strip()) < 100:
            return result('error', 'no_session')
        client = create_client(session_str=session)
        client.flood_sleep_threshold = 0
        return await asyncio.wait_for(_conversation(client, expected_id, expected_phone), timeout=55)
    except (FrozenMethodInvalidError, FrozenParticipantMissingError):
        return result('error', 'frozen')
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
