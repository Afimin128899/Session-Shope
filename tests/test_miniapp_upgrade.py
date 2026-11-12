"""Country drilldown, signed avatars and owner-only Mini App login codes."""
import json
import unittest
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace as NS
from decimal import Decimal
from test_payments import db
import test_miniapp
from miniapp import server
from miniapp.auth import validate_init_data,photo_url
from database import shop_navigation
from services import telethon_code


class MiniAppUpgradeTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_country_cards_aggregate_stock_and_price_before_status_drilldown(self):
        rows=[{'country':'us','nation':'us~'+status,'spam_status':status,'name':'old','count':count,'min_price':Decimal(price)} for status,count,price in [('clear',4,'74'),('permanent',2,'59'),('unverified',3,'50')]]
        with patch.object(shop_navigation,'countries',AsyncMock(return_value=rows)):
            r=await self.client.get('/api/category-market',headers=self.headers)
            items=(await r.json())['items'];self.assertEqual(len(items),1)
            self.assertEqual(items[0]['name'],'США');self.assertEqual(items[0]['count'],9)
            self.assertEqual(Decimal(items[0]['min_price']),50);self.assertEqual(items[0]['groups'],3)
            r=await self.client.get('/api/category-market?country=us',headers=self.headers)
            items=(await r.json())['items']
            self.assertEqual([i['name'] for i in items],['США Без спамблока','США Вечный СБ','США'])
            self.assertEqual([Decimal(i['min_price']) for i in items],[74,59,50])
            self.assertEqual((await self.client.get('/api/category-market?country=wrong',headers=self.headers)).status,400)

    async def test_active_owner_can_receive_code_without_exposing_session(self):
        order={'status':'issued','data':'PRIVATE_SESSION','number':'+15550000111'}
        with patch.object(db,'get_purchase_for_user',AsyncMock(return_value=order)) as lookup,patch.object(telethon_code,'try_fetch_login_code',AsyncMock(return_value='12345')) as fetch:
            r=await self.client.post('/api/orders/7/code',headers=self.headers,json={'user_id':999})
            self.assertEqual(r.status,200);self.assertEqual(await r.json(),{'status':'ready','code':'12345'})
            self.assertNotIn('PRIVATE',await r.text());self.assertEqual(lookup.await_count,2)
            lookup.assert_awaited_with(7,42);fetch.assert_awaited_once_with('PRIVATE_SESSION','+15550000111')

    async def test_foreign_completed_or_refunded_order_never_reads_telegram(self):
        for order,status in [(None,404),({'status':'completed','data':'private'},409),({'status':'refunded','data':'private'},409)]:
            with patch.object(db,'get_purchase_for_user',AsyncMock(return_value=order)),patch.object(telethon_code,'try_fetch_login_code',AsyncMock()) as fetch:
                r=await self.client.post('/api/orders/7/code',headers=self.headers,json={})
                self.assertEqual(r.status,status);fetch.assert_not_awaited()
        self.assertEqual((await self.client.post('/api/orders/7/code',json={})).status,401)

    async def test_code_is_discarded_if_order_changes_while_waiting(self):
        order={'status':'issued','data':'private','number':'+1555'}
        with patch.object(db,'get_purchase_for_user',AsyncMock(side_effect=[order,dict(order,status='refunded')])),patch.object(telethon_code,'try_fetch_login_code',AsyncMock(return_value='12345')):
            r=await self.client.post('/api/orders/7/code',headers=self.headers,json={})
            self.assertEqual(r.status,409);self.assertNotIn('12345',await r.text())

    async def test_pending_and_revoked_session_are_distinguished(self):
        order={'status':'issued','data':'private','number':'+1555'}
        for code,status in [(None,200),('SESSION_NOT_AUTHORIZED',409),('unexpected-private-text',200)]:
            with patch.object(db,'get_purchase_for_user',AsyncMock(return_value=order)),patch.object(telethon_code,'try_fetch_login_code',AsyncMock(return_value=code)):
                r=await self.client.post('/api/orders/7/code',headers=self.headers,json={})
                self.assertEqual(r.status,status);self.assertNotIn('unexpected-private-text',await r.text())
                if status==200:self.assertEqual((await r.json())['status'],'pending')

    async def test_avatar_fallback_uses_verified_owner_and_private_cache(self):
        self.bot.get_user_profile_photos=AsyncMock(return_value=NS(photos=[[NS(file_id='own-photo')]]))
        self.bot.get_file=AsyncMock(return_value=NS(file_path='photos/own.jpg',file_size=4))
        async def download(path,*,destination,timeout):destination.write(b'JPEG')
        self.bot.download_file=AsyncMock(side_effect=download)
        for _ in range(2):
            r=await self.client.get('/api/avatar?user_id=999',headers=self.headers)
            self.assertEqual(r.status,200);self.assertEqual(await r.read(),b'JPEG')
            self.assertEqual(r.headers['Cache-Control'],'no-store')
        self.bot.get_user_profile_photos.assert_awaited_once_with(42,limit=1)
        self.assertEqual((await self.client.get('/api/avatar')).status,401)


class SignedPhotoTests(unittest.TestCase):
    def test_avatar_only_comes_from_signed_telegram_user(self):
        url='https://t.me/i/userpic/320/test.jpg'
        user=json.dumps({'id':42,'photo_url':url})
        result=validate_init_data(test_miniapp.signed_data(user=user),test_miniapp.TEST_TOKEN)
        self.assertEqual(result['photo_url'],url)
        for value in ['http://t.me/i/a.jpg','https://evil.test/a.jpg','https://t.me.evil.test/a.jpg','https://x@t.me/a','data:image/png,abc']:
            self.assertIsNone(photo_url(value))
