"""Offline tests for user consent, notification retries and order ownership."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

# Reuse the existing isolated config setup; never connect to configured services.
from test_payments import db
from database import restock as storage
from services import restock as delivery
from handlers.user import restock as ui
from handlers import tickets as purchases
from keyboards import user_kb
from utils.support import purchase_support_url
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage


class SupportLinkTests(unittest.TestCase):
    def test_order_reference_is_prefilled_for_supported_contacts(self):
        for contact in ('@help_shop', 'help_shop', 'https://t.me/help_shop', 't.me/help_shop'):
            with self.subTest(contact=contact):
                result = urlsplit(purchase_support_url(contact, 52))
                self.assertEqual(result.netloc, 't.me')
                self.assertEqual(result.path, '/help_shop')
                self.assertIn('#52', parse_qs(result.query)['text'][0])

    def test_invalid_contacts_do_not_produce_links(self):
        for contact in ('', 'Не задана', 'https://evil.example/help_shop', 't.me/+invite', 'name?x=y'):
            with self.subTest(contact=contact):
                self.assertIsNone(purchase_support_url(contact, 52))


class NotificationDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.item = {'user_id': 42, 'category_slug': 'cat', 'token': 'generation', 'name': '<Category>'}
        self.bot = SimpleNamespace(send_message=AsyncMock())
        self.pending = patch.object(delivery, 'pending_notifications', AsyncMock(return_value=[self.item]))
        self.claim = patch.object(delivery, 'claim_notification', AsyncMock(return_value=True))
        self.finish = patch.object(delivery, 'finish_notification', AsyncMock())
        self.sleep = patch.object(delivery.asyncio, 'sleep', AsyncMock())
        self.pending.start()
        self.claim_mock = self.claim.start()
        self.finish_mock = self.finish.start()
        self.sleep.start()
        for patcher in (self.pending, self.claim, self.finish, self.sleep):
            self.addCleanup(patcher.stop)

    async def test_success_escapes_category_and_finishes_only_sent_generation(self):
        await delivery.send_pending_notifications(self.bot)
        self.assertIn('&lt;Category&gt;', self.bot.send_message.call_args.args[1])
        self.finish_mock.assert_awaited_once_with('generation')

    async def test_failure_preserves_subscription_for_retry(self):
        self.bot.send_message.side_effect = OSError('offline')
        with self.assertLogs(delivery.logger, level='ERROR'):
            await delivery.send_pending_notifications(self.bot)
        self.finish_mock.assert_not_awaited()

    async def test_blocked_bot_removes_subscription(self):
        self.bot.send_message.side_effect = TelegramForbiddenError(
            method=SendMessage(chat_id=42, text='test'), message='blocked')
        await delivery.send_pending_notifications(self.bot)
        self.finish_mock.assert_awaited_once_with('generation')

    async def test_rate_limit_preserves_subscription(self):
        self.bot.send_message.side_effect = TelegramRetryAfter(
            method=SendMessage(chat_id=42, text='test'), message='retry', retry_after=5)
        await delivery.send_pending_notifications(self.bot)
        self.finish_mock.assert_not_awaited()

    async def test_cancelled_or_claimed_subscription_is_not_sent(self):
        self.claim_mock.return_value = False
        await delivery.send_pending_notifications(self.bot)
        self.bot.send_message.assert_not_awaited()

    async def test_cancellation_is_not_swallowed(self):
        self.bot.send_message.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await delivery.send_pending_notifications(self.bot)
        self.finish_mock.assert_not_awaited()


class UserFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call = SimpleNamespace(data='purchase_help:52', from_user=SimpleNamespace(id=42))

    async def test_other_users_order_cannot_open_support(self):
        with patch.object(purchases, 'get_purchase_for_user', AsyncMock(return_value=None)) as get, \
             patch.object(purchases, 'edit_message_safe', AsyncMock()) as edit, \
             patch.object(purchases, 'answer_safe', AsyncMock()) as answer:
            await purchases.purchase_help(self.call, SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock()))
            get.assert_awaited_once_with(52, 42)
            edit.assert_not_awaited()
            self.assertIn('не найдена', answer.call_args.args[1])

    async def test_support_is_available_for_completed_order(self):
        state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock())
        with patch.object(purchases, 'get_purchase_for_user', AsyncMock(return_value={'id': 52, 'status': 'completed'})), \
             patch.object(purchases.store, 'ticket_for_order', AsyncMock(return_value=None)), \
             patch.object(purchases, 'edit_message_safe', AsyncMock()) as edit, \
             patch.object(purchases, 'answer_safe', AsyncMock()):
            await purchases.purchase_help(self.call, state)
            self.assertIn('#52', edit.call_args.args[1])
            state.update_data.assert_awaited_once_with(ticket_order_id=52)
            state.set_state.assert_awaited_once_with(purchases.TicketInput.new)

    async def test_empty_shop_still_offers_subscriptions(self):
        with patch.object(user_kb, 'get_available_categories', AsyncMock(return_value=[])):
            keyboard, has_stock = await user_kb.shop_menu()
            self.assertFalse(has_stock)
            self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, 'stock_menu')

    async def test_long_unicode_slug_fits_callback_limit(self):
        slug = 'категория' * 8
        self.assertLessEqual(len(f'stock_on:{ui.category_key(slug)}:0'.encode()), 64)

    async def test_subscribe_is_explicit_and_bound_to_current_user(self):
        category = {'slug': 'cat', 'name': 'Category', 'is_active': 1}
        self.call.data = f'stock_on:{ui.category_key("cat")}:0'
        with patch.object(ui, 'get_all_categories', AsyncMock(return_value=[category])), \
             patch.object(ui, 'subscribe', AsyncMock()) as subscribe, \
             patch.object(ui, 'render_subscriptions', AsyncMock()), \
             patch.object(ui, 'answer_safe', AsyncMock()):
            await ui.change_subscription(self.call)
            subscribe.assert_awaited_once_with(42, 'cat')

    async def test_inactive_category_cannot_receive_new_subscriptions(self):
        self.call.data = f'stock_on:{ui.category_key("cat")}:0'
        with patch.object(ui, 'get_all_categories', AsyncMock(return_value=[{'slug': 'cat', 'is_active': 0}])), \
             patch.object(ui, 'subscribe', AsyncMock()) as subscribe, \
             patch.object(ui, 'answer_safe', AsyncMock()):
            await ui.change_subscription(self.call)
            subscribe.assert_not_awaited()

    async def test_inactive_category_can_be_unsubscribed(self):
        self.call.data = f'stock_off:{ui.category_key("cat")}:0'
        with patch.object(ui, 'get_all_categories', AsyncMock(return_value=[{'slug': 'cat', 'is_active': 0}])), \
             patch.object(ui, 'unsubscribe', AsyncMock()) as unsubscribe, \
             patch.object(ui, 'render_subscriptions', AsyncMock()), \
             patch.object(ui, 'answer_safe', AsyncMock()):
            await ui.change_subscription(self.call)
            unsubscribe.assert_awaited_once_with(42, 'cat')
