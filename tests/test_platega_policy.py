"""Offline contracts for Platega, new-sale limits and public compliance links."""
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import config, db
import test_provider_apis
import test_miniapp
from services import payments, platega, stars
from database import admin_tools, shop_control, sales_policy, imports
from database import stars as ledger
from utils import commerce_policy as policy
from utils.legal import PRIVACY_URL, AGREEMENT_URL

IDENTITY='1a413e35-0db0-48b5-bf29-2461e0652df0'
MERCHANT='631790a6-375b-4dc7-8a19-e9641fb8b0a0'
ROW={'provider':'platega','invoice_id':IDENTITY,'user_id':42,'amount_rub':Decimal('500.00')}
PAID={'id':IDENTITY,'status':'CONFIRMED','payload':'rub_topup:42:500.00',
      'merchantId':MERCHANT,'paymentDetails':{'amount':500,'currency':'RUB'}}


class PolicyValues(unittest.TestCase):
    def test_new_funding_and_prices_have_exact_boundaries(self):
        self.assertEqual(payments.parse_amount('10 000,00'),10000)
        self.assertEqual(policy.money('10000.00'),10000)
        for value in ['10000.01','1000000','Infinity','NaN',True,'-1','0','10.001']:
            with self.subTest(value=value),self.assertRaises(ValueError):policy.money(value)
        for value in ['10000.01','1000000','9.99']:
            with self.assertRaises(ValueError):payments.parse_amount(value)

    def test_stars_floor_at_ruble_limit_does_not_reject_historical_receipts(self):
        self.assertEqual(ledger.parse_new_count('8333')*ledger.STARS_RATE,Decimal('9999.60'))
        with self.assertRaises(ValueError):ledger.parse_new_count(8334)
        self.assertEqual(ledger.parse_count(10000),10000)

    def test_phone_country_is_checked_independently_of_category(self):
        for phone in ['+79991234567','7 (495) 123-45-67','00380991234567','+380991234567','８９９９１２３４５６７','+7 800 1234567']:
            with self.subTest(phone=phone),self.assertRaises(ValueError):
                policy.require_stock({'country':'us','number':phone,'price':100,'category_name':'USA'})
        for phone in ['+77011234567','+7 (701) 123-45-67','+76123456789','+15551234567','+81312345678','+84901234567']:
            with self.subTest(phone=phone):policy.require_phone(phone)

    def test_country_names_aliases_flags_and_unicode_are_blocked(self):
        for value in ['RU','ua','Russia','Россия 🇷🇺','Україна','РФ','russian_accounts','UKRAINE','ＲＵ','🇺🇦 Premium']:
            with self.subTest(value=value):self.assertFalse(policy.category_allowed(value))
        self.assertTrue(policy.category_allowed('kz','Казахстан 🇰🇿'))
        self.assertTrue(policy.category_allowed('us','Prussia collection'))


