"""Regression checks for stale quotes, private data, failed navigation and retries."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace as NS
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import db
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText
from database import bot_store, coupons
from handlers.user import shop, purchases, promo
from handlers.admin import broadcast
from miniapp import storage
from services import payments, telethon_code
from utils import nav, maintenance, throttling
from utils.actions import single_action
import test_miniapp


class SharedCheckoutGuaranteeTests(unittest.IsolatedAsyncioTestCase):
    setUp = test_miniapp.CheckoutTests.setUp
    async def test_changed_warranty_rolls_back_before_any_charge(self):
        self.cur.fetchone.return_value = {'id': 1, 'price': 100, 'country': 'us', 'warranty_hours': 0}
        with self.assertRaisesRegex(storage.CheckoutError, 'гарантии'):
            await storage.checkout(42, 1, Decimal(100), warranty_hours=24)
        self.conn.rollback.assert_awaited_once()
        self.assertEqual(self.cur.execute.await_count, 1)


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call = NS(data='confirm_buy_acc:8:nonce', from_user=NS(id=42, username='buyer'))
        self.quote = dict(id=8, token='nonce', price='100.00', warranty_hours=24, expires=time.time()+60)
        self.state = NS(get_data=AsyncMock(return_value={'purchase_quote': self.quote}), clear=AsyncMock(), update_data=AsyncMock())

    async def test_quote_is_used_by_checkout_and_remaining_balance_comes_from_transaction(self):
        order = {'status':'issued','number':'+123456789','password':'<secret>'}
        with patch.object(shop, 'checkout', AsyncMock(return_value={'id':5,'paid_amount':'100.00','balance':'37.25'})) as checkout, \
             patch.object(shop, 'get_purchase_for_user', AsyncMock(return_value=order)), \
             patch.object(shop, 'edit_message_safe', AsyncMock()) as edit, \
             patch.object(shop, 'answer_safe', AsyncMock()), \
             patch.object(shop, 'after_purchase_menu', AsyncMock()), \
             patch.object(shop, 'ADMIN_IDS', []):
            await shop.confirm_purchase(self.call, self.state)
            checkout.assert_awaited_once_with(42, 8, Decimal('100'), warranty_hours=24)
            self.assertIn('37.25', edit.call_args.args[1])
            self.assertIn('&lt;secret&gt;', edit.call_args.args[1])
            self.state.update_data.assert_awaited_with(purchase_quote=None)

    async def test_expired_or_other_account_quote_never_charges(self):
        with patch.object(shop, 'checkout', AsyncMock()) as checkout, patch.object(shop, 'show_product', AsyncMock()) as preview:
            for change in ({'expires':0}, {'id':9}, {'token':'other'}):
                self.state.get_data.return_value = {'purchase_quote':self.quote | change}
                await shop.confirm_purchase(self.call, self.state)
            checkout.assert_not_awaited()
            self.assertEqual(preview.await_count, 3)

    async def test_price_conflict_requires_new_confirmation(self):
        with patch.object(shop, 'checkout', AsyncMock(side_effect=storage.CheckoutError('Цена изменилась','price_changed'))), \
             patch.object(shop, 'show_product', AsyncMock()) as preview, patch.object(shop, 'answer_safe', AsyncMock()):
            await shop.confirm_purchase(self.call, self.state)
            preview.assert_awaited_once()
            self.state.update_data.assert_not_awaited()

    async def test_completion_during_code_fetch_cannot_reveal_code(self):
        self.call.data='get_code:5'
        issued={'status':'issued','number':'+15555555','data':'session-private'}
        with patch.object(shop, 'get_purchase_for_user', AsyncMock(side_effect=[issued,issued|{'status':'completed'}])), \
             patch.object(telethon_code, 'try_fetch_login_code', AsyncMock(return_value='654321')), \
             patch.object(shop, 'answer_safe', AsyncMock()), patch.object(shop, 'edit_message_safe', AsyncMock()) as edit:
            await shop.deliver_login_code(self.call)
            edit.assert_not_awaited()

    async def test_completion_first_click_only_shows_confirmation(self):
        self.call.data='complete_purchase:5'
        with patch.object(purchases, 'get_purchase_for_user', AsyncMock(return_value={'status':'issued'})), \
             patch.object(purchases, 'edit_message_safe', AsyncMock()) as edit, \
             patch.object(purchases, 'answer_safe', AsyncMock()), \
             patch.object(bot_store, 'complete_order', AsyncMock()) as complete:
            await purchases.complete_purchase(self.call)
            complete.assert_not_awaited()
            self.assertEqual(edit.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data,'complete_confirm:5')

    async def test_large_order_history_is_paged_and_escaped(self):
        self.call.data='orders_page:1'
        rows=[{'id':i,'name':'<title>','country':'us','date':'date','status':'issued'} for i in range(8)]
        with patch.object(bot_store, 'orders', AsyncMock(return_value=(rows,1000,1))) as query, \
             patch.object(purchases, 'edit_message_safe', AsyncMock()) as edit, patch.object(purchases, 'answer_safe', AsyncMock()):
            await purchases.my_purchases(self.call,self.state)
            query.assert_awaited_once_with(42,1)
            self.assertLess(len(edit.call_args.args[1]),4096)
            self.assertIn('&lt;title&gt;',edit.call_args.args[1])
            self.assertLessEqual(len(edit.call_args.kwargs['reply_markup'].inline_keyboard),10)

    async def test_empty_bot_category_has_no_fake_price_and_remains_clickable(self):
        self.call.data='buy'
        rows=[{'slug':'us','name':'США','emoji':'🇺🇸','min_price':None,'count':0}]
        with patch.object(bot_store,'categories',AsyncMock(return_value=(rows,1,0))), \
             patch.object(shop,'edit_message_safe',AsyncMock()) as edit, patch.object(shop,'answer_safe',AsyncMock()):
            await shop.open_shop(self.call,self.state)
            button=edit.call_args.kwargs['reply_markup'].inline_keyboard[0][0]
            self.assertEqual(button.callback_data,'buy_us')
            self.assertIn('Нет в наличии',button.text)
            self.assertNotIn('₽',button.text)

    async def test_invalid_promo_keeps_form_open_and_does_not_credit(self):
        message=NS(from_user=NS(id=42),text='mistake',answer=AsyncMock())
        with patch.object(coupons,'preview',AsyncMock(side_effect=ValueError('Код не найден'))), \
             patch.object(coupons,'redeem_balance',AsyncMock()) as redeem:
            await promo.process_promo(message,self.state)
            self.state.clear.assert_not_awaited()
            redeem.assert_not_awaited()

    async def test_unknown_callback_ids_do_not_reach_database(self):
        with patch.object(shop,'get_purchase_for_user',AsyncMock()) as query, patch.object(shop,'answer_safe',AsyncMock()):
            for value in ('-1','99999999999999999999','NaN','١٢٣'):
                self.call.data='get_code:'+value
                await shop.deliver_login_code(self.call)
            query.assert_not_awaited()


class PaymentRegistryTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_check_rejects_unregistered_owner_before_provider_request(self):
        with patch.object(payments.commerce,'invoice',AsyncMock(return_value=None)) as registry, \
             patch.object(payments.cryptopay,'get_invoice',AsyncMock()) as provider:
            with self.assertRaises(ValueError): await payments.check_invoice(42,'crypto','1')
            registry.assert_awaited_once_with('crypto','1',42)
            provider.assert_not_awaited()

    async def test_paid_identity_mismatch_does_not_credit(self):
        row={'status':'pending','provider':'crypto','invoice_id':'1','user_id':42,'amount_rub':100}
        with patch.object(payments.commerce,'invoice',AsyncMock(return_value=row)), \
             patch.object(payments.cryptopay,'get_invoice',AsyncMock(return_value={'invoice_id':2,'status':'paid','payload':'rub_topup:42:100'})), \
             patch.object(payments.db,'credit_paid_deposit',AsyncMock()) as credit:
            with self.assertRaises(ValueError): await payments.check_invoice(42,'crypto','1')
            credit.assert_not_awaited()

    async def test_already_credited_invoice_does_not_contact_provider(self):
        with patch.object(payments.commerce,'invoice',AsyncMock(return_value={'status':'credited'})), \
             patch.object(payments.cryptopay,'get_invoice',AsyncMock()) as provider:
            self.assertEqual(await payments.check_invoice(42,'crypto','1'), {'status':'credited','credited':None})
            provider.assert_not_awaited()

    def test_amount_parsing_is_exact_and_does_not_silently_round(self):
        self.assertEqual(payments.parse_amount('1 000,50'),Decimal('1000.50'))
        for invalid in ('10.001','NaN','Infinity','0','9.99','1000000.01','1'*500):
            with self.assertRaises(ValueError): payments.parse_amount(invalid)


class RuntimeReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_broadcast_input_only_previews_and_requires_confirmation(self):
        message=NS(from_user=NS(id=7),chat=NS(id=7),text='-',answer=AsyncMock())
        state=NS(get_data=AsyncMock(return_value={'bc_source_chat':7,'bc_source_msg':9}),
                 update_data=AsyncMock(),set_state=AsyncMock())
        bot=NS(copy_message=AsyncMock())
        with patch.object(broadcast,'is_admin',return_value=True), patch.object(broadcast,'recipients',AsyncMock(return_value=(100,100))) as recipients:
            await broadcast.broadcast_preview(message,state,bot)
        bot.copy_message.assert_awaited_once()
        self.assertEqual(bot.copy_message.call_args.kwargs['chat_id'],7)
        recipients.assert_awaited_once_with()
        state.set_state.assert_awaited_once_with(broadcast.BroadcastState.waiting_confirm)

    async def test_old_broadcast_confirmation_cannot_start_sending(self):
        call=NS(from_user=NS(id=7),data='bc_send:stale')
        state=NS(get_data=AsyncMock(return_value={'bc_token':'current'}))
        bot=NS(copy_message=AsyncMock())
        with patch.object(broadcast,'is_admin',return_value=True), patch.object(broadcast,'answer_safe',AsyncMock()), \
             patch.object(broadcast,'recipients',AsyncMock()) as recipients:
            await broadcast.broadcast_run(call,state,bot)
        recipients.assert_not_awaited()
        bot.copy_message.assert_not_awaited()

    async def test_maintenance_check_restores_menu_after_work_finishes(self):
        from aiogram.types import CallbackQuery
        call=MagicMock(spec=CallbackQuery)
        call.from_user=NS(id=42)
        call.data='check_maintenance'
        state=NS(clear=AsyncMock())
        handler=AsyncMock()
        with patch.object(maintenance,'is_maintenance',AsyncMock(return_value=False)), \
             patch.object(nav,'edit_main',AsyncMock()) as menu, patch.object(nav,'answer_safe',AsyncMock()):
            await maintenance.MaintenanceMiddleware()(handler,call,{'state':state})
        menu.assert_awaited_once_with(call)
        state.clear.assert_awaited_once()
        handler.assert_not_awaited()

    async def test_failed_photo_replacement_does_not_delete_previous_message(self):
        message=NS(photo=[1],answer=AsyncMock(side_effect=OSError('offline')),delete=AsyncMock())
        with self.assertRaises(OSError): await nav.edit_message_safe(NS(message=message),'new')
        message.delete.assert_not_awaited()

    async def test_invalid_html_is_not_silently_resent(self):
        failure=TelegramBadRequest(EditMessageText(text='bad'), 'Bad Request: cannot parse entities')
        message=NS(photo=None,edit_text=AsyncMock(side_effect=failure),answer=AsyncMock(),delete=AsyncMock())
        with self.assertRaises(TelegramBadRequest): await nav.edit_message_safe(NS(message=message),'bad')
        message.answer.assert_not_awaited()
        message.delete.assert_not_awaited()

    async def test_action_guard_releases_after_cancellation(self):
        with self.assertRaises(asyncio.CancelledError):
            async with single_action(42,'test') as acquired:
                self.assertTrue(acquired)
                async with single_action(42,'test') as duplicate: self.assertFalse(duplicate)
                raise asyncio.CancelledError
        async with single_action(42,'test') as acquired: self.assertTrue(acquired)

    async def test_throttle_has_bounded_memory_and_ignores_wall_clock(self):
        limiter=throttling.ThrottlingMiddleware(max_entries=3)
        handler=AsyncMock()
        with patch.object(throttling.time,'monotonic',return_value=100):
            for user in range(10): await limiter(handler,NS(from_user=NS(id=user)),{})
            self.assertEqual(len(limiter.last_request),3)
            await limiter(handler,NS(from_user=NS(id=9)),{})
            self.assertEqual(handler.await_count,10)
        with patch.object(throttling.time,'monotonic',return_value=200):
            await limiter(handler,NS(from_user=NS(id=9)),{})
            self.assertEqual(len(limiter.last_request),1)

    def test_code_extraction_does_not_log_code_or_message_body(self):
        with self.assertLogs(telethon_code.logger,level='INFO') as logs:
            self.assertEqual(telethon_code._extract_code('Secret text: 654321'),'654321')
        self.assertNotIn('654321',''.join(logs.output))
        self.assertNotIn('Secret text',''.join(logs.output))

    def test_broadcast_button_validation_is_strict(self):
        self.assertIsNone(broadcast._markup_from_spec('-'))
        self.assertEqual(broadcast._markup_from_spec('Shop|https://example.com').inline_keyboard[0][0].text,'Shop')
        for spec in ('label|httpsbroken','label|javascript:alert(1)','label|https://user:password@example.com','not-a-spec'):
            with self.assertRaises(ValueError): broadcast._markup_from_spec(spec)
