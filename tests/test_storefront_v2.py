"""New category-only UI, owner-bound quotes/chat and explicit public access."""
import unittest
from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,MagicMock,patch
from aiohttp.test_utils import TestClient,TestServer

from test_payments import db
import test_miniapp
from miniapp import server,storefront_api
from database import direct_chat,shop_navigation


class StorefrontTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_served_interface_has_categories_and_messages_without_cart_or_footer(self):
        r=await self.client.get('/');text=await r.text()
        self.assertEqual(r.status,200)
        self.assertIn('id="categories"',text);self.assertIn('data-tab="messages"',text)
        self.assertNotIn('Корзина',text);self.assertNotIn('legal-footer',text)
        self.assertNotIn('mekbuda',text);self.assertNotIn('Твой аккаунт.',text)

    async def test_quote_chooses_account_server_side_and_cannot_be_replayed_or_forged(self):
        item={'id':7,'price':Decimal('25.00'),'warranty_hours':24,'spam_status':'permanent'}
        with patch.object(shop_navigation,'products',AsyncMock(return_value=([item],1,0))) as pick:
            r=await self.client.post('/api/category-quote',headers=self.headers,json={'mode':'auto','nation':'us~permanent'})
            self.assertEqual(r.status,200);quote=await r.json()
            self.assertNotIn('account_id',quote);self.assertIn('Вечный СБ',quote['name'])
            pick.assert_awaited_once_with(42,'auto','us~permanent',quantity=1)
        with patch.object(server.storage,'checkout',AsyncMock(return_value={'id':11,'balance':'75','paid_amount':'25'})) as checkout:
            other={'Authorization':'tma '+test_miniapp.signed_data(43)}
            r=await self.client.post('/api/category-buy',headers=other,json={'token':quote['token']})
            self.assertEqual(r.status,409);checkout.assert_not_awaited()
            body={'token':quote['token'],'account_id':999,'price':'0'}
            self.assertEqual((await self.client.post('/api/category-buy',headers=self.headers,json=body)).status,201)
            self.assertEqual((await self.client.post('/api/category-buy',headers=self.headers,json=body)).status,409)
            checkout.assert_awaited_once_with(42,7,Decimal('25.00'),warranty_hours=24,spam_status='permanent')

    async def test_chat_uses_signed_owner_and_stores_plain_text_without_tickets(self):
        with patch.object(direct_chat,'history',AsyncMock(return_value={'items':[],'has_more':False})) as history:
            r=await self.client.get('/api/chat?user_id=999',headers=self.headers)
            self.assertEqual(r.status,200);history.assert_awaited_once_with(42,0)
        with patch.object(direct_chat,'append',AsyncMock(return_value=5)) as save:
            r=await self.client.post('/api/chat',headers=self.headers,json={'body':'<script>test</script>','user_id':999})
            self.assertEqual(r.status,201);save.assert_awaited_once_with(42,'user','<script>test</script>')

    async def test_admin_chat_and_switch_reject_regular_users(self):
        with patch.object(direct_chat,'inbox',AsyncMock()) as inbox,patch.object(storefront_api,'public_access',AsyncMock()) as access:
            for method,path in [('GET','app-access'),('POST','app-access'),('GET','conversations'),('POST','conversations/43')]:
                r=await self.client.request(method,'/api/admin/'+path,headers=self.headers,json={'enabled':True,'body':'text'})
                self.assertEqual(r.status,403)
            inbox.assert_not_awaited();access.assert_not_awaited()

    async def test_admin_can_reply_to_the_selected_customer(self):
        with patch.object(server.config,'ADMIN_IDS',[42]),patch.object(direct_chat,'append',AsyncMock(return_value=8)) as save:
            r=await self.client.post('/api/admin/conversations/43',headers=self.headers,json={'body':'Ответ','user_id':999})
            self.assertEqual(r.status,201);save.assert_awaited_once_with(43,'admin','Ответ')

    async def test_public_access_is_an_explicit_audited_admin_change(self):
        from contextlib import asynccontextmanager
        cur=NS(execute=AsyncMock())
        @asynccontextmanager
        async def transaction(): yield cur
        with patch.object(server.config,'ADMIN_IDS',[42]),patch.object(storefront_api,'_transaction',transaction),patch.object(storefront_api,'_record',AsyncMock()) as audit,patch.object(storefront_api,'public_access',AsyncMock(return_value=True)):
            r=await self.client.post('/api/admin/app-access',headers=self.headers,json={'enabled':True})
            self.assertEqual(r.status,200);self.assertTrue((await r.json())['enabled'])
            self.assertEqual(cur.execute.call_args.args[1],('1',))
            audit.assert_awaited_once_with(cur,42,'miniapp_public_access','settings','miniapp_public_access',{'enabled':True})

    async def test_production_default_has_no_cart_http_routes(self):
        async with TestClient(TestServer(server.create_app(token=test_miniapp.TEST_TOKEN))) as client:
            with patch.object(server.config,'ADMIN_IDS',[42]),patch.object(server.commerce,'add_to_cart',AsyncMock()) as reserve:
                for method,path in [('GET','/api/cart'),('POST','/api/cart'),('POST','/api/cart/checkout')]:
                    r=await client.request(method,path,headers=self.headers,json={'account_id':1})
                    self.assertEqual(r.status,404)
                reserve.assert_not_awaited()

    async def test_public_switch_changes_gate_without_exposing_admin_routes(self):
        async with TestClient(TestServer(server.create_app(token=test_miniapp.TEST_TOKEN))) as client:
            with patch.object(server.config,'ADMIN_IDS',[99]),patch.object(storefront_api,'public_access',AsyncMock(return_value=False)):
                self.assertEqual((await client.get('/api/storefront-preview',headers=self.headers)).status,403)
            with patch.object(server.config,'ADMIN_IDS',[99]),patch.object(storefront_api,'public_access',AsyncMock(return_value=True)):
                self.assertEqual((await client.get('/api/storefront-preview',headers=self.headers)).status,200)
                self.assertEqual((await client.get('/api/admin/app-access',headers=self.headers)).status,403)


class ChatSynchronizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_reply_is_visible_in_the_same_web_conversation(self):
        from handlers import direct_support
        msg=NS(from_user=NS(id=99),chat=NS(id=99),message_id=1,text='Ответ',caption=None,content_type='text',answer=AsyncMock(),bot=NS(send_message=AsyncMock(),copy_message=AsyncMock()))
        state=NS(get_data=AsyncMock(return_value={'support_recipient':42}))
        with patch.object(direct_support,'ADMIN_IDS',[99]),patch.object(direct_chat,'append',AsyncMock()) as save:
            await direct_support.admin_message(msg,state)
            save.assert_awaited_once_with(42,'admin','Ответ')
