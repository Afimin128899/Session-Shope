"""Refund ownership, one-time crediting, commission reversal and access removal."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import db
from database import admin_tools, refunds
from handlers.admin import refunds as ui
from handlers.user import shop
from miniapp import server
from utils.order_status import order_status


class RefundTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.order = dict(id=5, user_id=42, account_id=8, paid_amount=Decimal('95'), currency='RUB',
                          status='issued', referrer_id=43, referral_bonus=Decimal('5'))
        self.cur = MagicMock(execute=AsyncMock(), fetchone=AsyncMock(side_effect=[self.order, None]),
                             fetchall=AsyncMock(return_value=[{'id': 42, 'balance': Decimal('100')}, {'id': 43, 'balance': Decimal('2')}]))
        self.conn = MagicMock(begin=AsyncMock(), commit=AsyncMock(), rollback=AsyncMock())
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__.return_value = self.conn
        p = patch.object(admin_tools, '_get_pool', return_value=self.pool)
        p.start(); self.addCleanup(p.stop)

    async def test_refund_credits_paid_amount_and_reverses_recorded_bonus(self):
        result = await refunds.refund_order(7, 5, 'Account unavailable')
        self.assertEqual(result['amount'], '95')
        updates = [c.args[1] for c in self.cur.execute.call_args_list if c.args[0].startswith('UPDATE users')]
        self.assertEqual(updates, [(Decimal('195'), 42), (Decimal('-3'), 43)])
        self.conn.commit.assert_awaited_once()
        sql = '\n'.join(c.args[0] for c in self.cur.execute.call_args_list)
        self.assertIn("status = 'refunded', data = '', password = NULL", sql)
        self.assertIn('INSERT INTO order_refunds', sql)
        self.assertIn('INSERT INTO admin_audit_log', sql)

    async def test_already_refunded_never_credits_again(self):
        self.order['status'] = 'refunded'
        self.assertIsNone(await refunds.refund_order(7, 5, 'Duplicate check'))
        self.assertEqual(self.cur.execute.await_count, 1)

    async def test_unpaid_order_cannot_be_refunded(self):
        self.order['status'] = 'pending'
        with self.assertRaisesRegex(ValueError, 'оплаченного'):
            await refunds.refund_order(7, 5, 'Not charged')
        self.conn.commit.assert_not_awaited()

    async def test_unknown_legacy_amount_is_not_invented_from_current_price(self):
        self.order['paid_amount'] = None
        with self.assertRaisesRegex(ValueError, 'не сохранена'):
            await refunds.refund_order(7, 5, 'Old order')
        self.conn.rollback.assert_awaited_once()
        self.assertEqual(self.cur.execute.await_count, 1)

    async def test_legacy_unknown_bonus_is_recorded_without_guessing(self):
        self.order.update(referral_bonus=None, referrer_id=None)
        self.cur.fetchall.return_value = [{'id': 42, 'balance': Decimal('100')}]
        await refunds.refund_order(7, 5, 'Legacy order')
        insert = next(c for c in self.cur.execute.call_args_list if 'INSERT INTO order_refunds' in c.args[0])
        self.assertTrue(insert.args[1][-1])
        self.assertEqual(insert.args[1][-2], 0)

    async def test_usdt_refund_uses_original_balance(self):
        self.order.update(currency='USDT', referral_bonus=0, referrer_id=None)
        self.cur.fetchall.return_value = [{'id': 42, 'balance': Decimal('0')}]
        await refunds.refund_order(7, 5, 'USDT order')
        sql = next(c.args[0] for c in self.cur.execute.call_args_list if c.args[0].startswith('UPDATE users'))
        self.assertIn('balance_usdt', sql)

    async def test_failed_audit_rolls_back_credit_and_status(self):
        async def execute(sql, params):
            if 'INSERT INTO admin_audit_log' in sql:
                raise RuntimeError('audit failed')
        self.cur.execute.side_effect = execute
        with self.assertRaises(RuntimeError):
            await refunds.refund_order(7, 5, 'Failed audit')
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_missing_user_prevents_partial_refund(self):
        self.cur.fetchall.return_value = []
        with self.assertRaises(ValueError):
            await refunds.refund_order(7, 5, 'Missing user')
        self.conn.commit.assert_not_awaited()

    async def test_invalid_reason_does_not_begin_transaction(self):
        for reason in ('', 'no', 'x' * 501):
            with self.assertRaises(ValueError): await refunds.refund_order(7, 5, reason)
        self.conn.begin.assert_not_awaited()

    async def test_cancellation_rolls_back(self):
        self.cur.execute.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError): await refunds.refund_order(7, 5, 'Cancelled')
        self.conn.rollback.assert_awaited_once()


class RefundViewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.call = SimpleNamespace(data='adm_refund_confirm:5', from_user=SimpleNamespace(id=7))
        self.state = SimpleNamespace(clear=AsyncMock(), get_data=AsyncMock(return_value={'refund_order_id': 5, 'refund_reason': 'Problem'}),
                                     get_state=AsyncMock(return_value=ui.RefundInput.confirm.state))

    async def test_non_admin_cannot_start_or_confirm(self):
        with patch.object(ui, 'is_admin', return_value=False), patch.object(ui, 'answer_safe', AsyncMock()), \
             patch.object(ui, 'find_order', AsyncMock()) as find, patch.object(ui, 'refund_order', AsyncMock()) as refund:
            await ui.start_refund(self.call, self.state)
            await ui.confirm_refund(self.call, self.state)
            find.assert_not_awaited(); refund.assert_not_awaited()

    async def test_old_confirmation_cannot_refund_another_order(self):
        self.call.data = 'adm_refund_confirm:6'
        with patch.object(ui, 'is_admin', return_value=True), patch.object(ui, 'answer_safe', AsyncMock()), \
             patch.object(ui, 'refund_order', AsyncMock()) as refund:
            await ui.confirm_refund(self.call, self.state)
            refund.assert_not_awaited()

    async def test_refunded_order_cannot_fetch_login_code(self):
        from services import telethon_code
        call = SimpleNamespace(data='get_code:5', from_user=SimpleNamespace(id=42, username='buyer'))
        with patch.object(shop, 'get_purchase_for_user', AsyncMock(return_value={'status': 'refunded'})), \
             patch.object(shop, 'answer_safe', AsyncMock()), \
             patch.object(telethon_code, 'try_fetch_login_code', AsyncMock()) as code:
            await shop.deliver_login_code(call)
            code.assert_not_awaited()

    def test_refund_status_has_priority_over_active_ticket(self):
        self.assertEqual(order_status({'status': 'refunded', 'ticket_status': 'open'}), 'Возвращён на баланс')
