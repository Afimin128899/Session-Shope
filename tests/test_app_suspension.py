"""Default suspension must cover saved URLs, assets, APIs and Telegram entries."""
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
import test_miniapp
from test_miniapp import TEST_TOKEN
from miniapp import server
from miniapp.access import CUSTOMER_ENABLED, ADMIN_ENABLED
from utils import app_access, miniapp
from keyboards import user_kb, admin_kb


class SuspensionTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_suspension_blocks_both_apps_without_database_work(self):
        app=server.create_app(token=TEST_TOKEN,admin_only=False)
        self.assertFalse(app[CUSTOMER_ENABLED]);self.assertFalse(app[ADMIN_ENABLED])
        async with TestClient(TestServer(app)) as client:
            with patch.object(server.db,'get_user',AsyncMock()) as get:
                for path in ['/', '/assets/index.html','/assets/app.js','/demo','/api/me','/api/catalog','/api/app-info']:
                    self.assertEqual((await client.get(path)).status,503,path)
                for path in ['/admin-app','/admin-app/','/admin-assets/app.js','/admin-assets/index.html','/api/admin/identity','/api/admin/overview']:
                    self.assertEqual((await client.get(path)).status,404,path)
                self.assertEqual((await client.get('/api/health')).status,200)
                from miniapp import public_info
                with patch.object(public_info,'rows',AsyncMock(return_value=[])),patch.object(server.db,'get_setting',AsyncMock(return_value='')):
                    self.assertEqual((await client.get('/about')).status,200)
                    for path in ['/assets/style.css','/assets/design.css']:
                        self.assertEqual((await client.get(path)).status,200)
                get.assert_not_awaited()

    async def test_menu_clears_persisted_webapp_and_settings_are_retained(self):
        bot=NS(set_chat_menu_button=AsyncMock())
        with patch.dict(os.environ,MINIAPP_URL='https://example.com/'):
            self.assertEqual(miniapp.miniapp_url(),'https://example.com')
            self.assertIsNone(miniapp.customer_miniapp_url());self.assertIsNone(miniapp.admin_miniapp_url())
            await app_access.configure_chat_menu(bot)
        self.assertEqual(bot.set_chat_menu_button.call_args.kwargs['menu_button'].type,'commands')

    async def test_user_and_admin_menus_have_no_app_or_tickets(self):
        with patch.dict(os.environ,MINIAPP_URL='https://example.com'),patch('utils.app_access.CUSTOMER_MINIAPP_ADMIN_ONLY',False),patch.object(user_kb,'get_button_label',AsyncMock(return_value=None)),patch.object(user_kb,'get_setting',AsyncMock(side_effect=lambda key,default:default)):
            menus=[await user_kb.main_menu(42),await user_kb.profile_menu(),admin_kb.get_admin_panel()]
        for menu in menus:
            for row in menu.inline_keyboard:
                for b in row:
                    self.assertIsNone(b.web_app)
                    self.assertFalse((b.callback_data or '').startswith(('tk_', 'tk:')))
        self.assertTrue(any(b.callback_data=='support' for row in menus[0].inline_keyboard for b in row))


class SeparateAdminTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_admin_preview_gate_blocks_regular_users_before_database_or_checkout(self):
        async with TestClient(TestServer(server.create_app(token=TEST_TOKEN))) as client:
            page=await client.get('/')
            self.assertEqual(page.status,200)
            self.assertIn('Только для админов',await page.text())
            with patch.object(server.config,'ADMIN_IDS',[]),patch.object(server.db,'get_user',AsyncMock()) as lookup,patch.object(server.storage,'checkout',AsyncMock()) as checkout:
                for method,path in [('GET','/api/storefront-preview'),('GET','/api/me'),('GET','/api/catalog'),('POST','/api/purchase')]:
                    self.assertEqual((await client.request(method,path,headers=self.headers)).status,403)
                lookup.assert_not_awaited();checkout.assert_not_awaited()
            self.assertEqual((await client.get('/api/storefront-preview')).status,401)
            with patch.object(server.config,'ADMIN_IDS',[42]):
                response=await client.get('/api/storefront-preview',headers=self.headers)
                self.assertEqual(response.status,200)
                self.assertIn('catalog-grid',await response.text())

    async def test_miniapp_button_is_visible_to_everyone(self):
        with patch.dict(os.environ,MINIAPP_URL='https://example.com'),patch.object(user_kb,'get_button_label',AsyncMock(return_value=None)):
            for user in [42,99]:
                menu=await user_kb.main_menu(user)
                button=next(b for row in menu.inline_keyboard for b in row if b.web_app)
                self.assertEqual((button.text,button.web_app.url),('Mini App','https://example.com'))

    async def test_admin_only_app_runs_independently_of_disabled_customer(self):
        # Only fixtures opt in. Production start_server uses the disabled defaults.
        async with TestClient(TestServer(server.create_app(token=TEST_TOKEN,admin_enabled=True,admin_only=False))) as client:
            self.assertEqual((await client.get('/')).status,503)
            self.assertEqual((await client.get('/admin-app')).status,200)
            self.assertEqual((await client.get('/api/admin/identity')).status,401)
            with patch.object(server.config,'ADMIN_IDS',[]):
                self.assertEqual((await client.get('/api/admin/identity',headers=self.headers)).status,403)
            with patch.object(server.config,'ADMIN_IDS',[42]):
                r=await client.get('/api/admin/identity',headers=self.headers)
                self.assertEqual(r.status,200);self.assertEqual((await r.json())['user']['id'],42)
                self.assertEqual((await client.get('/api/admin/tickets',headers=self.headers)).status,410)
            self.assertEqual((await client.get('/api/catalog',headers=self.headers)).status,503)

    async def test_enabled_customer_cannot_create_or_reopen_tickets(self):
        from database import tickets
        with patch.object(tickets,'create_general',AsyncMock()) as create,patch.object(tickets,'reply',AsyncMock()) as reply:
            for method,path in [('GET','/api/support'),('POST','/api/support'),('POST','/api/support/1/reply'),('POST','/api/orders/1/warranty-claim')]:
                r=await self.client.request(method,path,headers=self.headers,json={'body':'Test'})
                self.assertEqual(r.status,410)
            create.assert_not_awaited();reply.assert_not_awaited()
