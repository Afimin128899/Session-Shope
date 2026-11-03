"""Isolation checks for administrator training data and working financial routes."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch,MagicMock
from test_payments import config,db
import test_miniapp
from services.demo import DemoStore,STORE
from miniapp import server,storage
from handlers.admin import demo as bot_demo
from handlers.user import stars
from utils.demo_guard import DemoGuard
from aiogram.types import CallbackQuery,Message


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store=DemoStore();self.view=self.store.enter(42)
    def action(self,action,**fields):
        return self.store.action(42,{'action':action,'generation':self.view['generation'],**fields})
    def test_purchase_coupon_and_refund_only_change_training_balance(self):
        self.action('add',id=1)
        result=self.action('checkout',promo='DEMO10')
        self.assertEqual(result['balance'],'910.00')
        self.assertEqual(result['orders'][0]['paid'],'90.00')
        self.assertEqual(self.action('refund',id=1)['balance'],'1000.00')
        self.assertEqual(self.action('refund',id=1)['balance'],'1000.00')
        self.assertEqual(self.store.enter(43)['balance'],'1000.00')
        with self.assertRaises(ValueError):self.store.action(43,{'action':'refund','generation':self.store.view(43)['generation'],'id':1})
    def test_payment_and_reward_are_idempotent(self):
        result=self.action('invoice',provider='stars',stars=100)
        identity=result['invoices'][-1]['id']
        self.assertEqual(self.action('pay',invoice_id=identity)['balance'],'1120.00')
        self.assertEqual(self.action('pay',invoice_id=identity)['balance'],'1120.00')
        with patch('services.demo.secrets.randbelow',return_value=4):
            self.assertEqual(self.action('reward')['balance'],'1125.00')
        with self.assertRaises(ValueError):self.action('reward')
    def test_reset_rejects_stale_callbacks_and_leaves_other_admin_untouched(self):
        other=self.store.enter(43)
        self.view=self.action('reset')
        self.assertNotEqual(other['generation'],self.view['generation'])
        self.assertEqual(other,self.store.view(43))
        with self.assertRaises(ValueError):self.store.action(42,{'action':'buy','generation':'old','id':1})
    def test_unavailable_or_insufficient_purchase_does_not_mutate_orders(self):
        self.action('buy',id=1)
        with self.assertRaises(ValueError):self.action('buy',id=1)
        self.assertEqual(len(self.store.view(42)['orders']),1)
        self.action('reset')
        self.view=self.store.view(42)
        for identity in (1,2,3,4,5,6):self.action('add',id=identity)
        with self.assertRaises(ValueError):self.action('checkout')
        self.assertEqual(self.store.view(42)['orders'],[])
    def test_unknown_action_and_fractional_stars_are_rejected(self):
        for body in ({'action':[]},{'action':'invoice','provider':'stars','stars':1.5},{'action':'invoice','provider':'evil','amount':'100'}):
            with self.assertRaises(ValueError):self.store.action(42,{'generation':self.view['generation'],**body})


class DemoAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        STORE.states.clear();await test_miniapp.MiniAppAPITests.asyncSetUp(self)
    async def asyncTearDown(self):
        STORE.states.clear();await test_miniapp.MiniAppAPITests.asyncTearDown(self)
    async def test_customer_cannot_enter_demo(self):
        with patch.object(config,'ADMIN_IDS',[7]):
            response=await self.client.get('/api/demo/state',headers=self.headers)
            self.assertEqual(response.status,403)
        self.assertFalse(STORE.active(42))
    async def test_demo_does_not_touch_production_db_or_checkout(self):
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(storage,'access_settings',AsyncMock(side_effect=AssertionError('Working DB touched'))),patch.object(db,'create_user',AsyncMock(side_effect=AssertionError('Working user touched'))):
            result=await (await self.client.get('/api/demo/state',headers=self.headers)).json()
            self.assertEqual(result['balance'],'1000.00')
            response=await self.client.post('/api/demo/action',headers=self.headers,json={'user_id':99,'generation':result['generation'],'action':'buy','id':1})
            self.assertEqual(response.status,200)
            self.assertEqual((await response.json())['balance'],'900.00')
        self.assertEqual(STORE.view(99)['orders'],[])
    async def test_real_mutations_are_blocked_until_explicit_exit(self):
        with patch.object(config,'ADMIN_IDS',[42]):
            await self.client.get('/api/demo/state',headers=self.headers)
            with patch.object(storage,'checkout',AsyncMock()) as checkout:
                response=await self.client.post('/api/purchase',headers=self.headers,json={'account_id':1,'price':'100'})
                self.assertEqual(response.status,409);checkout.assert_not_awaited()
            await self.client.post('/api/demo/exit',headers=self.headers,json={})
            self.assertFalse(STORE.active(42))
    async def test_body_cannot_reset_another_admin(self):
        other=STORE.enter(43)
        with patch.object(config,'ADMIN_IDS',[42,43]):
            me=await (await self.client.get('/api/demo/state',headers=self.headers)).json()
            await self.client.post('/api/demo/action',headers=self.headers,json={'user_id':43,'action':'reset','generation':me['generation']})
        self.assertEqual(STORE.view(43),other)


class BotDemoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):STORE.states.clear()
    def tearDown(self):STORE.states.clear()
    async def test_working_callback_is_blocked_during_training(self):
        STORE.enter(42)
        event=MagicMock(spec=CallbackQuery);event.from_user=NS(id=42);event.data='confirm_buy_acc:1';event.answer=AsyncMock()
        handler=AsyncMock()
        with patch.object(config,'ADMIN_IDS',[42]):await DemoGuard()(handler,event,{})
        handler.assert_not_awaited();event.answer.assert_awaited_once()
    async def test_real_payment_receipt_still_passes(self):
        STORE.enter(42)
        event=MagicMock(spec=Message);event.from_user=NS(id=42);event.successful_payment=NS(currency='XTR');event.refunded_payment=None
        handler=AsyncMock()
        await DemoGuard()(handler,event,{})
        handler.assert_awaited_once()
    async def test_native_real_invoice_precheckout_is_denied(self):
        STORE.enter(42)
        query=NS(from_user=NS(id=42),answer=AsyncMock())
        with patch.object(stars.ledger,'check_precheckout',AsyncMock()) as check:await stars.pre_checkout(query)
        check.assert_not_awaited();self.assertFalse(query.answer.call_args.kwargs['ok'])
    async def test_bot_training_screen_and_exit_have_valid_keyboards(self):
        call=NS(from_user=NS(id=42),data='demo:open')
        state=NS(clear=AsyncMock())
        with patch.object(bot_demo,'ADMIN_IDS',[42]),patch.object(bot_demo,'edit_message_safe',AsyncMock()) as edit,patch.object(bot_demo,'answer_safe',AsyncMock()),patch.object(bot_demo,'miniapp_url',return_value=None):
            await bot_demo.demo(call,state)
            self.assertIn('ТЕСТОВЫЙ',edit.call_args.args[1])
            call.data='demo:exit';await bot_demo.demo(call,state)
            self.assertFalse(STORE.active(42))