class PlategaWire(unittest.IsolatedAsyncioTestCase):
    response=test_provider_apis.ProviderAPITests.response
    def setUp(self):
        p=patch.multiple(config,PLATEGA_MERCHANT_ID=MERCHANT,PLATEGA_SECRET='fixture-only-secret',create=True)
        p.start();self.addCleanup(p.stop)

    async def test_sbp_request_has_stable_telegram_metadata_and_no_email_form(self):
        _,session,factory=self.response(platega,{'transactionId':IDENTITY,'redirect':'https://app.platega.io/pay/fixture'})
        result=await platega.create_invoice('500.00','Top-up','rub_topup:42:500.00',42)
        self.assertEqual(result['id'],IDENTITY)
        self.assertEqual(session.request.call_args.args,('POST','https://app.platega.io/transaction/process'))
        options=session.request.call_args.kwargs
        self.assertEqual(options['json']['metadata'],{'user_email':'42@telegram.org'})
        self.assertEqual(options['json']['paymentDetails'],{'paymentMethod':2,'amount':500,'currency':'RUB'})
        self.assertEqual(options['json']['paymentMethod'],2)
        self.assertEqual(options['headers']['X-MerchantId'],MERCHANT)
        self.assertEqual(options['headers']['X-Secret'],'fixture-only-secret')
        self.assertFalse(options['allow_redirects']);self.assertTrue(factory.call_args.kwargs['trust_env'])
        self.assertEqual(session.request.call_count,1)

    async def test_bad_amount_or_untrusted_identity_never_calls_provider(self):
        with patch.object(platega,'_request',AsyncMock()) as send:
            for amount,user in [('10000.01',42),('500',True),('500',0),('500','42')]:
                with self.assertRaises(ValueError):await platega.create_invoice(amount,'x','x',user)
            send.assert_not_awaited()

    async def test_disabled_keys_and_http_failure_do_not_retry_creating_invoice(self):
        _,session,_=self.response(platega,{'error':'private'},status=403)
        self.assertIsNone(await platega.create_invoice(500,'x','x',42))
        self.assertEqual(session.request.call_count,1)
        with patch.object(config,'PLATEGA_SECRET',''):
            self.assertIsNone(await platega.create_invoice(500,'x','x',42))
        self.assertEqual(session.request.call_count,1)

    async def test_status_only_fetches_a_canonical_uuid_with_authentication(self):
        _,session,_=self.response(platega,PAID)
        self.assertEqual(await platega.get_invoice(IDENTITY),PAID)
        self.assertEqual(session.request.call_args.args,('GET','https://app.platega.io/transaction/'+IDENTITY))
        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])
        for value in ['../secrets','https://another.example/x',True,{},None,'x'*129]:
            self.assertIsNone(await platega.get_invoice(value))
        self.assertEqual(session.request.call_count,1)

    async def test_confirmed_invoice_is_credited_through_atomic_shared_ledger(self):
        with patch.object(db,'credit_paid_deposit',AsyncMock(return_value=(550,50))) as credit,patch.object(payments.commerce,'finish_invoice',AsyncMock()) as finish:
            self.assertEqual(await payments.settle_invoice(ROW,PAID),(550,50))
            credit.assert_awaited_once_with(42,Decimal('500'),'platega',IDENTITY)
            finish.assert_awaited_once_with('platega',IDENTITY,'credited',550)

    async def test_identity_owner_amount_currency_and_merchant_must_all_match(self):
        invoices=[]
        for key,value in [('id','f'*36),('payload','rub_topup:99:500.00'),('payload','rub_topup:42:1000.00'),('merchantId','another-merchant')]:
            invoice=deepcopy(PAID);invoice[key]=value;invoices.append(invoice)
        for details in [{'amount':499,'currency':'RUB'},{'amount':500,'currency':'USD'},{'amount':'NaN','currency':'RUB'},None]:
            invoice=deepcopy(PAID);invoice['paymentDetails']=details;invoices.append(invoice)
        with patch.object(db,'credit_paid_deposit',AsyncMock()) as credit:
            for invoice in invoices:
                with self.subTest(invoice=invoice),self.assertRaises(ValueError):await payments.settle_invoice(ROW,invoice)
            credit.assert_not_awaited()

    async def test_redirect_and_pending_or_chargeback_status_do_not_credit(self):
        with patch.object(db,'credit_paid_deposit',AsyncMock()) as credit,patch.object(payments.commerce,'finish_invoice',AsyncMock()):
            for status in ['PENDING','CHARGEBACKED','CANCELED','paid','confirmed']:
                self.assertIsNone(await payments.settle_invoice(ROW,{**PAID,'status':status}))
            credit.assert_not_awaited()

    async def test_creation_uses_rubles_without_exchange_and_registers_exact_owner(self):
        with patch.object(platega,'create_invoice',AsyncMock(return_value={'id':IDENTITY,'pay_url':'https://app.platega.io/pay/fixture'})) as create,patch.object(payments.commerce,'register_invoice',AsyncMock()) as register,patch.object(payments,'_health',AsyncMock()),patch.object(payments,'convert_rub_to_usdt',AsyncMock()) as fx:
            result=await payments.create_deposit(42,'username-is-not-id','platega','500')
            self.assertEqual(create.call_args.args[-1],42)
            self.assertEqual(result['amount'],'500')
            register.assert_awaited_once_with('platega',IDENTITY,42,Decimal('500'))
            fx.assert_not_awaited()

    async def test_legacy_paid_invoice_above_new_limit_is_still_settled(self):
        row={**ROW,'provider':'crypto','invoice_id':'123','amount_rub':Decimal(12000)}
        invoice={'invoice_id':123,'status':'paid','payload':'rub_topup:42:12000.00'}
        with patch.object(db,'credit_paid_deposit',AsyncMock(return_value=(12000,0))) as credit,patch.object(payments.commerce,'finish_invoice',AsyncMock()):
            self.assertEqual(await payments.settle_invoice(row,invoice),(12000,0))
            credit.assert_awaited_once()


