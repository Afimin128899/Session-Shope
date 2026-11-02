"""New marketplace boundaries, provider identity and polling behavior."""
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch
from test_payments import config
import test_miniapp
from miniapp import server, storage
from services import payments, cryptopay


class MarketplaceAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown = test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_cart_and_favorite_mutations_always_use_signed_owner(self):
        for path, function, body in [('cart','add_to_cart',{'account_id':1,'user_id':99}),('favorites','favorite',{'account_id':1,'enabled':True,'user_id':99})]:
            with patch.object(server.commerce,function,AsyncMock()) as call:
                res=await self.client.post('/api/'+path,headers=self.headers,json=body)
                self.assertEqual(res.status,200)
                self.assertEqual(call.call_args.args[0],42)

    async def test_invalid_cart_quote_never_reaches_checkout(self):
        with patch.object(storage,'checkout_cart',AsyncMock()) as checkout:
            for items in [[],[{'account_id':True,'price':'1'}],[{'account_id':1,'price':'Infinity'}],[{'account_id':1,'price':'1.001'}],[{'account_id':1,'price':100}],None]:
                res=await self.client.post('/api/cart/checkout',headers=self.headers,json={'items':items})
                self.assertEqual(res.status,400)
            checkout.assert_not_awaited()

    async def test_price_filter_rejects_nan_and_reversed_bounds(self):
        with patch.object(storage,'catalog',AsyncMock()) as call:
            for query in ['min_price=NaN','max_price=Infinity','min_price=-1','min_price=100&max_price=10']:
                self.assertEqual((await self.client.get('/api/catalog?'+query,headers=self.headers)).status,400)
            call.assert_not_awaited()

    async def test_private_invoice_status_never_accepts_query_owner(self):
        with patch.object(server.commerce,'invoice',AsyncMock(return_value=None)) as call:
            res=await self.client.get('/api/invoices/crypto/123?user_id=99',headers=self.headers)
            self.assertEqual(res.status,404)
            call.assert_awaited_once_with('crypto','123',42)


class AutomaticPaymentTests(unittest.IsolatedAsyncioTestCase):
    async def test_wrong_invoice_owner_amount_or_identity_never_credits(self):
        row={'provider':'crypto','invoice_id':'1','user_id':42,'amount_rub':Decimal(100)}
        with patch.object(payments.db,'credit_paid_deposit',AsyncMock()) as call:
            for invoice in [{'invoice_id':'2','status':'paid','payload':'rub_topup:42:100'}, {'invoice_id':'1','status':'paid','payload':'rub_topup:43:100'},{'invoice_id':'1','status':'paid','payload':'rub_topup:42:101'}]:
                with self.assertRaises(ValueError): await payments.settle_invoice(row,invoice)
            call.assert_not_awaited()

    async def test_unpaid_invoice_never_credits(self):
        with patch.object(payments.db,'credit_paid_deposit',AsyncMock()) as call:
            await payments.settle_invoice({'provider':'crypto'},{'status':'active'})
            call.assert_not_awaited()

    async def test_crypto_api_items_envelope_selects_exact_invoice(self):
        with patch.object(cryptopay,'_request',AsyncMock(return_value={'items':[{'invoice_id':12},{'invoice_id':13}]})):
            self.assertEqual(await cryptopay.get_invoice('13'),{'invoice_id':13})
            self.assertIsNone(await cryptopay.get_invoice('14'))

    async def test_bad_amount_never_calls_external_provider(self):
        for amount in ['NaN','Infinity','9','1000001','10.001','-1']:
            with self.assertRaises(ValueError): await payments.create_deposit(42,'test','crypto',amount)

    async def test_invoice_persisted_before_payment_link_is_returned(self):
        with patch.object(config,'CRYPTO_PAY_TOKEN','fake-test-token'), patch.object(cryptopay,'create_invoice',AsyncMock(return_value={'invoice_id':12,'bot_invoice_url':'https://t.me/test_invoice'})),patch.object(payments.commerce,'register_invoice',AsyncMock(side_effect=OSError('DB down'))) as save:
            with self.assertRaises(OSError): await payments.create_deposit(42,'test','crypto','100')
            save.assert_awaited_once_with('crypto','12',42,Decimal(100))

    async def test_worker_sends_receipt_only_for_new_credit(self):
        row={'provider':'crypto','invoice_id':'1','user_id':42,'amount_rub':Decimal(100)}
        bot=AsyncMock()
        with patch.object(payments.commerce,'pending_invoices',AsyncMock(return_value=[row])),patch.object(payments.commerce,'lease_invoice',AsyncMock(return_value=True)),patch.object(cryptopay,'get_invoice',AsyncMock(return_value={'status':'paid'})),patch.object(payments,'settle_invoice',AsyncMock(side_effect=[(110,10),None])):
            await payments.check_pending(bot);await payments.check_pending(bot)
        bot.send_message.assert_awaited_once()

    async def test_expired_provider_status_is_persisted_without_credit(self):
        row={'provider':'crypto','invoice_id':'1','user_id':42,'amount_rub':Decimal(100)}
        with patch.object(payments.commerce,'finish_invoice',AsyncMock()) as finish,patch.object(payments.db,'credit_paid_deposit',AsyncMock()) as credit:
            await payments.settle_invoice(row,{'status':'expired'})
            finish.assert_awaited_once_with('crypto','1','expired')
            credit.assert_not_awaited()
