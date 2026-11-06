"""SBP moderation path: exact amount, clickable placeholder, no financial side effects."""
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch
from test_payments import config,db
import test_miniapp
from services import payments,platega
from handlers.user import balance
from handlers.admin import sbp as admin_sbp
from database import admin_web


class SBPBoundsTests(unittest.TestCase):
    def test_sbp_one_to_ten_thousand_does_not_cap_other_providers(self):
        for amount in ['1','10000','1,50']:
            self.assertGreaterEqual(payments.parse_amount(amount,'platega'),1)
        for amount in ['.99','10000.01','1.001','NaN','Infinity',True]:
            with self.assertRaises(ValueError):payments.parse_amount(amount,'platega')
        for provider in ['crypto','xrocket','lave']:
            self.assertEqual(payments.parse_amount('1000000',provider),1000000)
            with self.assertRaises(ValueError):payments.parse_amount('9.99',provider)


class StubServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_sbp_is_visible_without_keys_when_stub_enabled(self):
        with patch.object(db,'get_setting',AsyncMock(return_value='1')),patch.multiple(config,PLATEGA_MERCHANT_ID='',PLATEGA_SECRET='',create=True):
            method=next(x for x in await payments.get_methods() if x['id']=='platega')
            self.assertTrue(method['enabled']);self.assertTrue(method['stub'])
            self.assertEqual((method['min'],method['max']),(1,10000))

    async def test_stub_blocks_outbound_requests_and_invoice_or_balance_writes(self):
        with patch.object(db,'get_setting',AsyncMock(return_value='1')),patch.object(platega,'create_invoice',AsyncMock()) as send,patch.object(payments.commerce,'register_invoice',AsyncMock()) as store,patch.object(db,'credit_paid_deposit',AsyncMock()) as credit:
            for amount in ['1','500','10000']:
                with self.assertRaises(payments.PaymentUnavailable):await payments.create_deposit(42,'user','platega',amount)
            send.assert_not_awaited();store.assert_not_awaited();credit.assert_not_awaited()

    async def test_stub_off_uses_existing_live_creation_with_verified_telegram_id(self):
        with patch.object(db,'get_setting',AsyncMock(return_value='0')),patch.multiple(config,PLATEGA_MERCHANT_ID='fixture',PLATEGA_SECRET='fixture',create=True),patch.object(platega,'create_invoice',AsyncMock(return_value={'id':'fixture','pay_url':'https://example.test/pay'})) as send,patch.object(payments.commerce,'register_invoice',AsyncMock()) as store,patch.object(payments,'_health',AsyncMock()):
            result=await payments.create_deposit(42,'not-an-email','platega','1')
            self.assertEqual(result['amount'],'1')
            self.assertEqual(send.call_args.args[-1],42)
            store.assert_awaited_once_with('platega','fixture',42,Decimal(1))


class StubAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_api_ignores_client_attempt_to_disable_placeholder(self):
        with patch.object(platega,'create_invoice',AsyncMock()) as send,patch.object(payments.commerce,'register_invoice',AsyncMock()) as store:
            response=await self.client.post('/api/invoices',headers=self.headers,json={'provider':'platega','amount':'1','platega_stub':False,'user_id':99})
            data=await response.json()
            self.assertEqual((response.status,data['code']),(409,'payment_unavailable'))
            self.assertIn('временно недоступна',data['error'])
            self.assertNotIn('invoice_id',data)
            send.assert_not_awaited();store.assert_not_awaited()

    async def test_customer_cannot_switch_real_payment_mode(self):
        with patch.object(config,'ADMIN_IDS',[7]),patch.object(admin_web,'save_settings',AsyncMock()) as save:
            response=await self.client.post('/api/admin/settings',headers=self.headers,json={'platega_stub':'0','admin_id':7})
            self.assertEqual(response.status,403);save.assert_not_awaited()

    async def test_method_list_includes_keyless_sbp_amount_range(self):
        response=await self.client.get('/api/payment-methods',headers=self.headers)
        self.assertEqual(response.status,200)
        method=next(x for x in (await response.json())['items'] if x['id']=='platega')
        self.assertTrue(method['enabled']);self.assertEqual((method['min'],method['max']),(1,10000))


class StubBotTests(unittest.IsolatedAsyncioTestCase):
    async def test_entering_amount_shows_exact_sum_and_pay_button_without_creating_invoice(self):
        message=NS(text='1',from_user=NS(id=42))
        state=NS(get_data=AsyncMock(return_value={'payment_method':'platega'}),set_state=AsyncMock(),update_data=AsyncMock())
        with patch.object(balance,'answer_screen',AsyncMock()) as screen,patch.object(payments,'create_deposit',AsyncMock()) as create:
            await balance.process_lave_amount(message,state)
            self.assertIn('1.00 ₽',screen.call_args.args[1])
            rows=screen.call_args.kwargs['reply_markup'].inline_keyboard
            self.assertEqual(rows[0][0].text,'Оплатить 1.00 ₽')
            self.assertTrue(rows[0][0].callback_data.startswith('sbp_pay:'))
            self.assertNotIn('Тариф',screen.call_args.args[1])
            create.assert_not_awaited()

    async def test_pay_click_shows_placeholder_and_preserves_quote_for_a_later_retry(self):
        call=NS(data='sbp_pay:nonce',from_user=NS(id=42,username='user'))
        state=NS(get_data=AsyncMock(return_value={'payment_method':'platega','payment_nonce':'nonce','payment_amount':'1.00'}),clear=AsyncMock())
        with patch.object(db,'get_setting',AsyncMock(return_value='1')),patch.object(balance,'edit_message_safe',AsyncMock()) as screen,patch.object(balance,'answer_safe',AsyncMock()) as answer,patch.object(platega,'create_invoice',AsyncMock()) as send:
            await balance.confirm_sbp(call,state)
            self.assertIn('временно недоступна',screen.call_args.args[1]);self.assertIn('1.00 ₽',screen.call_args.args[1])
            self.assertTrue(answer.call_args.kwargs['show_alert'])
            send.assert_not_awaited();state.clear.assert_not_awaited()

    async def test_stale_or_forwarded_button_cannot_start_payment(self):
        call=NS(data='sbp_pay:someone-else',from_user=NS(id=42))
        state=NS(get_data=AsyncMock(return_value={'payment_method':'platega','payment_nonce':'nonce'}))
        with patch.object(balance,'answer_safe',AsyncMock()),patch.object(payments,'create_deposit',AsyncMock()) as create:
            await balance.confirm_sbp(call,state)
            create.assert_not_awaited()

    async def test_only_admin_can_toggle_from_bot(self):
        call=NS(data='sbp_stub:0',from_user=NS(id=99))
        with patch.object(admin_sbp,'is_admin',return_value=False),patch.object(admin_sbp,'answer_safe',AsyncMock()),patch.object(admin_web,'save_settings',AsyncMock()) as save:
            await admin_sbp.toggle(call);save.assert_not_awaited()
