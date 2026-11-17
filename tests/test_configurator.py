"""Live configurator quote ownership, prices, replay protection and export revocation."""
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch
import test_miniapp
from test_payments import config
from miniapp import server, configurator_api
from database import shop_navigation, expansion, partners


class ConfiguratorTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown = test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_preview_uses_real_filters_and_rounds_each_item(self):
        items = [{'price': '33.33', 'warranty_hours': 24}] * 3
        with patch.object(shop_navigation, 'products', AsyncMock(return_value=(items, 148, 0))) as select, patch.object(expansion, 'rules', AsyncMock(return_value={'minimum': '90', 'percent': '10'})):
            r = await self.client.post('/api/configurator/preview', headers=self.headers, json={'country':'us','age':180,'premium':True,'two_fa':True,'clear':True})
            self.assertEqual(r.status, 200)
            data = await r.json()
            self.assertEqual(data['count'], 148)
            self.assertEqual(data['quantities'][-1]['total'], '90.00')
            self.assertEqual(data['quantities'][1]['total'], '66.66')
            select.assert_awaited_once_with(42, 'premium', 'us~clear', quantity=20, min_age=180, two_fa=True)

    async def test_invalid_selection_does_not_reach_database(self):
        with patch.object(shop_navigation, 'products', AsyncMock()) as select:
            for body in ({'country':'invalid'}, {'country':'us','age':True}, {'country':'us','premium':'1'}, {'country':'us','age':999}):
                r = await self.client.post('/api/configurator/preview', headers=self.headers, json=body)
                self.assertEqual(r.status, 400)
            select.assert_not_awaited()

    async def test_server_quote_owner_replay_and_total(self):
        saved = {'items':[{'account_id':7,'price':'100','warranty_hours':24}], 'total':'90.00', 'rate':'10', 'created_ids':[7]}
        with patch.object(shop_navigation, 'reserve_bulk', AsyncMock(return_value=saved)), patch.object(server, 'limited', return_value=False):
            r = await self.client.post('/api/configurator/quote', headers=self.headers, json={'country':'us','age':7,'quantity':1})
            self.assertEqual(r.status, 200)
            token = (await r.json())['token']
        with patch.object(server.storage, 'checkout_cart', AsyncMock(return_value={'order_ids':[11],'paid_amount':'90.00'})) as buy:
            other = {'Authorization':'tma '+test_miniapp.signed_data(43)}
            r = await self.client.post('/api/configurator/buy', headers=other, json={'token':token})
            self.assertEqual(r.status, 409)
            buy.assert_not_awaited()
            r = await self.client.post('/api/configurator/buy', headers=self.headers, json={'token':token,'total':'0','items':[]})
            self.assertEqual(r.status, 201)
            buy.assert_awaited_once_with(42, saved['items'], expected_total=Decimal('90.00'))
            self.assertEqual((await self.client.post('/api/configurator/buy', headers=self.headers, json={'token':token})).status, 409)

    async def test_expired_quote_never_charges_wallet(self):
        server_quote = {'user':42,'wallet_bot_id':0,'expires':0,'items':[],'total':'10'}
        self.client.server.app[configurator_api.QUOTES]['expired'] = server_quote
        with patch.object(server.storage, 'checkout_cart', AsyncMock()) as buy:
            r = await self.client.post('/api/configurator/buy', headers=self.headers, json={'token':'expired'})
            self.assertEqual(r.status,409);buy.assert_not_awaited()

    async def test_archive_is_owner_scoped_and_rechecks_access_after_build(self):
        order = {'id':7,'data':'private','status':'issued'}
        revoked = dict(order, data=None, access_revoked_at='now')
        with patch.object(server.db, 'get_purchase_for_user', AsyncMock(side_effect=[order, revoked])) as get, patch.object(configurator_api, 'archive_bytes', return_value=b'private-zip'):
            r = await self.client.get('/api/orders/7/archive', headers=self.headers)
            self.assertEqual(r.status,409)
            self.assertNotIn('private-zip',await r.text())
            self.assertEqual(get.call_args_list[0].args,(7,42))

    async def test_revoked_or_refunded_archive_is_not_built(self):
        for order in (None, {'status':'refunded','data':'private'}, {'status':'issued','data':None,'access_revoked_at':'now'}):
            with patch.object(server.db, 'get_purchase_for_user', AsyncMock(return_value=order)), patch.object(configurator_api, 'archive_bytes') as build:
                r = await self.client.get('/api/orders/7/archive', headers=self.headers)
                self.assertIn(r.status,(404,409));build.assert_not_called()

    async def test_bans_require_admin_and_use_signed_actor(self):
        with patch.object(partners,'ban',AsyncMock()) as ban:
            r=await self.client.post('/api/admin/user-bans',headers=self.headers,json={'user_id':43,'reason':'Abuse','enabled':True})
            self.assertEqual(r.status,403);ban.assert_not_awaited()
            with patch.object(config,'ADMIN_IDS',[42]),patch('database.admin_web.rows',AsyncMock(return_value=[])):
                r=await self.client.post('/api/admin/user-bans',headers=self.headers,json={'user_id':43,'reason':'Abuse','enabled':True,'admin_id':999})
                self.assertEqual(r.status,200);ban.assert_awaited_once_with(42,0,43,'Abuse',True)

    async def test_issued_archive_download_is_private_and_has_order_filename(self):
        order={'id':7,'data':'private','status':'issued'}
        with patch.object(server.db,'get_purchase_for_user',AsyncMock(return_value=order)),patch.object(configurator_api,'archive_bytes',return_value=b'PK-test'):
            r=await self.client.get('/api/orders/7/archive',headers=self.headers)
            self.assertEqual(r.status,200)
            self.assertEqual(await r.read(),b'PK-test')
            self.assertIn('tg-order-7.zip',r.headers['Content-Disposition'])
            self.assertEqual(r.headers['Cache-Control'],'no-store')

    async def test_archive_contains_session_metadata_and_optional_password(self):
        import io,json,zipfile
        with patch('services.session_audit.session_file_bytes',return_value=b'SQLite fixture'):
            data=configurator_api.archive_bytes({'id':7,'data':'secret','password':'cloud-password','telegram_user_id':123})
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            self.assertEqual(set(archive.namelist()),{'account.session','account.json','2fa.txt'})
            self.assertEqual(archive.read('account.session'),b'SQLite fixture')
            self.assertEqual(archive.read('2fa.txt'),b'cloud-password')
            metadata=json.loads(archive.read('account.json'))
            self.assertEqual(metadata['id'],7)
            self.assertNotIn('data',metadata)
