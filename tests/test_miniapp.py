"""Telegram signature, API ownership, input validation and shared checkout tests."""
import hashlib
import hmac
import json
import time
import unittest
from decimal import Decimal
from types import SimpleNamespace
from urllib.parse import urlencode
from unittest.mock import AsyncMock, MagicMock, patch

from aiohttp.test_utils import TestClient, TestServer
from test_payments import db
from miniapp.auth import validate_init_data, AuthError
from miniapp import server, storage
from database import admin_tools

TEST_TOKEN = '123456:local-test-token-not-for-production'


def signed_data(user_id=42, timestamp=None, **extra):
    values = {'auth_date': str(int(time.time()) if timestamp is None else timestamp),
              'query_id': 'test-query', 'user': json.dumps({'id': user_id, 'first_name': 'Alex', 'username': 'alex_test'})} | extra
    key = hmac.new(b'WebAppData', TEST_TOKEN.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(key, '\n'.join(f'{k}={v}' for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramAuthTests(unittest.TestCase):
    def test_valid_signed_user(self):
        self.assertEqual(validate_init_data(signed_data(), TEST_TOKEN)['id'], 42)

    def test_changed_user_id_fails(self):
        data = signed_data().replace('42', '43')
        with self.assertRaises(AuthError): validate_init_data(data, TEST_TOKEN)

    def test_wrong_bot_and_expired_or_future_sessions_fail(self):
        for token, timestamp in [('wrong', int(time.time())), (TEST_TOKEN, int(time.time()) - 3601), (TEST_TOKEN, int(time.time()) + 90)]:
            with self.subTest(token=token), self.assertRaises(AuthError):
                validate_init_data(signed_data(timestamp=timestamp), token)

    def test_duplicate_fields_and_non_integer_id_fail(self):
        for raw in [signed_data() + '&user=anything', signed_data(user_id=True), signed_data(user_id='42')]:
            with self.assertRaises(AuthError): validate_init_data(raw, TEST_TOKEN)

    def test_unsigned_and_oversized_data_fail(self):
        for raw in ['', 'user=42', 'x' * 20000]:
            with self.assertRaises(AuthError): validate_init_data(raw, TEST_TOKEN)


class MiniAppAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.patchers = [
            patch.object(storage, 'access_settings', AsyncMock(return_value={})),
            patch.object(db, 'create_user', AsyncMock()),
            patch.object(server.welcome, 'received', AsyncMock(return_value=Decimal(0))),
            patch.object(db, 'get_setting', AsyncMock(return_value='1')),
            patch.object(server.quality, 'my_review', AsyncMock(return_value=None)),
            patch.object(db, 'get_user', AsyncMock(return_value={'balance': 500, 'balance_usdt': 0})),
        ]
        for p in self.patchers: p.start()
        self.bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status='left')))
        self.client = TestClient(TestServer(server.create_app(token=TEST_TOKEN, bot=self.bot)))
        await self.client.start_server()
        self.headers = {'Authorization': 'tma ' + signed_data()}

    async def asyncTearDown(self):
        await self.client.close()
        for p in reversed(self.patchers): p.stop()

    async def test_static_shell_and_health_are_public_but_api_requires_auth(self):
        for path in ['/', '/assets/style.css', '/assets/app.js', '/api/health']:
            self.assertEqual((await self.client.get(path)).status, 200)
        for path in ['/api/me', '/api/catalog', '/api/orders', '/api/orders/1', '/api/payment-history']:
            self.assertEqual((await self.client.get(path)).status, 401)

    async def test_topup_history_uses_verified_owner_and_bounded_cursor(self):
        cur = MagicMock(execute=AsyncMock(), fetchall=AsyncMock(return_value=[
            {'id': i, 'amount': Decimal('120'), 'currency': 'RUB', 'method': 'stars_pay', 'created_at': '2026-11-10 10:00:00'}
            for i in range(49, 23, -1)
        ]))
        conn = MagicMock()
        conn.cursor.return_value.__aenter__.return_value = cur
        pool = MagicMock()
        pool.acquire.return_value.__aenter__.return_value = conn
        with patch.object(db, '_get_pool', return_value=pool):
            result = await self.client.get('/api/payment-history?before=50&user_id=99', headers=self.headers)
        self.assertEqual(result.status, 200)
        data = await result.json()
        self.assertEqual(len(data['items']), 25)
        self.assertTrue(data['has_more'])
        query, args = cur.execute.call_args.args
        self.assertEqual(args, (42, 50))
        self.assertIn('WHERE user_id=%s', query)
        self.assertIn('AND id<%s', query)
        self.assertIn('amount>0', query)
        self.assertIn("'stars_pay'", query)
        self.assertNotIn('reference', query)
        self.assertTrue(query.endswith('ORDER BY id DESC LIMIT 26'))
        self.assertEqual(result.headers['Cache-Control'], 'no-store')

    async def test_topup_history_rejects_invalid_cursor_before_database_access(self):
        with patch.object(db, '_get_pool') as pool:
            for cursor in ['', '-1', '1.5', '١', '1 OR 1=1', '10000000000']:
                with self.subTest(cursor=cursor):
                    result = await self.client.get('/api/payment-history', params={'before': cursor}, headers=self.headers)
                    self.assertEqual(result.status, 400)
            pool.assert_not_called()

    async def test_me_uses_verified_telegram_identity(self):
        res = await self.client.get('/api/me?user_id=99', headers=self.headers)
        self.assertEqual(res.status, 200)
        self.assertEqual((await res.json())['user']['id'], 42)
        db.get_user.assert_awaited_with(42)
        self.assertEqual(res.headers['Cache-Control'], 'no-store')
        self.assertIn('script-src', res.headers['Content-Security-Policy'])

    async def test_invoice_check_requires_authentication_and_owner(self):
        path = '/api/invoices/crypto/fixture/check'
        self.assertEqual((await self.client.post(path, json={})).status, 401)
        with patch.object(server.commerce, 'invoice', AsyncMock(return_value=None)) as invoice, patch.object(server.payments, 'check_invoice', AsyncMock()) as check:
            result = await self.client.post(path, headers=self.headers, json={'user_id': 99})
            self.assertEqual(result.status, 404)
            invoice.assert_awaited_once_with('crypto', 'fixture', 42)
            check.assert_not_awaited()

    async def test_wallet_is_authenticated_and_owner_scoped(self):
        from miniapp import wallet
        from database import activity
        for path in ['/api/wallet/summary', '/api/wallet/transactions']:
            self.assertEqual((await self.client.get(path)).status, 401)
        with patch.object(wallet, 'summary', AsyncMock(return_value={'deposited':'50','spent':'10'})) as summary, patch.object(activity, 'history', AsyncMock(return_value={'items':[], 'has_more':False})) as history:
            self.assertEqual((await self.client.get('/api/wallet/summary?user_id=99', headers=self.headers)).status, 200)
            self.assertEqual((await self.client.get('/api/wallet/transactions?user_id=99&page=1', headers=self.headers)).status, 200)
            summary.assert_awaited_once_with(42)
            history.assert_awaited_once_with(42, 1)

    async def test_purchase_cannot_choose_another_buyer_or_unchecked_price(self):
        with patch.object(storage, 'checkout', AsyncMock(return_value={'id': 5})) as checkout:
            result = await self.client.post('/api/purchase', headers=self.headers,
                                           json={'account_id': 1, 'price': '100.00', 'user_id': 99})
            self.assertEqual(result.status, 201)
            checkout.assert_awaited_once_with(42, 1, Decimal('100.00'))

    async def test_invalid_purchase_input_never_reaches_checkout(self):
        with patch.object(storage, 'checkout', AsyncMock()) as checkout:
            for data in [{'account_id': True, 'price': '100'}, {'account_id': 1, 'price': 'NaN'},
                         {'account_id': 1, 'price': '-1'}, {'account_id': 1, 'price': 100},
                         {'account_id': 1, 'price': '1.001'}, []]:
                res = await self.client.post('/api/purchase', headers=self.headers, json=data)
                self.assertEqual(res.status, 400)
            checkout.assert_not_awaited()

    async def test_other_users_order_is_not_exposed(self):
        with patch.object(db, 'get_purchase_for_user', AsyncMock(return_value=None)) as get:
            result = await self.client.get('/api/orders/5', headers=self.headers)
            self.assertEqual(result.status, 404)
            get.assert_awaited_once_with(5, 42)

    async def test_order_details_never_include_session_string(self):
        row = {'id': 5, 'number': 'test-number', 'password': 'test-password', 'data': 'NEVER_EXPOSE_THIS'}
        with patch.object(db, 'get_purchase_for_user', AsyncMock(return_value=row)):
            result = await self.client.get('/api/orders/5', headers=self.headers)
            self.assertEqual(result.status,200)
            data = await result.json()
            self.assertNotIn('data', data)
            self.assertNotIn('NEVER_EXPOSE_THIS', str(data))

    async def test_maintenance_and_subscription_cannot_be_bypassed(self):
        for settings, expected in [({'maintenance_mode': '1'}, 503), ({'sub_channel_enabled': '1', 'sub_channel_id': '@test'}, 403)]:
            storage.access_settings.return_value = settings
            result = await self.client.get('/api/me', headers=self.headers)
            self.assertEqual(result.status, expected)

    async def test_database_failure_does_not_expose_internal_error(self):
        with patch.object(storage, 'catalog', AsyncMock(side_effect=RuntimeError('INTERNAL_SECRET'))), self.assertLogs(server.logger, level='ERROR'):
            result = await self.client.get('/api/catalog', headers=self.headers)
            self.assertEqual(result.status, 503)
            self.assertNotIn('INTERNAL_SECRET', await result.text())

    async def test_untrusted_sort_is_rejected(self):
        with patch.object(storage, 'catalog', AsyncMock()) as catalog:
            result = await self.client.get('/api/catalog?sort=DROP_TABLE', headers=self.headers)
            self.assertEqual(result.status, 400)
            catalog.assert_not_awaited()

    async def test_rate_limit(self):
        for _ in range(120):
            self.assertEqual((await self.client.get('/api/me', headers=self.headers)).status, 200)
        self.assertEqual((await self.client.get('/api/me', headers=self.headers)).status, 429)


class CheckoutTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(), fetchall=AsyncMock())
        self.cur.lastrowid = 5
        self.conn = MagicMock(begin=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        pool = MagicMock(); pool.acquire.return_value.__aenter__.return_value = self.conn
        patcher = patch.object(admin_tools, '_get_pool', return_value=pool)
        patcher.start(); self.addCleanup(patcher.stop)

        # Sales switch locking and rejection are covered in test_shop_control.
        # These tests isolate the existing price, balance and order transaction.
        from database import shop_control
        sales = patch.object(shop_control, 'check_sales', AsyncMock())
        sales.start(); self.addCleanup(sales.stop)

    async def test_changed_price_rolls_back_without_charging(self):
        self.cur.fetchone.side_effect = [{'id': 1, 'price': 200, 'country': 'us'}, None, None]
        with self.assertRaisesRegex(storage.CheckoutError, 'Цена изменилась'):
            await storage.checkout(42, 1, Decimal('100'))
        self.conn.rollback.assert_awaited_once()
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_purchase_reads_price_under_lock_and_debits_rubles(self):
        self.cur.fetchone.side_effect = [{'id': 1, 'price': 100, 'country': 'us'}, None, None]
        self.cur.fetchall.return_value = [{'id': 42, 'balance': 500}]
        result = await storage.checkout(42, 1, Decimal('100'))
        self.assertEqual(result, {'id': 5, 'paid_amount': '100.00', 'balance': '400.00'})
        calls = self.cur.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[0].args[0])
        self.assertIn('UPDATE users SET balance = balance -', calls[4].args[0])
        self.conn.commit.assert_awaited_once()

    async def test_sold_account_never_debits(self):
        self.cur.fetchone.return_value = None
        with self.assertRaises(storage.CheckoutError): await storage.checkout(42, 1, Decimal('100'))
        self.assertEqual(self.cur.execute.await_count, 1)
        self.conn.rollback.assert_awaited_once()

    async def test_order_insert_failure_rolls_back_balance_and_stock(self):
        self.cur.fetchone.side_effect = [{'id': 1, 'price': 100, 'country': 'us'}, None, None]
        self.cur.fetchall.return_value = [{'id': 42, 'balance': 500}]
        self.cur.execute.side_effect = [None, None, None, None, None, OSError('insert failed')]
        with self.assertRaises(OSError): await storage.checkout(42, 1, Decimal('100'))
        self.conn.commit.assert_not_awaited()
        self.conn.rollback.assert_awaited_once()


class MiniAppBotIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_app_button_uses_configured_https_domain(self):
        import os
        from keyboards import user_kb
        with patch.dict(os.environ, {'MINIAPP_URL': 'https://sbandsub.space'}), \
             patch.object(user_kb, '_btn_text', AsyncMock(return_value=('Label', None))), \
             patch.object(user_kb, 'get_setting', AsyncMock(return_value='')):
            keyboard = await user_kb.main_menu(42)
            self.assertEqual(keyboard.inline_keyboard[0][0].web_app.url, 'https://sbandsub.space')

    async def test_shared_miniapp_link_opens_authenticated_webapp_button(self):
        import os
        from handlers.user import start
        message=SimpleNamespace(from_user=SimpleNamespace(id=42,username='fixture',first_name='Fixture'),answer=AsyncMock())
        with patch.dict(os.environ,MINIAPP_URL='https://sbandsub.space'), patch.object(start,'is_new_user',AsyncMock(return_value=False)), patch.object(start,'create_user_with_referrer',AsyncMock(return_value=Decimal(0))), patch.object(start,'update_user_username',AsyncMock()):
            await start.cmd_start(message,SimpleNamespace(args='miniapp'))
            keyboard=message.answer.call_args.kwargs['reply_markup']
            self.assertEqual(keyboard.inline_keyboard[0][0].web_app.url,'https://sbandsub.space')
            self.assertNotIn('initData',keyboard.inline_keyboard[0][0].web_app.url)

    async def test_public_app_link_metadata_does_not_require_login_or_expose_private_data(self):
        client=TestClient(TestServer(server.create_app(token=TEST_TOKEN,bot_username='fixture_bot')))
        try:
            await client.start_server()
            response=await client.get('/api/app-info')
            self.assertEqual(response.status,200)
            self.assertEqual(await response.json(),{'bot_username':'fixture_bot'})
            response=await client.get('/api/me')
            self.assertEqual(response.status,401)
        finally:await client.close()

    async def test_order_deep_link_checks_ownership_and_opens_existing_bot_flow(self):
        from handlers.user import start
        from keyboards import user_kb
        message = SimpleNamespace(from_user=SimpleNamespace(id=42, username='alex_test', first_name='Alex'), answer=AsyncMock())
        with patch.object(start, 'is_new_user', AsyncMock(return_value=False)), \
             patch.object(start, 'create_user_with_referrer', AsyncMock(return_value=Decimal(0))), \
             patch.object(start, 'update_user_username', AsyncMock()), \
             patch.object(db, 'get_purchase_for_user', AsyncMock(return_value={'id': 5, 'data': 'SECRET'})) as get, \
             patch.object(user_kb, 'after_purchase_menu', AsyncMock(return_value=None)) as menu:
            await start.cmd_start(message, SimpleNamespace(args='order_5'))
            get.assert_awaited_once_with(5, 42)
            menu.assert_awaited_once_with(5)
            self.assertNotIn('SECRET', message.answer.call_args.args[0])

    def test_url_validation_rejects_insecure_and_credential_urls(self):
        import os
        from utils.miniapp import miniapp_url
        for url in ('http://sbandsub.space', 'https://user:pass@sbandsub.space', 'https://sbandsub.space/path', 'https://sbandsub.space?token=x'):
            with self.subTest(url=url), patch.dict(os.environ, MINIAPP_URL=url), self.assertRaises(ValueError):
                miniapp_url()
