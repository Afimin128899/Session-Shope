"""Offline access revocation tests; no live Telegram sessions are used."""
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
from test_payments import config
from database import order_access as access
from database import bot_store


class OrderAccessTests(unittest.IsolatedAsyncioTestCase):
    def transaction(self, rows):
        cur = NS(execute=AsyncMock(), fetchone=AsyncMock(side_effect=rows))
        @asynccontextmanager
        async def tx():
            yield cur
        return cur, tx

    def test_revoked_view_hides_credentials_without_changing_history(self):
        row = {'id': 7, 'status': 'issued', 'paid_amount': '12', 'data': 'secret',
               'password': 'private', 'code': '12345', 'access_revoked_at': 'now'}
        result = access.customer_view(row)
        self.assertIsNone(result['data'])
        self.assertIsNone(result['password'])
        self.assertIsNone(result['code'])
        self.assertEqual(result['paid_amount'], '12')
        self.assertEqual(row['data'], 'secret')
        self.assertIsNone(access.customer_view(None))

    async def test_revoke_is_audited_and_repeat_does_not_overwrite(self):
        cur, tx = self.transaction([{'id': 7, 'status': 'issued', 'access_revoked_at': None}])
        with patch.object(access, '_transaction', tx), patch.object(access, '_record', AsyncMock()) as log:
            self.assertTrue(await access.revoke(42, 7, 'Support decision'))
            self.assertIn('FOR UPDATE', cur.execute.call_args_list[0].args[0])
            log.assert_awaited_once()
        cur, tx = self.transaction([{'id': 7, 'status': 'issued', 'access_revoked_at': 'now'}])
        with patch.object(access, '_transaction', tx), patch.object(access, '_record', AsyncMock()) as log:
            self.assertFalse(await access.revoke(42, 7, 'Duplicate'))
            self.assertEqual(cur.execute.await_count, 1)
            log.assert_not_awaited()

    async def test_invalid_reason_or_refunded_order_cannot_be_revoked(self):
        for reason in ('', 'x', None, 'x'*501):
            with self.assertRaises(ValueError):
                await access.revoke(42, 7, reason)
        cur, tx = self.transaction([{'status': 'refunded'}])
        with patch.object(access, '_transaction', tx):
            with self.assertRaises(ValueError):
                await access.revoke(42, 7, 'Support decision')
        self.assertEqual(cur.execute.await_count, 1)

    async def test_cleanup_requires_revocation_and_retained_identity(self):
        for rows in ([{'status': 'issued', 'access_revoked_at': None}],
                     [{'status': 'issued', 'access_revoked_at': 'now', 'account_id': 9}, {'data': None}]):
            cur, tx = self.transaction(rows)
            with patch.object(access, '_transaction', tx), patch('services.session_audit.clean_other_sessions', AsyncMock()) as clean:
                with self.assertRaises(ValueError):
                    await access.terminate(42, 7)
                clean.assert_not_awaited()

    async def test_telegram_failure_is_audited_without_restoring_shop_access(self):
        cur, tx = self.transaction([{'status': 'issued', 'access_revoked_at': 'now', 'account_id': 9},
                                    {'data': 'private-session', 'telegram_user_id': 123}])
        result = {'status': 'failed', 'reason': 'flood_wait', 'retry_after': 30}
        with patch.object(access, '_transaction', tx), patch.object(access, '_record', AsyncMock()) as log, patch('services.session_audit.clean_other_sessions', AsyncMock(return_value=result)) as clean:
            self.assertEqual(await access.terminate(42, 7), result)
            clean.assert_awaited_once_with('private-session', 123)
            self.assertEqual(log.call_args.args[-1], result)
            self.assertFalse(any('UPDATE purchases' in c.args[0] for c in cur.execute.call_args_list))

    async def test_old_completion_button_cannot_delete_revoked_session(self):
        cur, tx = self.transaction([{'account_id': 9, 'status': 'issued', 'access_revoked_at': 'now'}])
        with patch.object(bot_store, '_transaction', tx):
            with self.assertRaises(ValueError):
                await bot_store.complete_order(10, 7)
        self.assertEqual(cur.execute.await_count, 1)


import test_miniapp
from miniapp import server


class OrderAccessAPI(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown = test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_non_admin_cannot_revoke_or_terminate(self):
        with patch.object(access, 'revoke', AsyncMock()) as revoke, patch.object(access, 'terminate', AsyncMock()) as terminate:
            for action in ('revoke-access', 'terminate-sessions'):
                response = await self.client.post('/api/admin/orders/7/'+action, headers=self.headers, json={'reason': 'Support decision'})
                self.assertEqual(response.status, 403)
            revoke.assert_not_awaited()
            terminate.assert_not_awaited()

    async def test_mutations_use_signed_admin_identity(self):
        with patch.object(config, 'ADMIN_IDS', [42]), patch.object(access, 'revoke', AsyncMock(return_value=True)) as revoke, patch.object(access, 'terminate', AsyncMock(return_value={'status': 'single'})) as terminate:
            response = await self.client.post('/api/admin/orders/7/revoke-access', headers=self.headers, json={'reason': 'Support decision', 'admin_id': 999})
            self.assertEqual(response.status, 200)
            revoke.assert_awaited_once_with(42, 7, 'Support decision')
            response = await self.client.post('/api/admin/orders/7/terminate-sessions', headers=self.headers, json={})
            self.assertEqual(response.status, 200)
            terminate.assert_awaited_once_with(42, 7)

    async def test_revocation_during_login_code_fetch_discards_code(self):
        order = {'id': 7, 'status': 'issued', 'data': 'retained-session', 'number': '+15550000000'}
        revoked = dict(order, data=None, access_revoked_at='now')
        with patch.object(server, 'limited', return_value=False), patch.object(server.db, 'get_purchase_for_user', AsyncMock(side_effect=[order, revoked])), patch('services.telethon_code.try_fetch_login_code', AsyncMock(return_value='12345')):
            response = await self.client.post('/api/orders/7/code', headers=self.headers, json={})
            self.assertEqual(response.status, 409)
            self.assertNotIn('12345', await response.text())
