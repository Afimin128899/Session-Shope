"""Browser sessions, email challenges, Telegram Login Widget and GEO endpoints."""
import hashlib
import hmac
import os
import re
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

import test_miniapp
from database import web_auth
from miniapp import browser_auth, server
from miniapp.auth import AuthError, normalize_email, validate_login_widget


def widget_data(user_id=42, timestamp=None):
    data = {
        'id': user_id,
        'first_name': 'Alex',
        'username': 'alex_test',
        'auth_date': int(time.time()) if timestamp is None else timestamp,
    }
    check = '\n'.join(f'{key}={data[key]}' for key in sorted(data))
    secret = hashlib.sha256(test_miniapp.TEST_TOKEN.encode()).digest()
    data['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return data


class BrowserAuthValidationTests(unittest.TestCase):
    def test_login_widget_signature_and_age_are_verified(self):
        self.assertEqual(validate_login_widget(widget_data(), test_miniapp.TEST_TOKEN)['id'], 42)
        changed = widget_data()
        changed['id'] = 43
        with self.assertRaises(AuthError):
            validate_login_widget(changed, test_miniapp.TEST_TOKEN)
        with self.assertRaises(AuthError):
            validate_login_widget(widget_data(timestamp=int(time.time()) - 3601), test_miniapp.TEST_TOKEN)

    def test_telegram_and_web_identity_ranges_do_not_overlap(self):
        with self.assertRaises(AuthError):
            validate_login_widget(widget_data(user_id=web_auth.WEB_USER_ID_BASE), test_miniapp.TEST_TOKEN)
        self.assertGreaterEqual(web_auth.WEB_USER_ID_BASE, web_auth.TELEGRAM_ID_LIMIT)
        self.assertLess(web_auth.WEB_USER_ID_BASE, 2**63)

    def test_email_normalization_is_strict_and_stable(self):
        self.assertEqual(normalize_email('  Buyer@Example.COM '), 'buyer@example.com')
        self.assertEqual(normalize_email('buyer@пример.рф'), 'buyer@xn--e1afmkfd.xn--p1ai')
        for value in ('a@b', '.a@example.com', 'a..b@example.com', 'a\n@example.com', 'тест@example.com'):
            with self.subTest(value=value), self.assertRaises(AuthError):
                normalize_email(value)

    def test_smtp_sender_must_contain_a_valid_mailbox(self):
        settings = {
            'AUTH_SMTP_HOST': 'smtp.example.com',
            'AUTH_SMTP_PORT': '587',
            'AUTH_SMTP_SECURITY': 'starttls',
            'AUTH_SMTP_FROM': 'SBAND ACCS <login@example.com>',
        }
        with patch.dict(os.environ, settings, clear=True):
            self.assertEqual(browser_auth.smtp_settings()[0], 'smtp.example.com')
        settings['AUTH_SMTP_FROM'] = 'not-an-email'
        with patch.dict(os.environ, settings, clear=True), self.assertRaises(browser_auth.EmailUnavailable):
            browser_auth.smtp_settings()

    def test_resend_provider_requires_key_and_valid_sender(self):
        settings = {
            'AUTH_EMAIL_PROVIDER': 'resend',
            'RESEND_API_KEY': 're_fixture',
            'AUTH_SMTP_FROM': 'SBAND ACCS <support@sbandsub.space>',
        }
        with patch.dict(os.environ, settings, clear=True):
            self.assertEqual(browser_auth.check_email_settings(), ('re_fixture', settings['AUTH_SMTP_FROM']))
        settings.pop('RESEND_API_KEY')
        with patch.dict(os.environ, settings, clear=True), self.assertRaises(browser_auth.EmailUnavailable):
            browser_auth.check_email_settings()


class ResendDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_resend_uses_https_and_never_puts_key_in_payload(self):
        calls = {}

        class Reply:
            status = 200
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            async def json(self, **_kwargs): return {'id': 'email-fixture'}

        class Session:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return False
            def post(self, url, **kwargs):
                calls.update(url=url, **kwargs)
                return Reply()

        settings = {
            'AUTH_EMAIL_PROVIDER': 'resend',
            'RESEND_API_KEY': 're_private_fixture',
            'AUTH_SMTP_FROM': 'SBAND ACCS <support@sbandsub.space>',
        }
        with patch.dict(os.environ, settings, clear=True), \
             patch.object(browser_auth.aiohttp, 'ClientSession', return_value=Session()):
            await browser_auth.send_email_code('buyer@example.com', '123456')
        self.assertEqual(calls['url'], 'https://api.resend.com/emails')
        self.assertEqual(calls['json']['to'], ['buyer@example.com'])
        self.assertNotIn('re_private_fixture', str(calls['json']))
        self.assertEqual(calls['headers']['Authorization'], 'Bearer re_private_fixture')


class EmailChallengePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_attempt_is_committed_before_error_is_raised(self):
        cur = SimpleNamespace(
            execute=AsyncMock(),
            fetchone=AsyncMock(return_value={
                'code_hash': 'expected', 'attempts': 0, 'active': 1,
            }),
        )
        state = {'committed': False, 'raised_inside': False}

        @asynccontextmanager
        async def transaction():
            try:
                yield cur
            except BaseException:
                state['raised_inside'] = True
                raise
            else:
                state['committed'] = True

        with patch.object(web_auth, '_transaction', transaction):
            with self.assertRaises(web_auth.EmailCodeError):
                await web_auth.consume_email_code(
                    'buyer@example.com', 'email-hash', 'wrong-code-hash',
                )
        self.assertTrue(state['committed'])
        self.assertFalse(state['raised_inside'])
        self.assertIn(
            'UPDATE web_email_codes SET attempts=',
            cur.execute.await_args_list[-1].args[0],
        )


class BrowserAuthAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown = test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_email_code_creates_httponly_session_without_exposing_token(self):
        identity = {'id': 7, 'user_id': web_auth.WEB_USER_ID_BASE + 7}
        with patch.object(browser_auth, 'smtp_settings', return_value=('smtp.test', 587, 'starttls', '', '', 'shop@test')), \
             patch.object(web_auth, 'save_email_code', AsyncMock(return_value=(True, 60))) as save, \
             patch.object(browser_auth, 'send_email_code', AsyncMock()) as send:
            result = await self.client.post('/api/auth/email/start', json={'email': 'Buyer@Example.com'})
            self.assertEqual(result.status, 202)
            save.assert_awaited_once()
            recipient, code = send.await_args.args
            self.assertEqual(recipient, 'buyer@example.com')
            self.assertRegex(code, r'^[0-9]{6}$')

        with patch.object(web_auth, 'consume_email_code', AsyncMock(return_value=identity)) as consume, \
             patch.object(web_auth, 'create_session', AsyncMock(return_value=('opaque-session-token-value-123456789', 3600))):
            result = await self.client.post('/api/auth/email/verify', json={
                'email': 'buyer@example.com', 'code': '123456',
            })
            self.assertEqual(result.status, 200)
            consume.assert_awaited_once()
            cookie = result.headers['Set-Cookie']
            self.assertIn('sband_session=', cookie)
            self.assertIn('HttpOnly', cookie)
            self.assertIn('Secure', cookie)
            self.assertIn('SameSite=Lax', cookie)
            self.assertNotIn('opaque-session-token', await result.text())

    async def test_browser_cookie_authenticates_api_and_cross_site_write_is_blocked(self):
        identity = {
            'id': 42, 'first_name': 'Alex', 'username': 'alex_test',
            'auth_method': 'telegram', 'identity_id': 3,
        }
        with patch.object(web_auth, 'session_identity', AsyncMock(return_value=identity)) as session:
            result = await self.client.get('/api/me', headers={'Cookie': 'sband_session=' + 'x' * 40})
            self.assertEqual(result.status, 200)
            self.assertEqual((await result.json())['user']['auth_method'], 'telegram')
            session.assert_awaited()
            result = await self.client.post(
                '/api/preferences/language',
                headers={
                    'Cookie': 'sband_session=' + 'x' * 40,
                    'Origin': 'https://evil.example',
                    'Sec-Fetch-Site': 'cross-site',
                },
                json={'language': 'ru'},
            )
            self.assertEqual(result.status, 403)

    async def test_email_user_id_stays_exact_in_browser_json(self):
        user_id = web_auth.WEB_USER_ID_BASE + 17
        identity = {
            'id': user_id, 'first_name': 'buyer', 'username': None,
            'email': 'buyer@example.com', 'auth_method': 'email',
            'identity_id': 17,
        }
        with patch.object(web_auth, 'session_identity', AsyncMock(return_value=identity)):
            result = await self.client.get(
                '/api/me', headers={'Cookie': 'sband_session=' + 'x' * 40},
            )
        self.assertEqual(result.status, 200)
        self.assertEqual((await result.json())['user']['id'], str(user_id))

    async def test_login_widget_endpoint_issues_session_for_verified_telegram_user(self):
        identity = {'id': 9, 'user_id': 42}
        with patch.object(web_auth, 'telegram_identity', AsyncMock(return_value=identity)) as upsert, \
             patch.object(web_auth, 'create_session', AsyncMock(return_value=('telegram-session-token-value-12345', 3600))):
            result = await self.client.post('/api/auth/telegram', json=widget_data())
            self.assertEqual(result.status, 200)
            upsert.assert_awaited_once()
            self.assertIn('sband_session=', result.headers['Set-Cookie'])

    async def test_logout_revokes_and_expires_browser_session(self):
        token = 'x' * 40
        with patch.object(web_auth, 'revoke_session', AsyncMock()) as revoke:
            result = await self.client.post(
                '/api/auth/logout',
                headers={'Cookie': 'sband_session=' + token},
                json={},
            )
        self.assertEqual(result.status, 200)
        revoke.assert_awaited_once_with(token)
        cookie = result.headers['Set-Cookie']
        self.assertIn('sband_session=', cookie)
        self.assertIn('Max-Age=0', cookie)
        self.assertIn('HttpOnly', cookie)

    async def test_discovery_files_are_public_and_keep_private_paths_out(self):
        for path in (
            '/robots.txt', '/llms.txt', '/llms-full.txt', '/ai.txt',
            '/.well-known/ai.txt', '/sitemap.xml', '/summary.json',
            '/ai/summary.json', '/ai/faq.json', '/ai/service.json',
            '/feed.xml', '/index.md', '/about.md',
        ):
            result = await self.client.get(path)
            self.assertEqual(result.status, 200, path)
            self.assertIn('public', result.headers['Cache-Control'])
        robots = await (await self.client.get('/robots.txt')).text()
        self.assertIn('User-agent: OAI-SearchBot', robots)
        self.assertIn('User-agent: Claude-SearchBot', robots)
        self.assertIn('User-agent: PerplexityBot', robots)
        self.assertGreaterEqual(robots.count('Disallow: /api/'), 3)
        sitemap = await (await self.client.get('/sitemap.xml')).text()
        self.assertIn('https://sbandsub.space/about', sitemap)
        self.assertNotIn('/api/', sitemap)

    async def test_public_pages_offer_markdown_without_database_or_javascript(self):
        result = await self.client.get('/', headers={'Accept': 'text/markdown'})
        self.assertEqual(result.status, 200)
        self.assertEqual(result.content_type, 'text/markdown')
        self.assertIn('# SBAND ACCS', await result.text())
        self.assertEqual(result.headers.get('Vary'), 'Accept')

    async def test_storefront_has_canonical_schema_and_both_login_methods(self):
        result = await self.client.get('/')
        text = await result.text()
        self.assertIn('<link rel="canonical" href="https://sbandsub.space/">', text)
        self.assertIn('application/ld+json', text)
        self.assertIn('id="email-start-form"', text)
        self.assertIn('id="telegram-widget"', text)
        self.assertIn('Как работает SBAND ACCS', text)


class ClosedGateDiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_home_remains_factual_and_indexable(self):
        app = server.create_app(token=test_miniapp.TEST_TOKEN)
        async with TestClient(TestServer(app)) as client:
            with patch.object(server.db, 'get_setting', AsyncMock(return_value='0')):
                result = await client.get('/')
            text = await result.text()
            self.assertEqual(result.status, 200)
            self.assertIn('Только для админов', text)
            self.assertIn('SBAND ACCS — магазин Telegram-аккаунтов', text)
            self.assertIn('rel="canonical"', text)
            self.assertNotIn('noindex', text)


if __name__ == '__main__':
    unittest.main()
