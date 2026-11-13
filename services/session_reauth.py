"""Create a new authorization using a fresh service code read from the current session."""
import asyncio
import re
from telethon.errors import FloodWaitError, SessionPasswordNeededError, PasswordHashInvalidError
from services.telethon_factory import create_client
from services.account_health import ensure_not_frozen, FrozenAccountError
from utils.commerce_policy import require_phone


async def recreate(account):
    old=new=None
    try:
        require_phone(account['number'])
        old=create_client(session_str=account['data'])
        new=create_client(session_str='')
        old.flood_sleep_threshold=new.flood_sleep_threshold=0
        return await asyncio.wait_for(_authorize(old,new,account),70)
    except FloodWaitError as exc:
        return {'status':'failed','reason':'flood_wait','retry_after':exc.seconds}
    except FrozenAccountError:
        return {'status':'failed','reason':'frozen'}
    except PasswordHashInvalidError:
        return {'status':'failed','reason':'wrong_2fa'}
    except TimeoutError:
        return {'status':'failed','reason':'timeout'}
    except Exception:
        return {'status':'failed','reason':'authorization_error'}
    finally:
        for client in (new,old):
            if client:
                try: await asyncio.wait_for(client.disconnect(),5)
                except Exception: pass


async def _authorize(old,new,account):
    await old.connect()
    if not await old.is_user_authorized():
        return {'status':'failed','reason':'old_session_invalid'}
    me=await old.get_me()
    digits=lambda value: ''.join(c for c in str(value) if c.isascii() and c.isdigit())
    if not me or (account.get('telegram_user_id') and me.id!=account['telegram_user_id']) or digits(me.phone)!=digits(account['number']):
        return {'status':'failed','reason':'identity_mismatch'}
    await ensure_not_frozen(old)
    history=await old.get_messages(777000,limit=1)
    baseline=max((message.id for message in history),default=0)
    await new.connect()
    sent=await new.send_code_request(account['number'])
    from telethon.tl.types.auth import SentCodeSuccess
    if not isinstance(sent,SentCodeSuccess):
        code=None
        for _ in range(15):
            messages=await old.get_messages(777000,limit=8,min_id=baseline)
            for message in messages:
                if message.id>baseline and message.sender_id==777000:
                    match=re.search(r'(?<!\d)\d{5,6}(?!\d)',message.raw_text or '')
                    if match: code=match.group();break
            if code: break
            await asyncio.sleep(2)
        if not code:
            return {'status':'failed','reason':'code_not_received'}
        try:
            await new.sign_in(phone=account['number'],code=code,phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            if not account.get('password') or account['password']=='-':
                return {'status':'failed','reason':'2fa_required'}
            await new.sign_in(password=account['password'])
    verified=await new.get_me()
    if not verified or verified.id!=me.id:
        return {'status':'failed','reason':'new_identity_mismatch'}
    await ensure_not_frozen(new)
    value=new.session.save()
    if not value or value==account['data']:
        return {'status':'failed','reason':'new_session_missing'}
    return {'status':'ready','new_session':value,'telegram_user_id':verified.id}