class PolicyTransactions(unittest.IsolatedAsyncioTestCase):
    async def test_claim_blocks_real_country_before_writing_identity_locks(self):
        cur=NS(execute=AsyncMock())
        with self.assertRaises(ValueError):await imports.claim(cur,'+79991234567',42,'private-session')
        cur.execute.assert_not_awaited()

    async def test_review_release_rechecks_country_and_rolls_back(self):
        cur=MagicMock(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[{'id':1,'status':'review'},None]),fetchall=AsyncMock(return_value=[{'country':'us','number':'+380991234567','price':100}]))
        conn=MagicMock(begin=AsyncMock(),commit=AsyncMock(),rollback=AsyncMock());conn.cursor.return_value.__aenter__.return_value=cur
        pool=MagicMock();pool.acquire.return_value.__aenter__.return_value=conn
        with patch.object(admin_tools,'_get_pool',return_value=pool),self.assertRaises(ValueError):await shop_control.set_review(7,1,False,'Checked')
        conn.rollback.assert_awaited_once();conn.commit.assert_not_awaited()
        self.assertFalse(any('UPDATE accounts' in c.args[0] for c in cur.execute.call_args_list))

    async def test_migration_withdraws_only_restricted_unsold_stock_and_clears_holds(self):
        cur=MagicMock(execute=AsyncMock(),rowcount=1,fetchall=AsyncMock(side_effect=[
            [('ru','Россия'),('other','Украина 🇺🇦'),('kz','Казахстан')],
            [(1,'us','+79991234567',100,'USA'),(2,'us','+15551234567',10001,'USA'),(3,'kz','+77011234567',100,'Казахстан')]]))
        await sales_policy.migrate(cur)
        calls=cur.execute.call_args_list
        self.assertEqual(len([c for c in calls if 'UPDATE categories' in c.args[0]]),2)
        self.assertEqual(len([c for c in calls if 'UPDATE accounts' in c.args[0]]),2)
        query=next(c.args[0] for c in calls if 'SELECT a.id' in c.args[0])
        self.assertIn('NOT EXISTS',query);self.assertIn("a.status='available'",query)
        self.assertFalse(any('DELETE FROM accounts' in c.args[0] for c in calls))


class PublicInfoTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_documents_remain_public_without_telegram_authentication(self):
        from miniapp import public_info
        with patch.object(public_info,'rows',AsyncMock(return_value=[{'slug':'us','name':'US <script>','quantity':1,'minimum':100,'maximum':200}])),patch.object(db,'get_setting',AsyncMock(return_value='https://t.me/fixture_support')):
            response=await self.client.get('/about')
            text=await response.text()
            self.assertEqual(response.status,200)
            self.assertIn(PRIVACY_URL,text);self.assertIn(AGREEMENT_URL,text)
            self.assertIn('mekbuda',text);self.assertIn('100,00–200,00 ₽',text)
            self.assertIn('US &lt;script&gt;',text)
            self.assertIn('https://t.me/fixture_support',text)
            self.assertNotIn('type="email"',text)
        page=await self.client.get('/')
        self.assertEqual(page.status,200)
        text=await page.text()
        self.assertIn('legal-footer',text);self.assertIn(PRIVACY_URL,text);self.assertIn('mekbuda',text)
