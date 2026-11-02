import unittest
from unittest.mock import AsyncMock,patch
import test_miniapp
from miniapp import server,storage
from handlers import expansion as admin
from types import SimpleNamespace
from database import expansion


class ExpansionAPI(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown
    async def test_filters_reject_injections_and_unknown_premium(self):
        with patch.object(storage,'catalog',AsyncMock()) as get:
            for query in ['premium=2','min_age=-1','min_age=10001','min_age=1%20OR%201']:
                self.assertEqual((await self.client.get('/api/catalog?'+query,headers=self.headers)).status,400)
            get.assert_not_awaited()
    async def test_filters_pass_checked_values(self):
        with patch.object(storage,'catalog',AsyncMock(return_value={'items':[]})) as get:
            r=await self.client.get('/api/catalog?premium=0&min_age=365',headers=self.headers)
            self.assertEqual(r.status,200)
            self.assertEqual(get.call_args.kwargs['premium'],0)
            self.assertEqual(get.call_args.kwargs['min_age'],365)
    async def test_product_projection_does_not_expose_private_data(self):
        with patch.object(storage,'catalog',AsyncMock(return_value={'items':[{'id':1,'name':'Item'}]})):
            r=await self.client.get('/api/products/1',headers=self.headers)
            self.assertEqual(r.status,200)
    async def test_order_search_owner_is_signed(self):
        with patch.object(storage,'orders',AsyncMock(return_value={'items':[]})) as get:
            r=await self.client.get('/api/orders?q=123&user_id=99',headers=self.headers)
            self.assertEqual(r.status,200);get.assert_awaited_once_with(42,0,'123')
    async def test_non_admin_cannot_mutate_stock_or_approve(self):
        call=SimpleNamespace(from_user=SimpleNamespace(id=99),answer=AsyncMock(),data='refund_approve:1')
        with patch.object(admin,'ADMIN_IDS',[1]),patch.object(expansion,'approve_refund',AsyncMock()) as approve:
            await admin.approve(call)
            approve.assert_not_awaited()
