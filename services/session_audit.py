"""Remove other Telegram authorizations while preserving the store's current one."""
import asyncio
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import GetAuthorizationsRequest, ResetAuthorizationRequest
from services.telethon_factory import create_client

async def clean_other_sessions(session, expected_id):
    client = None
    try:
        client = create_client(session_str=session)
        client.flood_sleep_threshold = 0
        return await asyncio.wait_for(_clean(client, expected_id), 55)
    except FloodWaitError as exc:
        return {'status':'failed','reason':'flood_wait','retry_after':exc.seconds}
    except Exception:
        return {'status':'failed','reason':'telegram_error'}
    finally:
        try:
            if client:
                await asyncio.wait_for(client.disconnect(), 5)
        except Exception:
            pass

async def _clean(client, expected_id):
    await client.connect()
    me = await client.get_me()
    if not me or not expected_id or me.id != expected_id:
        return {'status':'failed','reason':'identity_mismatch'}
    before = (await client(GetAuthorizationsRequest())).authorizations
    if sum(bool(item.current) for item in before) != 1:
        return {'status':'failed','reason':'current_session_unknown'}
    others = [item for item in before if not item.current]
    for item in others:
        await client(ResetAuthorizationRequest(hash=item.hash))
    after = (await client(GetAuthorizationsRequest())).authorizations
    remaining = sum(not item.current for item in after)
    return {'status':'failed' if remaining else 'cleaned' if others else 'single',
            'extra_before':len(others),'extra_after':remaining}


def session_file_bytes(value):
    """Export the store's StringSession as a Telethon SQLite session locally."""
    import tempfile
    from pathlib import Path
    from telethon.sessions import StringSession, SQLiteSession
    source = StringSession(value)
    with tempfile.TemporaryDirectory(prefix='sband-export-') as folder:
        path = Path(folder) / 'account.session'
        target = SQLiteSession(str(path))
        try:
            target.set_dc(source.dc_id, source.server_address, source.port)
            target.auth_key = source.auth_key
            target.save()
        finally:
            target.close()
        return path.read_bytes()
