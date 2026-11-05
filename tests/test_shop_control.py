"""Atomic review/sales guards and persisted, isolated RU/EN interface preferences."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import db, config
import test_miniapp
from database import admin_tools, shop_control, commerce, preferences
from miniapp import storage
from utils.i18n import LANGUAGE, tr
from utils.language_middleware import LanguageMiddleware
from utils.maintenance import MaintenanceMiddleware
from aiogram.types import Message


class ControlTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(), fetchall=AsyncMock())
        self.cur.fetchall.return_value = [{'country':'us','number':'+15550001111','price':100,'category_name':'США'}]
        self.conn = MagicMock(begin=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        pool=MagicMock();pool.acquire.return_value.__aenter__.return_value=self.conn
        p=patch.object(admin_tools,'_get_pool',return_value=pool);p.start();self.addCleanup(p.stop)

    async def test_review_cancels_cart_and_reservations_and_keeps_audit_in_same_transaction(self):
        self.cur.fetchone.side_effect=[{'id':1,'status':'available'},None]
        self.assertEqual(await shop_control.set_review(7,1,True,'Login problem'),'review')
        sql=[c.args[0] for c in self.cur.execute.call_args_list]
        self.assertIn('FOR UPDATE',sql[0])
        self.assertTrue(any('DELETE FROM account_reservations' in q for q in sql))
        self.assertTrue(any('DELETE FROM shopping_cart' in q for q in sql))
        update=next(c for c in self.cur.execute.call_args_list if 'UPDATE accounts' in c.args[0])
        self.assertIn('spam_token=NULL',update.args[0]);self.assertEqual(update.args[1][0],'review')
        self.assertFalse(any('UPDATE users' in q for q in sql))
        self.conn.commit.assert_awaited_once()

    async def test_release_is_explicit_and_keeps_previous_reason_in_history(self):
        self.cur.fetchone.side_effect=[{'id':1,'status':'review','review_reason':'Login problem'},None]
        self.assertEqual(await shop_control.set_review(8,1,False,'Problem resolved'),'available')
        audit=next(c for c in self.cur.execute.call_args_list if 'INSERT INTO admin_audit_log' in c.args[0])
        self.assertIn('Login problem',audit.args[1][-1]);self.assertIn('Problem resolved',audit.args[1][-1])

    async def test_sold_account_or_purchase_history_never_returns_to_sale(self):
        for rows in [[{'status':'sold'}],[{'status':'available'}, {'id':12}]]:
            self.cur.reset_mock();self.cur.fetchone.side_effect=rows
            with self.assertRaises(ValueError):await shop_control.set_review(7,1,True,'Problem')
            self.assertFalse(any('UPDATE accounts' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_invalid_review_request_does_not_start_transaction(self):
        for account,enabled,reason in [(True,True,'Reason'),(1,1,'Reason'),(1,True,''),(1,False,'x'*501)]:
            with self.assertRaises(ValueError):await shop_control.set_review(7,account,enabled,reason)
        self.conn.begin.assert_not_awaited()

    async def test_audit_failure_rolls_back_status_and_cancelled_holds(self):
        self.cur.fetchone.side_effect=[{'id':1,'status':'available'},None]
        async def execute(sql,*args):
            if 'INSERT INTO admin_audit_log' in sql:raise OSError('fixture')
        self.cur.execute.side_effect=execute
        with self.assertRaises(OSError):await shop_control.set_review(7,1,True,'Problem')
        self.conn.rollback.assert_awaited_once();self.conn.commit.assert_not_awaited()

    async def test_paused_sales_stop_checkout_before_money_or_promo_changes(self):
        self.cur.fetchone.side_effect=[{'id':1,'price':100,'country':'us'}, {'value':'1'}]
        with self.assertRaises(storage.CheckoutError) as error:await storage.checkout(42,1,Decimal(100))
        self.assertEqual(error.exception.code,'sales_paused')
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))
        self.assertIn('LOCK IN SHARE MODE',self.cur.execute.call_args.args[0])
        self.conn.rollback.assert_awaited_once()

    async def test_paused_sales_stop_cart_reservation(self):
        self.cur.fetchone.side_effect=[{'id':1}, {'value':'1'}]
        with self.assertRaises(storage.CheckoutError):await commerce.add_to_cart(42,1)
        self.assertFalse(any('INSERT' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_legacy_tuple_cursor_obeys_same_switch(self):
        self.cur.fetchone.return_value=('1',)
        with self.assertRaises(storage.CheckoutError):await shop_control.check_sales(self.cur,tuple_cursor=True)
        self.cur.fetchone.return_value=('0',)
        await shop_control.check_sales(self.cur,tuple_cursor=True)


class ControlAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_review_requires_admin_and_ignores_spoofed_actor(self):
        with patch.object(shop_control,'set_review',AsyncMock(return_value='review')) as review:
            res=await self.client.post('/api/admin/stock/1/review',headers=self.headers,json={'enabled':True,'reason':'Issue','admin_id':99})
            self.assertEqual(res.status,403);review.assert_not_awaited()
            with patch.object(config,'ADMIN_IDS',[42]):
                res=await self.client.post('/api/admin/stock/1/review',headers=self.headers,json={'enabled':True,'reason':'Issue','admin_id':99})
            self.assertEqual(res.status,200);review.assert_awaited_once_with(42,1,True,'Issue')

    async def test_sales_pause_keeps_buyer_orders_and_profile_available(self):
        storage.access_settings.return_value={'sales_paused':'1'}
        with patch.object(storage,'orders',AsyncMock(return_value={'items':[],'has_more':False})):
            self.assertEqual((await self.client.get('/api/orders',headers=self.headers)).status,200)
        res=await self.client.get('/api/me',headers=self.headers)
        self.assertTrue((await res.json())['shop_status']['sales_paused'])

    async def test_full_maintenance_has_localized_status_and_language_control(self):
        storage.access_settings.return_value={'maintenance_mode':'1','maintenance_reason':'Custom <reason>','maintenance_eta':'18:00 MSK'}
        db.get_user.return_value={'balance':100,'balance_usdt':0,'language':'en'}
        res=await self.client.get('/api/me',headers=self.headers)
        self.assertEqual(res.status,503);data=await res.json()
        self.assertIn('Maintenance',data['error']);self.assertEqual(data['shop_status']['reason'],'Custom <reason>')
        self.assertEqual(res.headers['Content-Language'],'en')
        self.assertEqual((await self.client.get('/api/status',headers=self.headers)).status,200)
        with patch.object(preferences,'set_language',AsyncMock(return_value='ru')) as save:
            res=await self.client.post('/api/preferences/language',headers=self.headers,json={'language':'ru','user_id':99})
        self.assertEqual(res.status,200);save.assert_awaited_once_with(42,'ru')

    async def test_invalid_language_never_reaches_database_write(self):
        with patch.object(preferences,'create_user',AsyncMock()) as create:
            for value in ['de',[],True,None]:
                res=await self.client.post('/api/preferences/language',headers=self.headers,json={'language':value})
                self.assertEqual(res.status,400)
        create.assert_not_awaited()

    async def test_concurrent_languages_do_not_leak_between_users(self):
        async def profile(user):
            await asyncio.sleep(0)
            return {'balance':100,'balance_usdt':0,'language':'en' if user==42 else 'ru'}
        db.get_user.side_effect=profile
        storage.access_settings.return_value={'maintenance_mode':'1'}
        a,b=await asyncio.gather(self.client.get('/api/me',headers=self.headers),self.client.get('/api/me',headers={'Authorization':'tma '+test_miniapp.signed_data(43)}))
        self.assertIn('Maintenance',(await a.json())['error']);self.assertIn('технические',(await b.json())['error'])
        self.assertEqual(a.headers['Content-Language'],'en');self.assertEqual(b.headers['Content-Language'],'ru')


class LocalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_language_selection_saves_profile_and_renders_new_language(self):
        from handlers.user import language as ui
        call=NS(from_user=NS(id=42),data='language:en')
        state=NS(clear=AsyncMock())
        token=LANGUAGE.set('ru')
        try:
            with patch.object(ui,'set_language',AsyncMock(return_value='en')) as save,patch.object(ui,'edit_message_safe',AsyncMock()) as edit,patch.object(ui,'answer_safe',AsyncMock()):
                await ui.save_language(call,state)
            save.assert_awaited_once_with(42,'en');state.clear.assert_awaited_once()
            self.assertIn('Language saved',edit.call_args.args[1])
            self.assertIn('My profile',str(edit.call_args.kwargs['reply_markup']))
        finally:LANGUAGE.reset(token)

    async def test_recipient_notice_uses_their_language_and_lookup_failure_cannot_block_receipt(self):
        from utils.notification_language import send_translated
        bot=NS(send_message=AsyncMock())
        with patch.object(preferences,'get_language',AsyncMock(return_value='en')):
            await send_translated(bot,42,'⭐ Зачислено {0} ₽.','120.00')
        self.assertIn('Credited 120.00',bot.send_message.call_args.args[1])
        with patch.object(preferences,'get_language',AsyncMock(side_effect=OSError)):
            await send_translated(bot,42,'⭐ Зачислено {0} ₽.','120.00')
        self.assertIn('Зачислено 120.00',bot.send_message.call_args.args[1])

    async def test_dynamic_values_are_not_translated_and_html_is_preserved(self):
        token=LANGUAGE.set('en')
        try:
            result=tr('<b>Мой профиль</b>\n<code>{0}</code>','Мой профиль {0} $& <secret>')
            self.assertEqual(result,'<b>My profile</b>\n<code>Мой профиль {0} $& <secret></code>')
            self.assertEqual(tr('Произвольное название пользователя'),'Произвольное название пользователя')
        finally:LANGUAGE.reset(token)

    async def test_middleware_resolves_persisted_language_and_restores_context_on_error(self):
        async def handler(event,data):
            self.assertEqual(tr('Мой профиль'),'My profile');raise OSError('fixture')
        with patch('utils.language_middleware.get_language',AsyncMock(return_value='en')) as get:
            with self.assertRaises(OSError):await LanguageMiddleware()(handler,NS(from_user=NS(id=42)),{})
        get.assert_awaited_once_with(42);self.assertEqual(LANGUAGE.get(),'ru')

    async def test_payment_receipts_bypass_language_lookup_and_maintenance(self):
        event=MagicMock(spec=Message);event.successful_payment=NS(currency='XTR');event.refunded_payment=None
        handler=AsyncMock()
        with patch('utils.language_middleware.get_language',AsyncMock(side_effect=OSError)) as language,patch('utils.maintenance.is_maintenance',AsyncMock(return_value=True)) as maintenance:
            await LanguageMiddleware()(handler,event,{})
            await MaintenanceMiddleware()(handler,event,{})
        self.assertEqual(handler.await_count,2);language.assert_not_awaited();maintenance.assert_not_awaited()

    async def test_maintenance_escapes_operator_notice_and_has_english_default(self):
        token=LANGUAGE.set('en')
        try:
            self.assertIn('updating the store',shop_control.maintenance_message({}))
            text=shop_control.maintenance_message({'maintenance_reason':'<script>','maintenance_eta':'<b>18:00</b>'})
            self.assertIn('&lt;script&gt;',text);self.assertNotIn('<script>',text)
            self.assertIn('&lt;b&gt;18:00&lt;/b&gt;',text)
        finally:LANGUAGE.reset(token)


if __name__=='__main__':unittest.main()
