"""New login and export tests use synthetic sessions and never contact Telegram."""
import io
import json
import zipfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock,patch
from test_payments import config
from services import session_reauth as reauth, session_inventory_jobs as jobs
from telethon.errors import SessionPasswordNeededError
import test_miniapp
from miniapp import server
from database import session_jobs

class AuthorizationTests(unittest.IsolatedAsyncioTestCase):
    def clients(self):
        old=NS(connect=AsyncMock(),is_user_authorized=AsyncMock(return_value=True),get_me=AsyncMock(return_value=NS(id=42,phone='15551112222')),get_messages=AsyncMock(side_effect=[[NS(id=10)],[NS(id=11,sender_id=777000,raw_text='Login code: 12345.')]]))
        new=NS(connect=AsyncMock(),send_code_request=AsyncMock(return_value=NS(phone_code_hash='hash')),sign_in=AsyncMock(),get_me=AsyncMock(return_value=NS(id=42)),session=NS(save=MagicMock(return_value='new-fixture')))
        return old,new
    async def test_new_login_uses_only_fresh_service_code_and_returns_new_session(self):
        old,new=self.clients()
        with patch.object(reauth,'ensure_not_frozen',AsyncMock()):
            result=await reauth._authorize(old,new,{'number':'+15551112222','data':'old-fixture','telegram_user_id':42})
        self.assertEqual(result['new_session'],'new-fixture')
        new.sign_in.assert_awaited_once_with(phone='+15551112222',code='12345',phone_code_hash='hash')
        self.assertNotIn('12345',str(result))

    async def test_unknown_2fa_keeps_existing_session(self):
        old,new=self.clients();new.sign_in.side_effect=SessionPasswordNeededError(None)
        with patch.object(reauth,'ensure_not_frozen',AsyncMock()):
            result=await reauth._authorize(old,new,{'number':'+15551112222','data':'old-fixture','password':'-'})
        self.assertEqual(result['reason'],'2fa_required');new.session.save.assert_not_called()

    async def test_owner_mismatch_never_requests_login_code(self):
        old,new=self.clients()
        result=await reauth._authorize(old,new,{'number':'+15551112222','data':'old-fixture','telegram_user_id':99})
        self.assertEqual(result['reason'],'identity_mismatch');new.send_code_request.assert_not_awaited()

    async def test_wrong_new_identity_is_never_saved(self):
        old,new=self.clients();new.get_me.return_value.id=99
        with patch.object(reauth,'ensure_not_frozen',AsyncMock()):
            result=await reauth._authorize(old,new,{'number':'+15551112222','data':'old-fixture','telegram_user_id':42})
        self.assertEqual(result['reason'],'new_identity_mismatch');new.session.save.assert_not_called()

class ArchiveTests(unittest.TestCase):
    def test_archive_has_session_and_json_but_no_invented_registration(self):
        account={'id':7,'data':'fixture','number':'+15551112222','password':'private-2fa'}
        with patch.object(jobs,'session_file_bytes',return_value=b'SQLite fixture'):
            archive=jobs.archive_bytes([account],[{'id':7,'status':'exported'}])
        with zipfile.ZipFile(io.BytesIO(archive)) as z:
            self.assertEqual(set(z.namelist()),{'account-7.session','account-7.json','report.json'})
            metadata=json.loads(z.read('account-7.json'))
            self.assertIsNone(metadata['registration_date']);self.assertEqual(metadata['string_session'],'fixture')
            self.assertEqual(metadata['password'],'private-2fa')
            self.assertNotIn('fixture',z.read('report.json').decode())

class JobTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_authorization_never_replaces_existing_session(self):
        bot=NS(send_document=AsyncMock(),send_message=AsyncMock())
        account={'id':7,'data':'original','lease_token':'token'}
        with patch.object(jobs,'rows',AsyncMock(side_effect=[[{'maximum':7}],[{'id':7}]])),patch.object(session_jobs,'claim',AsyncMock(return_value=account)),patch.object(session_jobs,'release',AsyncMock()) as release,patch.object(session_jobs,'save_new',AsyncMock()) as save,patch.object(jobs,'recreate',AsyncMock(return_value={'status':'failed','reason':'2fa_required'})),patch.object(jobs,'archive_bytes',return_value=b'zip') as archive:
            await jobs.run(bot,42,'reauthorize')
        save.assert_not_awaited();release.assert_awaited_once_with(account)
        self.assertEqual(archive.call_args.args[0][0]['data'],'original')
        self.assertEqual(bot.send_document.call_args.args[0],42)

class ExportAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown
    async def test_customer_cannot_export_or_rotate(self):
        with patch.object(config,'ADMIN_IDS',[99]),patch.object(jobs,'run',AsyncMock()) as run:
            r=await self.client.post('/api/admin/session-jobs',headers=self.headers,json={'action':'export','admin_id':99})
            self.assertEqual(r.status,403);run.assert_not_awaited()
    async def test_export_recipient_is_signed_admin_not_body(self):
        bot=NS(send_message=AsyncMock())
        self.client.app[server.BOT]=bot
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(jobs,'run',AsyncMock()) as run:
            r=await self.client.post('/api/admin/session-jobs',headers=self.headers,json={'action':'export','admin_id':99})
            self.assertEqual(r.status,202)
            import asyncio
            await asyncio.sleep(0)
            run.assert_awaited_once_with(bot,42,'export')

class LeaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_lease_cannot_replace_session(self):
        from contextlib import asynccontextmanager
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value=None))
        @asynccontextmanager
        async def tx():yield cur
        with patch.object(session_jobs,'_transaction',tx):
            saved=await session_jobs.save_new(42,{'id':7,'data':'old','lease_token':'expired'},{'new_session':'new','telegram_user_id':99})
        self.assertFalse(saved)
        self.assertEqual(cur.execute.await_count,1)
        self.assertIn('spam_lease_until>UTC_TIMESTAMP()',cur.execute.call_args.args[0])

    async def test_success_updates_session_and_identity_index_together(self):
        from contextlib import asynccontextmanager
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[{'id':7},{'account_id':7}]))
        @asynccontextmanager
        async def tx():yield cur
        with patch.object(session_jobs,'_transaction',tx),patch.object(session_jobs,'_record',AsyncMock()) as audit:
            saved=await session_jobs.save_new(42,{'id':7,'data':'old','lease_token':'active'},{'new_session':'new','telegram_user_id':99})
        self.assertTrue(saved)
        self.assertEqual(cur.execute.call_args.args[1],('new',99,7))
        self.assertNotIn('old',str(audit.call_args));self.assertNotIn('new',str(audit.call_args))
