"""No real Telegram accounts: freeze detection and import rejection invariants."""
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
from test_payments import config
from telethon.tl.types import JsonObject, JsonObjectValue, JsonNumber, JsonString
from telethon.errors import FrozenMethodInvalidError
from services.account_health import ensure_not_frozen, FrozenAccountError
from services import telethon_auth, archive_import

class HealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_config_and_explicit_rpc_rejected(self):
        client=AsyncMock(return_value=NS(config=JsonObject([JsonObjectValue('freeze_since_date', JsonNumber(1700000000))])))
        with self.assertRaises(FrozenAccountError): await ensure_not_frozen(client)
        client.side_effect=FrozenMethodInvalidError(None)
        with self.assertRaises(FrozenAccountError): await ensure_not_frozen(client)

    async def test_regular_and_spam_limited_accounts_are_not_frozen(self):
        for values in ([],[JsonObjectValue('freeze_since_date',JsonNumber(0))], [JsonObjectValue('unrelated',JsonString('limited'))]):
            await ensure_not_frozen(AsyncMock(return_value=NS(config=JsonObject(values))))

    async def test_unavailable_or_malformed_config_is_not_accepted(self):
        for reply in (NS(),NS(config=JsonObject([JsonObjectValue('freeze_since_date',JsonString('bad'))]))):
            with self.assertRaises(ValueError): await ensure_not_frozen(AsyncMock(return_value=reply))

    async def test_session_import_never_exports_frozen_session(self):
        client=NS(connect=AsyncMock(),disconnect=AsyncMock(),is_user_authorized=AsyncMock(return_value=True),get_me=AsyncMock())
        metadata={}
        with patch.object(telethon_auth,'TELEGRAM_API_ID',1),patch.object(telethon_auth,'TELEGRAM_API_HASH','fixture'),patch('services.session_validation.validate_session_file'),patch.object(telethon_auth,'TelegramClient',return_value=client),patch.object(telethon_auth,'ensure_not_frozen',AsyncMock(side_effect=FrozenAccountError())),patch.object(telethon_auth.StringSession,'save') as export:
            result=await telethon_auth.import_session_file('/unused',metadata)
        self.assertIsNone(result[0]);self.assertEqual(metadata,{'rejection':'frozen'})
        export.assert_not_called();client.disconnect.assert_awaited_once()

    async def test_manual_login_rejects_frozen_and_disconnects(self):
        client=NS(disconnect=AsyncMock(),session=NS(save=MagicMock()))
        with patch.object(telethon_auth,'ensure_not_frozen',AsyncMock(side_effect=FrozenAccountError())):
            result=await telethon_auth.finalize_account(client,{})
        self.assertIsNone(result[0]);client.session.save.assert_not_called();client.disconnect.assert_awaited_once()

    async def test_archive_rejection_deletes_temporary_session_and_never_stores_secret(self):
        paths=[]
        async def verifier(path,metadata):
            paths.append(Path(path));Path(path+'-wal').write_bytes(b'private')
            metadata['rejection']='frozen'
            return None,None,'frozen'
        files=[('account.session',b'SQLite format 3\x00fixture')]
        with patch.object(archive_import.imports,'preview',AsyncMock(return_value={'status':'checking'})),patch.object(archive_import.imports,'add_item',AsyncMock()) as add,patch.object(archive_import.imports,'finish',AsyncMock()),patch.object(archive_import,'rows',AsyncMock()) as rows:
            await archive_import.process(1,'batch',files,verifier)
        self.assertEqual(add.call_args.args[2],'error');self.assertNotIn('session',add.call_args.kwargs)
        rows.assert_not_awaited();self.assertFalse(paths[0].parent.exists());self.assertEqual(files,[])

class StandaloneWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_standalone_runs_and_stops_spam_worker(self):
        import asyncio
        from miniapp import server
        from services import spam_check
        started=asyncio.Event()
        stopped=asyncio.Event()
        async def work(bot):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        context=MagicMock()
        context.__aenter__.return_value=NS()
        runner=NS(cleanup=AsyncMock())
        pool=NS(close=MagicMock(),wait_closed=AsyncMock())
        with patch('aiogram.Bot',return_value=context),patch.object(server.db,'init_db',AsyncMock()),patch.object(server.db,'pool',pool),patch.object(server,'start_server',AsyncMock(return_value=runner)),patch.object(spam_check,'spam_worker',work):
            task=asyncio.create_task(server.standalone())
            try:
                await asyncio.wait_for(started.wait(),1)
            finally:
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(stopped.is_set())
        runner.cleanup.assert_awaited_once();pool.wait_closed.assert_awaited_once()
