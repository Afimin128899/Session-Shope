"""Warranty boundaries, signed-owner APIs, review privacy and monitor delivery."""
import unittest
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock,patch
import test_miniapp
from test_payments import db
from database import quality,coupons,activity,admin_tools,tickets
from miniapp import server
from deploy import healthcheck,setup_monitor
from handlers import quality as handlers


class WarrantyTests(unittest.TestCase):
    def test_no_retroactive_warranty_or_refunded_access(self):
        self.assertEqual(quality.warranty({})['label'],'Срок не сохранён')
        self.assertFalse(quality.warranty({'warranty_hours':0})['active'])
        future=datetime.now(timezone.utc).replace(tzinfo=None)+timedelta(hours=24)
        self.assertTrue(quality.warranty({'warranty_hours':24,'warranty_until':future})['active'])
        self.assertFalse(quality.warranty({'warranty_hours':24,'warranty_until':future,'status':'refunded'})['active'])
        self.assertFalse(quality.warranty({'warranty_hours':24,'warranty_until':future-timedelta(days=2)})['active'])

    def test_no_invented_age_or_premium_and_no_password_projection(self):
        self.assertIsNone(quality.characteristics({})['registration_date'])
        self.assertIsNone(quality.characteristics({})['is_premium'])
        data=quality.characteristics({'password':'SECRET'})
        self.assertNotIn('SECRET',str(data))

    def test_monitor_timer_runs_independently_from_bot(self):
        from pathlib import Path
        units=setup_monitor.units(Path('/opt/app'),Path('/opt/app/.venv/bin/python'),'shop.service')
        self.assertIn('OnUnitActiveSec=2min',units['session-shope-monitor.timer'])
        self.assertIn('--service "shop.service"',units['session-shope-monitor.service'])
        self.assertNotIn('Requires=shop.service',units['session-shope-monitor.service'])


class QualityAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_new_routes_require_telegram_signature(self):
        for path in ['/api/activity','/api/reviews','/api/promo/preview','/api/promo/redeem','/api/orders/1/warranty-claim']:
            method=self.client.get if path in {'/api/activity','/api/reviews'} else self.client.post
            self.assertEqual((await method(path)).status,401)

    async def test_history_never_accepts_another_user(self):
        with patch.object(activity,'history',AsyncMock(return_value={'items':[]})) as get:
            res=await self.client.get('/api/activity?user_id=999&page=2',headers=self.headers)
            self.assertEqual(res.status,200);get.assert_awaited_once_with(42,2)

    async def test_reviews_use_signed_owner(self):
        with patch.object(quality,'save_review',AsyncMock()) as save:
            res=await self.client.post('/api/reviews',headers=self.headers,json={'purchase_id':1,'user_id':99,'rating':5,'body':'Good'})
            self.assertEqual(res.status,201);save.assert_awaited_once_with(42,1,5,'Good')

    async def test_warranty_claim_checks_ownership_in_storage(self):
        with patch.object(tickets,'create_ticket',AsyncMock(side_effect=ValueError('Гарантия истекла'))) as save:
            res=await self.client.post('/api/orders/1/warranty-claim',headers=self.headers,json={'user_id':99,'body':'Problem'})
            self.assertEqual(res.status,409);save.assert_awaited_once_with(42,1,'Problem',warranty=True)

    async def test_promo_redeem_uses_signed_owner(self):
        with patch.object(coupons,'redeem_balance',AsyncMock(return_value=Decimal(100))) as redeem:
            res=await self.client.post('/api/promo/redeem',headers=self.headers,json={'code':'TEST','user_id':99})
            self.assertEqual(res.status,200);redeem.assert_awaited_once_with(42,'TEST')

    async def test_invalid_discount_quote_cannot_reach_checkout(self):
        with patch.object(server.storage,'checkout_cart',AsyncMock()) as buy:
            for total in ['NaN','Infinity','-1',100,None]:
                res=await self.client.post('/api/cart/checkout',headers=self.headers,json={'items':[{'account_id':1,'price':'100.00'}],'promo_code':'TEST','expected_total':total})
                self.assertEqual(res.status,400)
            buy.assert_not_awaited()


class QualityTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur=MagicMock(execute=AsyncMock(),fetchone=AsyncMock(),fetchall=AsyncMock())
        self.conn=MagicMock(begin=AsyncMock(),commit=AsyncMock(),rollback=AsyncMock())
        self.conn.cursor.return_value.__aenter__.return_value=self.cur
        pool=MagicMock();pool.acquire.return_value.__aenter__.return_value=self.conn
        p=patch.object(admin_tools,'_get_pool',return_value=pool);p.start();self.addCleanup(p.stop)

    async def test_review_of_another_buyer_is_rejected(self):
        self.cur.fetchone.return_value=None
        with self.assertRaisesRegex(ValueError,'Покупка'): await quality.save_review(42,1,5,'Good')
        self.conn.rollback.assert_awaited_once();self.conn.commit.assert_not_awaited()
        self.assertIn('user_id=%s',self.cur.execute.call_args.args[0])

    async def test_review_rejects_password_and_phone(self):
        self.cur.fetchone.return_value={'id':1,'status':'issued','number':'+15551234567','password':'SECRET'}
        for body in ['password SECRET','phone +1 555 123 45 67']:
            with self.assertRaisesRegex(ValueError,'Не публикуйте'): await quality.save_review(42,1,5,body)
        self.assertFalse(any('INSERT' in call.args[0] for call in self.cur.execute.call_args_list))

    async def test_expired_claim_rolls_back_before_opening_ticket(self):
        self.cur.fetchone.return_value={'id':1,'status':'issued','warranty_active':0}
        with self.assertRaisesRegex(ValueError,'Гарантия'): await tickets.create_ticket(42,1,'Problem',warranty=True)
        self.conn.rollback.assert_awaited_once()
        self.assertFalse(any('INSERT' in call.args[0] for call in self.cur.execute.call_args_list))

    async def test_discount_code_cannot_credit_balance(self):
        self.cur.fetchone.side_effect=[{'code':'TEST','value':10,'uses':0,'max_uses':10,'kind':'discount'},None]
        with self.assertRaisesRegex(ValueError,'скидку'): await coupons.redeem_balance(42,'TEST')
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_bad_rating_never_starts_transaction(self):
        for rating in [0,6,True,'5']:
            with self.assertRaises(ValueError): await quality.save_review(42,1,rating,'text')
        self.conn.begin.assert_not_awaited()

    async def test_non_admin_cannot_edit_characteristics_or_discounts(self):
        call=SimpleNamespace(from_user=SimpleNamespace(id=999),data='quality_features:1',answer=AsyncMock())
        state=AsyncMock()
        with patch.object(handlers,'ADMIN_IDS',[1]),patch.object(handlers.db,'get_account',AsyncMock()) as get:
            await handlers.begin_features(call,state);await handlers.begin_discount(call,state)
            get.assert_not_awaited();state.set_state.assert_not_awaited()


class MonitorTests(unittest.IsolatedAsyncioTestCase):
    async def test_alert_cooldown_and_recovery(self):
        settings={'BOT_TOKEN':'test-only','ADMIN_IDS':'42'};state={}
        with patch.object(healthcheck,'notify',AsyncMock(return_value=True)) as send:
            await healthcheck.deliver(None,settings,{'bot':'Stopped'},state,10000)
            await healthcheck.deliver(None,settings,{'bot':'Stopped'},state,10001)
            self.assertEqual(send.await_count,1)
            await healthcheck.deliver(None,settings,{'bot':'Stopped'},state,13601)
            self.assertEqual(send.await_count,2)
            await healthcheck.deliver(None,settings,{},state,13602)
            self.assertEqual(send.await_count,3);self.assertEqual(state,{'42':{}})

    async def test_delivery_failure_is_retried(self):
        state={}
        with patch.object(healthcheck,'notify',AsyncMock(side_effect=[False,True])) as send:
            for now in [10000,10001]: await healthcheck.deliver(None,{'BOT_TOKEN':'test','ADMIN_IDS':'42'},{'bot':'Stopped'},state,now)
            self.assertEqual(send.await_count,2);self.assertEqual(state['42']['bot'],10001)

    async def test_collector_reports_failures_without_exposing_database_text(self):
        from pathlib import Path
        from collections import namedtuple
        response=MagicMock(status=200,json=AsyncMock(return_value={'status':'ok'}))
        session=MagicMock();session.get.return_value.__aenter__.return_value=response
        cur=MagicMock(execute=AsyncMock(),fetchall=AsyncMock(return_value=[('payments:crypto',),('UNTRUSTED_SECRET',)]))
        connection=MagicMock();connection.cursor.return_value.__aenter__.return_value=cur
        def state(name):
            return {'LoadState':'loaded','ActiveState':'failed' if name=='shop.service' else 'active','Result':'exit-code' if name=='session-shope-backup.service' else 'success'}
        with patch.object(healthcheck,'unit',side_effect=state),patch.object(healthcheck.aiomysql,'connect',AsyncMock(return_value=connection)),patch.object(healthcheck.shutil,'disk_usage',return_value=SimpleNamespace(free=2*1024**3)):
            result=await healthcheck.collect(Path('/tmp'),'shop.service',session,{'DB_USER':'test','DB_NAME':'fixture'})
        self.assertIn('bot',result);self.assertIn('session-shope-backup.service',result)
        self.assertIn('payments:crypto',result);self.assertNotIn('UNTRUSTED_SECRET',str(result))

    async def test_database_failure_alert_does_not_include_exception(self):
        from pathlib import Path
        session=MagicMock();session.get.return_value.__aenter__.side_effect=OSError('INTERNAL_SECRET')
        with patch.object(healthcheck,'unit',return_value={}),patch.object(healthcheck.aiomysql,'connect',AsyncMock(side_effect=RuntimeError('INTERNAL_SECRET'))):
            result=await healthcheck.collect(Path('/tmp'),'shop.service',session,{'DB_USER':'test','DB_NAME':'fixture'})
        self.assertIn('database',result);self.assertIn('miniapp',result);self.assertNotIn('INTERNAL_SECRET',str(result))

    async def test_long_coupon_name_cannot_break_telegram_callbacks(self):
        for name in ['A'*41,'Я'*21]:
            with self.assertRaises(ValueError): await coupons.create_discount(1,name,10,10)

    async def test_review_in_bot_escapes_worst_case_public_text(self):
        data={'average':5,'count':1,'items':[{'rating':5,'body':'&'*500}],'has_more':False}
        call=SimpleNamespace(data='quality_reviews:0',answer=AsyncMock())
        with patch.object(quality,'reviews',AsyncMock(return_value=data)) as get,patch('utils.nav.edit_message_safe',AsyncMock()) as edit:
            await handlers.show_reviews(call)
        get.assert_awaited_once_with(0,per_page=1)
        self.assertLess(len(edit.call_args.args[1]),4096)
        self.assertIn('&amp;',edit.call_args.args[1])
