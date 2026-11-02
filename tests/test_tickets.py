"""Ticket ownership, transitions, persistence and order migration regressions."""
import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import db
from database import admin_tools, tickets
from database.support_schema import init_support_schema
from handlers import tickets as ui
from handlers.admin.tools import order_card, order_menu
from utils.order_status import order_status


class TicketStorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur = MagicMock()
        self.cur.execute = AsyncMock()
        self.cur.fetchone = AsyncMock()
        self.cur.fetchall = AsyncMock(return_value=[])
        self.cur.lastrowid = 9
        self.conn = MagicMock()
        self.conn.begin = AsyncMock()
        self.conn.commit = AsyncMock()
        self.conn.rollback = AsyncMock()
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__.return_value = self.conn
        for module in (admin_tools, tickets):
            patcher = patch.object(module, '_get_pool', return_value=self.pool)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_creation_locks_owners_order_and_saves_message(self):
        self.cur.fetchone.side_effect = [{'id': 52}, None]
        self.assertEqual(await tickets.create_ticket(42, 52, 'Problem'), 9)
        calls = self.cur.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[0].args[0])
        self.assertEqual(calls[0].args[1], (52, 42))
        self.assertIn('INSERT INTO support_tickets', calls[2].args[0])
        self.assertEqual(calls[3].args[1], (9, 42, 'user', 'Problem'))
        self.conn.commit.assert_awaited_once()

    async def test_other_users_order_cannot_create_ticket(self):
        self.cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            await tickets.create_ticket(42, 52, 'Problem')
        self.assertEqual(self.cur.execute.await_count, 1)
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_concurrent_submission_reuses_ticket_for_order(self):
        self.cur.fetchone.side_effect = [{'id': 52}, {'id': 9}]
        self.assertEqual(await tickets.create_ticket(42, 52, 'Another message'), 9)
        self.assertFalse(any('INSERT INTO support_tickets' in c.args[0] for c in self.cur.execute.call_args_list))
        self.assertIn("status = 'open'", self.cur.execute.call_args_list[2].args[0])

    async def test_message_failure_rolls_back_new_ticket(self):
        self.cur.fetchone.side_effect = [{'id': 52}, None]
        self.cur.execute.side_effect = [None, None, None, OSError('write failed')]
        with self.assertRaises(OSError):
            await tickets.create_ticket(42, 52, 'Problem')
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_user_reply_filters_owner_and_reopens_ticket(self):
        self.cur.fetchone.return_value = {'id': 9, 'user_id': 42}
        self.assertEqual(await tickets.reply(9, 42, 'Still broken'), 42)
        calls = self.cur.execute.call_args_list
        self.assertIn('AND user_id = %s FOR UPDATE', calls[0].args[0])
        self.assertEqual(calls[0].args[1], (9, 42))
        self.assertEqual(calls[2].args[1], ('open', 9))

    async def test_non_owner_reply_is_rejected(self):
        self.cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            await tickets.reply(9, 99, 'Not my order')
        self.assertEqual(self.cur.execute.await_count, 1)
        self.conn.rollback.assert_awaited_once()

    async def test_admin_reply_changes_status_and_audits_without_body(self):
        self.cur.fetchone.return_value = {'id': 9, 'user_id': 42}
        await tickets.reply(9, 7, 'Answer', admin=True)
        calls = self.cur.execute.call_args_list
        self.assertEqual(calls[1].args[1], (9, 7, 'admin', 'Answer'))
        self.assertEqual(calls[2].args[1], ('waiting_user', 9))
        self.assertIn('INSERT INTO admin_audit_log', calls[3].args[0])
        self.assertNotIn('Answer', str(calls[3].args[1]))
        self.conn.commit.assert_awaited_once()

    async def test_close_is_idempotent(self):
        self.cur.fetchone.return_value = {'user_id': 42, 'status': 'closed'}
        self.assertIsNone(await tickets.close_ticket(9, 7))
        self.assertEqual(self.cur.execute.await_count, 1)

    async def test_close_records_system_message_and_audit(self):
        self.cur.fetchone.return_value = {'user_id': 42, 'status': 'open'}
        self.assertEqual(await tickets.close_ticket(9, 7), 42)
        calls = self.cur.execute.call_args_list
        self.assertIn("status = 'closed'", calls[1].args[0])
        self.assertEqual(calls[2].args[1][2], 'system')
        self.assertEqual(calls[3].args[1][1], 'ticket_close')

    async def test_ticket_history_enforces_owner_in_sql(self):
        await tickets.history(9, 42, 100)
        sql, params = self.cur.execute.call_args.args
        self.assertIn('t.user_id = %s', sql)
        self.assertIn('m.id < %s', sql)
        self.assertEqual(params, (9, 42, 100))

    async def test_body_bounds_checked_before_database(self):
        for body in ('', '   ', 'x' * 501):
            with self.subTest(body=body[:10]), self.assertRaises(ValueError):
                await tickets.create_ticket(42, 52, body)
        self.conn.begin.assert_not_awaited()

    async def test_deletion_with_ticket_preserves_order_and_history(self):
        self.cur.fetchone.return_value = {'country': 'cat', 'price': 100, 'status': 'sold'}
        self.cur.execute.side_effect = [None, admin_tools.aiomysql.IntegrityError(1451, 'referenced')]
        with self.assertRaisesRegex(ValueError, 'история поддержки'):
            await admin_tools.remove_account(7, 8)
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_cancellation_rolls_back(self):
        self.cur.execute.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await tickets.create_ticket(42, 52, 'Problem')
        self.conn.rollback.assert_awaited_once()


class OrderMigrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_run_adds_columns_and_protects_ticket_history(self):
        cur = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(return_value=None))
        await init_support_schema(cur, 'test_shop')
        sql = [c.args[0] for c in cur.execute.call_args_list]
        self.assertEqual(sum('ALTER TABLE' in q for q in sql), 2)
        self.assertTrue(any('ON DELETE RESTRICT' in q for q in sql))
        self.assertTrue(any("SET p.status = 'completed'" in q for q in sql))

    async def test_repeat_run_skips_alter_but_recovers_interrupted_backfill(self):
        cur = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(return_value={'COLUMN_NAME': 'present'}))
        await init_support_schema(cur, 'test_shop')
        sql = [c.args[0] for c in cur.execute.call_args_list]
        self.assertFalse(any('ALTER TABLE' in q for q in sql))
        self.assertTrue(any("WHERE p.status = 'issued'" in q for q in sql))

    async def test_completion_updates_state_and_clears_session_atomically(self):
        cur = MagicMock(execute=AsyncMock())
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def transaction():
            yield cur
        with patch.object(admin_tools, '_transaction', transaction):
            await db.complete_user_purchase(8)
        self.assertIn("status = 'completed'", cur.execute.call_args_list[0].args[0])
        self.assertIn('UPDATE accounts SET data', cur.execute.call_args_list[1].args[0])

    def test_status_changes_follow_active_ticket_without_losing_completion(self):
        self.assertEqual(order_status({'status': 'issued'}), 'Оплачен и выдан')
        self.assertEqual(order_status({'status': 'completed'}), 'Завершён')
        self.assertIn('Проблема', order_status({'status': 'completed', 'ticket_status': 'open'}))
        self.assertEqual(order_status({'status': 'completed', 'ticket_status': 'closed'}), 'Завершён')


class TicketViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call = SimpleNamespace(data='tk:9:0', from_user=SimpleNamespace(id=42))
        self.state = SimpleNamespace(clear=AsyncMock(), get_data=AsyncMock(return_value={'ticket_id': 9}),
                                     update_data=AsyncMock(), set_state=AsyncMock())

    async def test_non_admin_cannot_close_or_list_admin_tickets(self):
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui.store, 'close_ticket', AsyncMock()) as close, \
             patch.object(ui.store, 'inbox', AsyncMock()) as inbox, \
             patch.object(ui, 'answer_safe', AsyncMock()):
            self.call.data = 'tk_close:9'
            await ui.close_ticket(self.call, self.state)
            self.call.data = 'tk_admin:active:0'
            await ui.show_inbox(self.call, self.state)
            close.assert_not_awaited()
            inbox.assert_not_awaited()

    async def test_owner_filter_is_used_when_opening_ticket(self):
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui.store, 'get_ticket', AsyncMock(return_value=None)) as get, \
             patch.object(ui.store, 'history', AsyncMock()) as history, \
             patch.object(ui, 'answer_safe', AsyncMock()):
            await ui.display_ticket(self.call, 9)
            get.assert_awaited_once_with(9, 42)
            history.assert_not_awaited()

    async def test_worst_case_html_body_fits_and_is_escaped(self):
        ticket = {'id': 9, 'purchase_id': 52, 'status': 'open'}
        message = {'id': 100, 'body': '"' * 500, 'author_role': 'user', 'created_at': datetime(2026, 11, 2)}
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui.store, 'get_ticket', AsyncMock(return_value=ticket)), \
             patch.object(ui.store, 'history', AsyncMock(return_value=[message, {'id': 99}])), \
             patch.object(ui, 'edit_message_safe', AsyncMock()) as edit:
            await ui.display_ticket(self.call, 9)
            text = edit.call_args.args[1]
            self.assertIn('&quot;', text)
            self.assertLess(len(text), 4096)
            callbacks = [b.callback_data for row in edit.call_args.kwargs['reply_markup'].inline_keyboard for b in row]
            self.assertIn('tk:9:100', callbacks)
            self.assertNotIn('tk_close:9', callbacks)

    async def test_lost_admin_rights_are_rechecked_on_message_submit(self):
        message = SimpleNamespace(from_user=SimpleNamespace(id=42), text='Reply', answer=AsyncMock(), bot=SimpleNamespace())
        with patch.object(ui, 'is_admin', return_value=False), \
             patch.object(ui.store, 'reply', AsyncMock(return_value=42)) as reply, \
             patch.object(ui, 'notify', AsyncMock()):
            await ui.submit_reply(message, self.state)
            reply.assert_awaited_once_with(9, 42, 'Reply', admin=False)

    async def test_notification_failure_does_not_lose_saved_reply(self):
        bot = SimpleNamespace(send_message=AsyncMock(side_effect=OSError('offline')))
        with self.assertLogs(ui.logger, level='WARNING'):
            await ui.notify(bot, [42], 9, 'New reply')
        bot.send_message.assert_awaited_once()

    def test_admin_order_card_exposes_status_and_ticket(self):
        order = {'id': 52, 'user_id': 42, 'account_id': 8, 'date': 'today', 'ticket_id': 9,
                 'ticket_status': 'open', 'status': 'completed'}
        self.assertIn('Проблема', order_card(order))
        self.assertEqual(order_menu(order).inline_keyboard[0][0].callback_data, 'tk:9:0')
