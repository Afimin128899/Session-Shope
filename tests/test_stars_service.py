"""Offline native invoices, trusted-receipt replay and payment-event routing checks."""
import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from test_payments import config
from aiogram.types import Message
from database import stars as ledger
from handlers.user import stars as ui
from services import stars
from middlewares import subscription_middleware as subscription
from utils import maintenance, throttling

IDENTITY = 'a' * 32
PAYLOAD = 'sband_stars:' + IDENTITY
ROW = {'invoice_id': IDENTITY, 'stars': 100, 'amount': '120.00'}
EVENT = {'kind': 'paid', 'invoice_id': IDENTITY, 'stars': 100,
         'charge_id': 'telegram-private-charge', 'user_id': 42}


def payment_message(kind='successful_payment'):
    """Real aiogram model for middleware type checks, with fixture-only fields."""
    return Message.model_validate({
        'message_id': 1, 'date': datetime.now(timezone.utc),
        'chat': {'id': 42, 'type': 'private'},
        'from': {'id': 42, 'is_bot': False, 'first_name': 'Fixture'},
        kind: {'currency': 'XTR', 'total_amount': 100, 'invoice_payload': PAYLOAD,
               'telegram_payment_charge_id': EVENT['charge_id'], 'provider_payment_charge_id': ''},
    })


class NativeInvoiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_link_is_created_only_after_invoice_is_persisted(self):
        timeline = []
        async def register(user, count):
            timeline.append(('persist', user, count))
            return ROW
        async def telegram(**kwargs):
            timeline.append(('telegram', kwargs))
            return 'https://t.me/$fixture_invoice'
        bot = NS(create_invoice_link=AsyncMock(side_effect=telegram))
        with patch.object(ledger, 'register_invoice', AsyncMock(side_effect=register)):
            result = await stars.create_invoice(bot, 42, 100)
        self.assertEqual(timeline[0], ('persist', 42, 100))
        self.assertEqual(timeline[1][0], 'telegram')
        fields = timeline[1][1]
        self.assertEqual(fields['currency'], 'XTR')
        self.assertEqual(fields['provider_token'], '')
        self.assertEqual(fields['payload'], PAYLOAD)
        self.assertEqual(len(fields['prices']), 1)
        self.assertEqual(fields['prices'][0].amount, 100)
        self.assertEqual(result, {'provider': 'stars', 'invoice_id': IDENTITY,
                                 'pay_url': 'https://t.me/$fixture_invoice', 'amount': '120.00',
                                 'stars': 100, 'rate': '1.20', 'currency': 'XTR'})

    async def test_native_chat_invoice_uses_exact_stars_and_owner(self):
        bot = NS(send_invoice=AsyncMock())
        with patch.object(ledger, 'register_invoice', AsyncMock(return_value=ROW)) as persist:
            self.assertEqual(await stars.send_invoice(bot, 42, '100'), ROW)
        persist.assert_awaited_once_with(42, 100)
        kwargs = bot.send_invoice.call_args.kwargs
        self.assertEqual((kwargs['chat_id'], kwargs['currency'], kwargs['provider_token']), (42, 'XTR', ''))
        self.assertEqual([(p.label, p.amount) for p in kwargs['prices']], [('Пополнение баланса', 100)])
        self.assertEqual(kwargs['payload'], PAYLOAD)
        self.assertTrue(kwargs['start_parameter'])

    async def test_persistence_failure_never_opens_telegram_invoice(self):
        bot = NS(create_invoice_link=AsyncMock(), send_invoice=AsyncMock())
        with patch.object(ledger, 'register_invoice', AsyncMock(side_effect=OSError('DB unavailable'))):
            for operation in (stars.create_invoice, stars.send_invoice):
                with self.assertRaises(OSError): await operation(bot, 42, 100)
        bot.create_invoice_link.assert_not_awaited()
        bot.send_invoice.assert_not_awaited()

    async def test_invalid_or_fractional_count_never_calls_database_or_telegram(self):
        bot = NS(create_invoice_link=AsyncMock())
        with patch.object(ledger, 'register_invoice', AsyncMock()) as persist:
            for count in (True, 0, 10001, '1.5', 1.5, 'NaN', '١٠٠'):
                with self.assertRaises(ValueError): await stars.create_invoice(bot, 42, count)
        persist.assert_not_awaited()
        bot.create_invoice_link.assert_not_awaited()

    async def test_unexpected_invoice_link_is_not_returned_to_customer(self):
        with patch.object(ledger, 'register_invoice', AsyncMock(return_value=ROW)):
            for link in ('http://t.me/$fixture', 'https://evil.example/invoice', 'https://user:password@t.me/$fixture'):
                bot = NS(create_invoice_link=AsyncMock(return_value=link))
                with self.assertRaises(ValueError): await stars.create_invoice(bot, 42, 100)


class ReceiptDurabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='stars-service-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        patcher = patch.dict('os.environ', {'STARS_RECEIPTS_DIR': str(self.root)})
        patcher.start(); self.addCleanup(patcher.stop)

    def files(self):
        return list(self.root.glob('*.json'))

    async def test_receipt_is_durable_before_ledger_and_retained_on_database_failure(self):
        async def fail(*args):
            files = self.files()
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text()), EVENT)
            self.assertEqual(stat.S_IMODE(files[0].stat().st_mode), 0o600)
            self.assertNotIn(EVENT['charge_id'], files[0].name)
            raise OSError('DB temporarily unavailable')
        with patch.object(ledger, 'credit_payment', AsyncMock(side_effect=fail)):
            with self.assertRaises(OSError): await stars.accept(EVENT)
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(list(self.root.glob('.receipt-*')), [])

    async def test_replay_applies_same_event_and_removes_receipt_after_commit(self):
        stars.save_receipt(EVENT)
        bot = NS(send_message=AsyncMock())
        with patch.object(ledger, 'credit_payment', AsyncMock(return_value=Decimal('120.00'))) as credit:
            await stars.replay(bot)
        credit.assert_awaited_once_with(42, IDENTITY, 100, EVENT['charge_id'])
        self.assertEqual(self.files(), [])
        bot.send_message.assert_awaited_once()
        self.assertIn('120.00', bot.send_message.call_args.args[1])

    async def test_duplicate_receipts_delegate_to_idempotent_ledger_without_duplicate_notice(self):
        stars.save_receipt(EVENT)
        bot = NS(send_message=AsyncMock())
        with patch.object(ledger, 'credit_payment', AsyncMock(return_value=None)) as credit:
            await stars.replay(bot)
        credit.assert_awaited_once_with(42, IDENTITY, 100, EVENT['charge_id'])
        bot.send_message.assert_not_awaited()
        self.assertEqual(self.files(), [])

    async def test_failed_replay_keeps_receipt_without_logging_private_data(self):
        stars.save_receipt(EVENT)
        bot = NS(send_message=AsyncMock())
        with patch.object(ledger, 'credit_payment', AsyncMock(side_effect=OSError('PRIVATE_DATABASE_TOKEN'))):
            with self.assertLogs(stars.logger, level='WARNING') as logs:
                await stars.replay(bot)
        self.assertEqual(len(self.files()), 1)
        self.assertNotIn('PRIVATE_DATABASE_TOKEN', ''.join(logs.output))
        self.assertNotIn(EVENT['charge_id'], ''.join(logs.output))
        bot.send_message.assert_not_awaited()

    async def test_refund_receipt_uses_owner_bound_refund_ledger(self):
        refund = EVENT | {'kind': 'refunded'}
        with patch.object(ledger, 'refund_payment', AsyncMock(return_value=Decimal('120.00'))) as apply:
            result = await stars.accept(refund)
        apply.assert_awaited_once_with(IDENTITY, 100, EVENT['charge_id'], user_id=42)
        self.assertEqual(result, Decimal('120.00'))
        self.assertEqual(self.files(), [])


