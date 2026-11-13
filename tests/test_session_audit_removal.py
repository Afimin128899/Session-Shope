"""A failed audit is hidden before delivery and deleted only after delivery succeeds."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from contextlib import asynccontextmanager
from test_payments import config
from database import session_audit as storage
from handlers.admin import spam_checks as handler

class RemovalTests(unittest.IsolatedAsyncioTestCase):
    async def test_hide_does_not_delete_and_checks_purchase_and_reservation(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[{'id':1},None,None]))
        @asynccontextmanager
        async def tx(): yield cur
        account={'id':1,'data':'private'}
        with patch.object(storage,'_transaction',tx),patch.object(storage,'_record',AsyncMock()):
            self.assertTrue(await storage.hide_failed(42,account,'token'))
        sql=[call.args[0] for call in cur.execute.call_args_list]
        self.assertTrue(any("status='review'" in q for q in sql))
        self.assertFalse(any('DELETE FROM accounts' in q for q in sql))

    async def test_sold_account_is_not_hidden_or_deleted(self):
        for operation in ('hide','delete'):
            cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[{'id':1},{'id':7}]))
            @asynccontextmanager
            async def tx(): yield cur
            with patch.object(storage,'_transaction',tx):
                if operation=='hide': result=await storage.hide_failed(42,{'id':1,'data':'private'},'token')
                else: result=await storage.delete_delivered(42,{'id':1,'data':'private'})
            self.assertFalse(result)
            self.assertFalse(any('DELETE' in call.args[0] for call in cur.execute.call_args_list))

    async def run_handler(self, delivery_fails):
        events=[]
        account={'id':1,'data':'fixture','number':'fixture','telegram_user_id':99,'registration_date':None,'status':'available'}
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[account,None]))
        @asynccontextmanager
        async def tx(): yield cur
        async def hide(*args): events.append('hide');return True
        async def deliver(*args,**kwargs):
            events.append('deliver')
            if delivery_fails: raise RuntimeError('delivery failed')
        async def delete(*args): events.append('delete');return True
        message=NS(from_user=NS(id=42),answer=AsyncMock(),answer_document=AsyncMock(side_effect=deliver))
        with patch.object(handler,'ADMIN_IDS',[42]),patch('database.admin_web.rows',AsyncMock(side_effect=[[{'id':1}],[]])),patch('database.admin_tools._transaction',tx),patch('services.session_audit.clean_other_sessions',AsyncMock(return_value={'status':'failed','reason':'telegram_error'})),patch('services.session_audit.session_file_bytes',return_value=b'fixture'),patch.object(storage,'hide_failed',side_effect=hide),patch.object(storage,'delete_delivered',side_effect=delete):
            if delivery_fails:
                with self.assertRaises(RuntimeError): await handler.audit_sessions(message)
            else: await handler.audit_sessions(message)
        self.assertFalse(handler._audit_running)
        return events

    async def test_deletion_happens_after_document_delivery(self):
        self.assertEqual(await self.run_handler(False),['hide','deliver','delete'])

    async def test_failed_delivery_keeps_hidden_account_for_retry(self):
        self.assertEqual(await self.run_handler(True),['hide','deliver'])
