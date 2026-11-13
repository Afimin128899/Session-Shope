import io
import json
import zipfile
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from test_payments import config
from services.session_metadata import parse_metadata,match_identity
from services.archive_import import inspect_archive,process
from database import imports

class MetadataTests(unittest.TestCase):
    def test_explicit_date_only(self):
        self.assertEqual(parse_metadata(b'{"registration_date":"2020-01-02"}')['registration_date'],'2020-01-02')
        self.assertIsNone(parse_metadata(b'{"session_created":123}')['registration_date'])
        for value in ('2099-01-01','bad',True,[], '2010-01-01'):
            with self.assertRaises(ValueError):parse_metadata(json.dumps({'registration_date':value}).encode())
    def test_identity_mismatch_rejected(self):
        for value in ({'phone':'+1999'},{'user_id':99}):
            with self.assertRaises(ValueError):match_identity(value,'+15551112222',42)
    def test_paired_json_accepted_but_unpaired_rejected(self):
        for paired in (True,False):
            buffer=io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as z:
                if paired:z.writestr('account.session',b'SQLite format 3\0fixture')
                z.writestr('account.json',b'{"registration_date":"2020-01-02"}')
            if paired:self.assertEqual(len(inspect_archive(buffer.getvalue())),2)
            else:
                with self.assertRaises(ValueError):inspect_archive(buffer.getvalue())

class ProcessTests(unittest.IsolatedAsyncioTestCase):
    async def test_matching_existing_session_prepares_metadata_update_without_duplicate(self):
        from services import archive_import
        async def verifier(path,metadata):
            metadata.update(telegram_user_id=42,is_premium=False)
            return 'fixture','+15551112222',None
        files=[('account.session',b'SQLite format 3\0fixture'),('account.json',b'{"registration_date":"2020-01-02","user_id":42}')]
        with patch.object(imports,'preview',AsyncMock(return_value={'status':'checking'})),patch.object(imports,'add_item',AsyncMock()) as add,patch.object(imports,'finish',AsyncMock()),patch.object(archive_import,'rows',AsyncMock(return_value=[{'id':7,'status':'available','data':'fixture'}])):
            await process(1,'batch',files,verifier)
        self.assertEqual(add.call_args.kwargs['existing_account'],7)
        self.assertEqual(add.call_args.kwargs['registration_date'],'2020-01-02')
        self.assertEqual(add.call_args.args[2],'ready')

class CommitMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_account_date_updated_without_repricing_or_duplicate_insert(self):
        from contextlib import asynccontextmanager
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[{'status':'ready'},{'session_data':'fixture','account_id':7,'telegram_id':42,'registration_date':'2020-01-02','phone':'+15551112222','premium':False},{'id':7}]))
        @asynccontextmanager
        async def tx():yield cur
        with patch.object(imports,'_transaction',tx),patch.object(imports,'_record',AsyncMock()):
            ids=await imports.commit(1,'batch',[{'id':10,'price':'999','category':'auto'}])
        self.assertEqual(ids,[7])
        queries=[c.args[0] for c in cur.execute.call_args_list]
        updates=[q for q in queries if q.startswith('UPDATE accounts')]
        self.assertEqual(len(updates),1)
        self.assertNotIn('price=',updates[0])
        self.assertFalse(any('INSERT INTO accounts' in q for q in queries))
