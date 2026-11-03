"""Offline regression tests; never connect to Telegram or a configured database."""
import asyncio
import importlib
import sys
import types
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

# Import application modules without reading the repository's real credentials.
config = types.ModuleType('config')
for name in ('LAVE_PAY_API_KEY', 'XROCKET_API_KEY', 'CRYPTO_PAY_TOKEN',
             'TONKEEPER_WALLET', 'RUB_DETAILS', 'REVIEWS_LINK', 'SUPPORT_USERNAME',
             'BOT_TOKEN', 'TELEGRAM_API_HASH'):
    setattr(config, name, '')
config.DB_CONFIG = {}
config.ADMIN_IDS = []
config.TELEGRAM_API_ID = 0
config.USDT_RUB_RATE = 100.0
config.TON_FALLBACK_RATE = config.USDT_FALLBACK_RATE = 1.0
sys.modules['config'] = config
db = importlib.import_module('database.db')
balance = importlib.import_module('handlers.user.balance')
shop = importlib.import_module('handlers.user.shop')


class PaymentTransactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur = MagicMock()
        self.cur.execute = AsyncMock()
        self.cur.fetchone = AsyncMock(return_value=(0,))
        self.conn = MagicMock()
        self.conn.begin = AsyncMock()
        self.conn.commit = AsyncMock()
        self.conn.rollback = AsyncMock()
        self.conn.cursor.return_value.__aenter__.return_value = self.cur
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__.return_value = self.conn
        self.patch = patch.object(db, '_get_pool', return_value=self.pool)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_first_deposit_bonus_and_payment_log_commit_together(self):
        self.assertEqual(await db.credit_paid_deposit(42, '100.10', 'crypto', '123'), (110.11, 10.01))
        calls = self.cur.execute.call_args_list
        self.assertIn('FOR UPDATE', calls[1].args[0])
        self.assertEqual(calls[2].args[1], (Decimal('110.11'), 42))
        self.assertEqual(calls[3].args[1], (42, Decimal('100.10'), 'RUB', 'crypto_pay', '123'))
        self.conn.begin.assert_awaited_once()
        self.conn.commit.assert_awaited_once()
        self.conn.rollback.assert_not_awaited()

    async def test_later_deposit_has_no_bonus(self):
        self.cur.fetchone.return_value = (1,)
        self.assertEqual(await db.credit_paid_deposit(42, '100', 'lave', '123'), (100, 0))

    async def test_duplicate_never_changes_balance(self):
        self.cur.execute.side_effect = db.aiomysql.IntegrityError(1062, 'duplicate')
        self.assertIsNone(await db.credit_paid_deposit(42, 100, 'xrocket', '123'))
        self.assertEqual(self.cur.execute.await_count, 1)
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_failed_log_rolls_back_and_allows_retry(self):
        self.cur.execute.side_effect = [None, None, None, RuntimeError('log failed')]
        with self.assertRaises(RuntimeError):
            await db.credit_paid_deposit(42, 100, 'crypto', '123')
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()
        self.cur.execute.side_effect = None
        self.assertEqual(await db.credit_paid_deposit(42, 100, 'crypto', '123'), (110, 10))
        self.conn.commit.assert_awaited_once()

    async def test_missing_user_rolls_back_payment_marker(self):
        self.cur.fetchone.return_value = None
        with self.assertRaises(ValueError):
            await db.credit_paid_deposit(42, 100, 'crypto', '123')
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_cancellation_rolls_back(self):
        self.cur.execute.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await db.credit_paid_deposit(42, 100, 'crypto', '123')
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()

    async def test_invalid_amounts_never_start_transaction(self):
        for amount in ('NaN', 'Infinity', '-Infinity', 'bad', '0', '-10', '9.99', '1000000.01'):
            with self.subTest(amount=amount), self.assertRaises(ValueError):
                await db.credit_paid_deposit(42, amount, 'crypto', '123')
        self.conn.begin.assert_not_awaited()


class PaymentHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_payment_check_uses_signed_owner_and_shared_service(self):
        call = SimpleNamespace(data='crypto_check:123', from_user=SimpleNamespace(id=42))
        with patch.object(balance.payments, 'check_invoice', AsyncMock(return_value={'status':'credited','credited':None})) as check, \
             patch.object(balance, 'answer_safe', AsyncMock()) as answer, \
             patch.object(balance, 'edit_message_safe', AsyncMock()) as edit:
            await balance.check_payment(call)
            check.assert_awaited_once_with(42, 'crypto', '123')
            edit.assert_not_awaited()
            self.assertIn('уже зачислен', answer.call_args.args[1])

    async def test_nan_input_never_creates_invoice(self):
        message = SimpleNamespace(text='nan', answer=AsyncMock())
        state = SimpleNamespace(get_data=AsyncMock())
        await balance.process_lave_amount(message, state)
        state.get_data.assert_not_awaited()
        message.answer.assert_awaited_once()

    async def test_legacy_confirmation_opens_fresh_quote_without_debit(self):
        call = SimpleNamespace(data='confirm_buy_acc:8', from_user=SimpleNamespace(id=42))
        state = SimpleNamespace(get_data=AsyncMock(return_value={}))
        with patch.object(shop, 'show_product', AsyncMock()) as preview, \
             patch.object(shop, 'checkout', AsyncMock()) as buy:
            await shop.confirm_purchase(call, state)
            preview.assert_awaited_once_with(call, state, 8)
            buy.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
