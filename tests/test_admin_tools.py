"""Admin access controls, safe search and transactional audit regressions."""
import asyncio
import json
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import config
from database import admin_tools as storage
from handlers.admin import tools as ui
from handlers.admin import admin_panel
from keyboards.admin_kb import get_admin_panel


class AdminMutationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur = MagicMock()
        self.cur.execute = AsyncMock()
        self.cur.fetchone = AsyncMock(return_value={'balance': Decimal('100.00')})
        self.cur.fetchall = AsyncMock(return_value=[])
        self.cur.rowcount = 1
        self.conn = MagicMock()
        self.conn.begin = AsyncMock()
        self.conn.commit = AsyncMock()
        self.conn.rollback = AsyncMock()
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__.return_value = self.conn
        patcher = patch.object(storage, '_get_pool', return_value=self.pool)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def test_balance_change_and_log_commit_together(self):
        await storage.change_balance(7, 42, '25.15', 'RUB', 'add')
        calls = self.cur.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[0].args[0])
        self.assertEqual(calls[1].args[1], (Decimal('125.15'), 42))
        log = calls[2].args[1]
        self.assertEqual(log[:4], (7, 'balance_add', 'user', '42'))
        self.assertEqual(json.loads(log[4]), {'currency': 'RUB', 'before': '100.00', 'after': '125.15000000'})
        self.conn.commit.assert_awaited_once()

    async def test_log_failure_rolls_back_balance(self):
        self.cur.execute.side_effect = [None, None, OSError('audit unavailable')]
        with self.assertRaises(OSError):
            await storage.change_balance(7, 42, '25', 'RUB', 'add')
        self.conn.commit.assert_not_awaited()
        self.conn.rollback.assert_awaited_once()

    async def test_usdt_set_uses_correct_balance(self):
        await storage.change_balance(7, 42, '10', 'USDT', 'set')
        self.assertIn('balance_usdt', self.cur.execute.call_args_list[1].args[0])
        self.assertEqual(self.cur.execute.call_args_list[1].args[1], (Decimal('10'), 42))

    async def test_invalid_money_never_starts_transaction(self):
        for value in ('NaN', 'Infinity', 'bad', '10000000000', '0.000000001'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                await storage.change_balance(7, 42, value, 'RUB', 'set')
        self.conn.begin.assert_not_awaited()

    async def test_admin_can_set_a_debt_or_add_above_the_sbp_limit(self):
        await storage.change_balance(7,42,'-101','RUB','add')
        self.assertEqual(self.cur.execute.call_args_list[1].args[1],(Decimal('-1'),42))
        self.conn.commit.assert_awaited_once()
        self.cur.execute.reset_mock()
        await storage.change_balance(7,42,'1000000','RUB','set')
        self.assertEqual(self.cur.execute.call_args_list[1].args[1],(Decimal('1000000'),42))

    async def test_balance_overflow_still_rolls_back(self):
        with self.assertRaises(ValueError):
            await storage.change_balance(7,42,'9999999999.99999999','RUB','add')
        self.conn.rollback.assert_awaited_once()

    async def test_missing_user_cannot_produce_success_log(self):
        self.cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            await storage.change_balance(7, 42, 1, 'RUB', 'add')
        self.conn.rollback.assert_awaited_once()
        self.assertEqual(self.cur.execute.await_count, 1)

    async def test_delete_log_failure_rolls_back_account_and_orders(self):
        self.cur.fetchone.return_value = {'country': 'cat', 'price': Decimal('100'), 'status': 'sold'}
        self.cur.execute.side_effect = [None, None, None, OSError('audit failed')]
        with self.assertRaises(OSError):
            await storage.remove_account(7, 8)
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()
        self.assertIn('DELETE FROM purchases', self.cur.execute.call_args_list[1].args[0])

    async def test_missing_account_is_not_logged(self):
        self.cur.fetchone.return_value = None
        self.assertFalse(await storage.remove_account(7, 8))
        self.assertEqual(self.cur.execute.await_count, 1)

    async def test_price_change_records_previous_value(self):
        self.cur.fetchone.return_value = {'price': Decimal('100.00')}
        self.assertTrue(await storage.change_account_price(7, 8, '150.50'))
        details = json.loads(self.cur.execute.call_args_list[2].args[1][4])
        self.assertEqual(details, {'before': '100.00', 'after': '150.50'})
        self.conn.commit.assert_awaited_once()

    async def test_bulk_price_records_count_and_previous_prices(self):
        self.cur.fetchall.return_value = [{'price': Decimal('100')}, {'price': Decimal('120')}]
        self.cur.rowcount = 2
        self.assertEqual(await storage.change_category_price(7, 'cat', '150'), 2)
        sql, params = self.cur.execute.call_args_list[1].args
        self.assertIn('WHERE country=%s', sql)
        self.assertIn("status IN ('available','review')", sql)
        self.assertEqual(params[-1], 'cat')
        details = json.loads(self.cur.execute.call_args_list[2].args[1][4])
        self.assertEqual(details['before'], ['100', '120'])
        self.assertEqual(details['updated'], 2)

    async def test_cancellation_rolls_back(self):
        self.cur.execute.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await storage.remove_account(7, 8)
        self.conn.rollback.assert_awaited_once()

    async def test_username_search_is_parameterized(self):
        query = "' OR 1=1 --"
        await storage.find_user(query)
        sql, params = self.cur.execute.call_args.args
        self.assertNotIn(query, sql)
        self.assertEqual(params, (query,))
        self.assertNotIn('password', sql)

    async def test_order_search_does_not_select_credentials(self):
        await storage.find_order(5)
        sql, params = self.cur.execute.call_args.args
        self.assertNotIn('password', sql)
        self.assertNotIn('a.*', sql)
        self.assertEqual(params, (5,))

    async def test_huge_id_never_reaches_mysql(self):
        self.assertIsNone(await storage.find_order(2**63))
        self.assertIsNone(await storage.find_user(str(2**64)))
        self.cur.execute.assert_not_awaited()


class AdminViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call = SimpleNamespace(from_user=SimpleNamespace(id=7), data='adm_audit')
        self.state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock())

    async def test_non_admin_callbacks_cannot_read_or_change_state(self):
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui, 'audit_entries', AsyncMock()) as entries, \
             patch.object(ui, 'find_order', AsyncMock()) as order, \
             patch.object(ui, 'answer_safe', AsyncMock()):
            for handler in (ui.open_search, ui.start_search, ui.open_order, ui.show_audit):
                await handler(self.call, self.state)
            entries.assert_not_awaited()
            order.assert_not_awaited()
            self.state.clear.assert_not_awaited()
            self.state.set_state.assert_not_awaited()

    async def test_non_admin_messages_cannot_search(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=7), text='42')
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui, 'find_user', AsyncMock()) as user, \
             patch.object(ui, 'find_order', AsyncMock()) as order:
            await ui.search_user(message, self.state)
            await ui.search_order(message, self.state)
            user.assert_not_awaited()
            order.assert_not_awaited()

    async def test_valid_order_search_clears_state_and_escapes_html(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=7), text='#52', answer=AsyncMock(), answer_photo=AsyncMock())
        order = {'id': 52, 'user_id': 42, 'account_id': 8, 'country': '<cat>', 'date': 'today', 'completed': True}
        with patch.object(ui, 'is_admin', return_value=True), patch.object(ui, 'find_order', AsyncMock(return_value=order)) as find:
            await ui.search_order(message, self.state)
            find.assert_awaited_once_with(52)
            self.state.clear.assert_awaited_once()
            self.assertIn('&lt;cat&gt;', message.answer_photo.call_args.kwargs['caption'])
            self.assertIn('Завершён', message.answer_photo.call_args.kwargs['caption'])

    async def test_invalid_order_search_does_not_query_database(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=7), text='bad', answer=AsyncMock())
        with patch.object(ui, 'is_admin', return_value=True), patch.object(ui, 'find_order', AsyncMock()) as find:
            await ui.search_order(message, self.state)
            find.assert_not_awaited()
            self.state.clear.assert_not_awaited()

    async def test_audit_pagination_and_timezone(self):
        entries = [dict(id=10-i, admin_id=7, action='balance_set', target_type='user', target_id='42',
                        details=json.dumps({'before': '100', 'after': '50', 'currency': 'RUB'}),
                        created_at=datetime(2026, 11, 2, 10)) for i in range(6)]
        with patch.object(ui, 'is_admin', return_value=True), \
             patch.object(ui, 'audit_entries', AsyncMock(return_value=entries)), \
             patch.object(ui, 'edit_message_safe', AsyncMock()) as edit, \
             patch.object(ui, 'answer_safe', AsyncMock()):
            await ui.show_audit(self.call, self.state)
            text = edit.call_args.args[1]
            self.assertIn('13:00:00 МСК', text)
            self.assertNotIn('#5 ·', text)
            self.assertEqual(edit.call_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data, 'adm_audit:6')

    async def test_balance_handler_uses_audited_change_with_actor(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=7), text='25', answer=AsyncMock())
        self.state.get_data = AsyncMock(return_value={'target_user_id': 42, 'balance_mode': 'add', 'balance_currency': 'RUB'})
        with patch.object(admin_panel, 'is_admin', return_value=True), \
             patch.object(admin_panel, 'change_balance', AsyncMock()) as change:
            await admin_panel.admin_balance_step_3(message, self.state)
            change.assert_awaited_once_with(7, 42, '25', 'RUB', 'add')

    async def test_menu_exposes_search_and_audit(self):
        callbacks = {b.callback_data for row in get_admin_panel().inline_keyboard for b in row}
        self.assertTrue({'adm_search', 'adm_audit'} <= callbacks)