class NativeEventTests(unittest.IsolatedAsyncioTestCase):
    def query(self):
        return NS(from_user=NS(id=42), invoice_payload=PAYLOAD, currency='XTR', total_amount=100, answer=AsyncMock())

    async def test_precheckout_forwards_authenticated_payer_and_exact_invoice(self):
        query = self.query()
        with patch.object(ledger, 'check_precheckout', AsyncMock()) as check:
            await ui.pre_checkout(query)
        check.assert_awaited_once_with(42, PAYLOAD, 'XTR', 100)
        query.answer.assert_awaited_once_with(ok=True)

    async def test_precheckout_rejects_invalid_invoice_and_db_outage(self):
        for error in (ValueError('Счёт не совпадает'), OSError('PRIVATE_DATABASE_TOKEN')):
            with self.subTest(error=type(error).__name__):
                query = self.query()
                with patch.object(ledger, 'check_precheckout', AsyncMock(side_effect=error)):
                    await ui.pre_checkout(query)
                self.assertFalse(query.answer.call_args.kwargs['ok'])
                self.assertNotIn('PRIVATE_DATABASE_TOKEN', query.answer.call_args.kwargs['error_message'])
                query.answer.assert_awaited_once()

    async def test_native_duplicate_event_does_not_send_second_credit_message(self):
        model = payment_message()
        message = NS(successful_payment=model.successful_payment, refunded_payment=None,
                     from_user=NS(id=42), chat=NS(id=42, type='private'), answer=AsyncMock())
        with patch.object(stars, 'accept', AsyncMock(side_effect=[Decimal('120.00'), None])) as accept:
            await ui.receipt(message)
            await ui.receipt(message)
        self.assertEqual(accept.await_count, 2)
        self.assertEqual(accept.call_args.args[0], EVENT)
        message.answer.assert_awaited_once()
        self.assertIn('120.00', message.answer.call_args.args[0])

    async def test_untrusted_currency_group_or_mismatched_sender_does_not_reach_ledger(self):
        good = payment_message().successful_payment
        variants = [
            NS(successful_payment=good.model_copy(update={'currency':'RUB'}), refunded_payment=None, from_user=NS(id=42), chat=NS(id=42,type='private')),
            NS(successful_payment=good, refunded_payment=None, from_user=NS(id=42), chat=NS(id=42,type='group')),
            NS(successful_payment=good, refunded_payment=None, from_user=NS(id=43), chat=NS(id=42,type='private')),
        ]
        with patch.object(stars, 'accept', AsyncMock()) as accept:
            for message in variants: await ui.receipt(message)
        accept.assert_not_awaited()

    async def test_payment_receipts_bypass_maintenance_subscription_and_throttle(self):
        for kind in ('successful_payment', 'refunded_payment'):
            with self.subTest(kind=kind):
                message = payment_message(kind)
                handler = AsyncMock(return_value='received')
                with patch.object(maintenance, 'is_maintenance', AsyncMock(side_effect=AssertionError('Must bypass maintenance'))) as check:
                    self.assertEqual(await maintenance.MaintenanceMiddleware()(handler,message,{}),'received')
                check.assert_not_awaited()
                with patch.object(subscription, 'is_user_subscribed', AsyncMock(side_effect=AssertionError('Must bypass subscription'))) as check:
                    self.assertEqual(await subscription.SubscriptionMiddleware()(handler,message,{'bot':object()}),'received')
                check.assert_not_awaited()
                limiter = throttling.ThrottlingMiddleware()
                limiter.last_request[42] = 100
                with patch.object(throttling.time, 'monotonic', side_effect=AssertionError('Must bypass throttle')):
                    self.assertEqual(await limiter(handler,message,{}),'received')
                self.assertEqual(limiter.last_request[42],100)
                self.assertEqual(handler.await_count,3)
