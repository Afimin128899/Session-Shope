"""Role boundary and hostile archive validation; never contact Telegram."""
import io
import stat
import unittest
import zipfile
from unittest.mock import AsyncMock,patch
import test_miniapp
from test_payments import config
from database import admin_web,imports,admin_tools
from miniapp import server
from services.archive_import import inspect_archive,MAX_FILE


def archive(entries):
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_STORED) as z:
        for name,data in entries: z.writestr(name,data)
    return out.getvalue()


class ArchiveTests(unittest.TestCase):
    def test_valid_archive_is_not_extracted_to_user_paths(self):
        items=inspect_archive(archive([('folder/account.session',b'SQLite format 3\0payload')]))
        self.assertEqual(items,[('folder/account.session',b'SQLite format 3\0payload')])
    def test_broken_session_can_be_shown_as_error_in_preview(self):
        self.assertEqual(inspect_archive(archive([('broken.session',b'bad')]))[0][1],b'bad')
    def test_rejects_paths_links_and_other_extensions(self):
        for name in ['../escape.session','/absolute.session','x\\bad.session','C:bad.session','folder/../../bad.session','account.zip','account.json']:
            with self.subTest(name=name),self.assertRaises(ValueError): inspect_archive(archive([(name,b'SQLite format 3\0payload')]))
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:
            entry=zipfile.ZipInfo('link.session');entry.create_system=3;entry.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(entry,b'SQLite format 3\0payload')
        with self.assertRaises(ValueError):inspect_archive(out.getvalue())
    def test_rejects_zip_bomb_and_too_many_sessions(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('bomb.session',b'0'*200000)
        with self.assertRaises(ValueError):inspect_archive(out.getvalue())
        with self.assertRaises(ValueError):inspect_archive(archive([(f'{i}.session',b'a') for i in range(101)]))
        with self.assertRaises(ValueError):inspect_archive(archive([('huge.session',b'x'*(MAX_FILE+1))]))
    def test_rejects_duplicates_invalid_zip_and_empty(self):
        with self.assertRaises(ValueError):inspect_archive(b'not ZIP')
        with self.assertRaises(ValueError):inspect_archive(archive([]))
        with self.assertRaises(ValueError):inspect_archive(archive([('a.session',b'1'),('a.session',b'2')]))


class AdminAPI(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown
    async def test_every_admin_route_rejects_non_admin_before_database_work(self):
        with patch.object(admin_web,'overview',AsyncMock()) as get,patch.object(imports,'create',AsyncMock()) as create:
            for method,path in [('GET','overview'),('GET','stock'),('GET','orders'),('GET','tickets'),('GET','users'),('GET','settings'),('GET','payments'),('POST','payments/check'),('GET','audit'),('GET','imports'),('POST','imports'),('POST','approvals/1'),('POST','users/1/balance'),('PATCH','stock/1'),('DELETE','stock/1')]:
                r=await self.client.request(method,'/api/admin/'+path,headers=self.headers)
                self.assertEqual(r.status,403,(method,path))
            get.assert_not_awaited();create.assert_not_awaited()
    async def test_admin_identity_cannot_be_chosen_by_client(self):
        with patch.object(config,'ADMIN_IDS',[999]),patch.object(admin_web,'overview',AsyncMock()) as get:
            r=await self.client.get('/api/admin/overview?admin_id=999',headers=self.headers)
            self.assertEqual(r.status,403);get.assert_not_awaited()
    async def test_signed_admin_can_read_dashboard_and_me_flag(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(admin_web,'overview',AsyncMock(return_value={'stock':2})):
            r=await self.client.get('/api/admin/overview',headers=self.headers)
            self.assertEqual(r.status,200);self.assertEqual((await r.json())['stock'],2)
            self.assertTrue((await (await self.client.get('/api/me',headers=self.headers)).json())['is_admin'])
    async def test_draft_uses_signed_owner(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(imports,'preview',AsyncMock(return_value={'items':[]})) as get:
            r=await self.client.get('/api/admin/imports/'+'a'*32+'?admin_id=99',headers=self.headers)
            self.assertEqual(r.status,200);get.assert_awaited_once_with(42,'a'*32)
    async def test_invalid_batch_never_reaches_database(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(imports,'preview',AsyncMock()) as get:
            self.assertEqual((await self.client.get('/api/admin/imports/not-a-batch',headers=self.headers)).status,400)
            get.assert_not_awaited()
    async def test_balance_requires_a_replay_key_and_supports_large_telegram_id(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(admin_tools,'change_balance',AsyncMock()) as change:
            r=await self.client.post('/api/admin/users/9000000000/balance',headers=self.headers,json={'amount':'100','mode':'add','currency':'RUB'})
            self.assertEqual(r.status,400);change.assert_not_awaited()
            r=await self.client.post('/api/admin/users/9000000000/balance',headers=self.headers,json={'amount':'100','mode':'add','currency':'RUB','operation_id':'a'*32})
            self.assertEqual(r.status,200);change.assert_awaited_once_with(42,9000000000,'100','RUB','add',request_key='a'*32)
    async def test_upload_size_and_type_are_bounded(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(imports,'create',AsyncMock()) as create:
            r=await self.client.post('/api/admin/imports',headers=self.headers,data=b'not a zip')
            self.assertEqual(r.status,400)
            r=await self.client.post('/api/admin/imports',headers=self.headers|{'Content-Type':'application/zip'},data=b'not a zip')
            self.assertEqual(r.status,400);create.assert_not_awaited()


class SessionEndpointTests(unittest.TestCase):
    def test_only_official_datacenter_endpoints_are_accepted(self):
        import tempfile,sqlite3
        from pathlib import Path
        from services.session_validation import validate_session_file
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.session'
            with sqlite3.connect(path) as connection:
                connection.execute('CREATE TABLE sessions(dc_id INTEGER,server_address TEXT,port INTEGER,auth_key BLOB)')
                connection.execute('INSERT INTO sessions VALUES(2,?,443,?)',('149.154.167.51',b'k'*256))
            validate_session_file(path)
            for address,port in [('127.0.0.1',443),('10.0.0.1',3306),('example.com',443),('149.154.167.51',3306)]:
                with sqlite3.connect(path) as connection:connection.execute('UPDATE sessions SET server_address=?,port=?',(address,port))
                with self.assertRaises(ValueError):validate_session_file(path)
    def test_view_cannot_impersonate_a_session_table(self):
        import tempfile,sqlite3
        from pathlib import Path
        from services.session_validation import validate_session_file
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.session'
            with sqlite3.connect(path) as connection:connection.execute('CREATE VIEW sessions AS SELECT 2 AS dc_id')
            with self.assertRaises(ValueError):validate_session_file(path)
