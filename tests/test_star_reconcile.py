"""Offline Stars history recovery tests: no real credentials or Telegram calls."""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, patch

from test_payments import config
from services import star_reconcile as service

INVOICE = 'a' * 32


def transaction(index, *, direction='incoming', payload='sband_stars:' + INVOICE,
                amount=100, fraction=None, user=42, kind='invoice_payment'):
    partner = NS(type='user', transaction_type=kind, user=NS(id=user), invoice_payload=payload)
    return NS(id='charge-' + str(index), amount=amount, nanostar_amount=fraction,
              source=partner if direction == 'incoming' else None,
              receiver=partner if direction == 'refund' else None)


class EntryTests(unittest.TestCase):
    def test_only_this_bots_whole_star_invoice_payments_are_eligible(self):
        entry = service._entry(transaction(1), 'incoming')
        self.assertEqual((entry.user_id, entry.invoice_id, entry.stars, entry.charge_id), (42, INVOICE, 100, 'charge-1'))
        for options in ({'payload':'another-bot-invoice'}, {'amount':True}, {'amount':-100},
                        {'amount':0}, {'fraction':1}, {'kind':'paid_media_payment'}, {'user':True}):
            with self.subTest(options=options):
                self.assertIsNone(service._entry(transaction(1, **options), 'incoming'))

    def test_refund_id_may_equal_payment_id_but_direction_stays_distinct(self):
        incoming = service._entry(transaction(1), 'incoming')
        refund = service._entry(transaction(1, direction='refund'), 'refund')
        self.assertEqual(incoming.charge_id, refund.charge_id)
        self.assertEqual(refund.direction, 'refund')
        self.assertIsNone(service._entry(transaction(1), 'refund'))

    def test_payloadless_refund_requires_charge_correlation(self):
        self.assertIsNone(service._entry(transaction(1, direction='refund', payload=None), 'refund').invoice_id)
        self.assertIsNone(service._entry(transaction(1, payload=None), 'incoming'))


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = {}
        self.ledger = NS(credit_payment=AsyncMock(), refund_payment=AsyncMock(),
                         charge_info=AsyncMock(return_value=None), record_unmatched_refund=AsyncMock())
        async def get(key, default=''):
            return self.settings.get(key, default)
        async def put(key, value):
            self.settings[key] = value
        for patcher in (patch.object(service, '_store', return_value=self.ledger),
                        patch.object(service.db, 'get_setting', AsyncMock(side_effect=get)),
                        patch.object(service.db, 'set_setting', AsyncMock(side_effect=put))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def bot(self, items):
        async def read(offset, limit):
            return NS(transactions=items[offset:offset + limit])
        return NS(get_star_transactions=AsyncMock(side_effect=read))

    async def test_more_than_hundred_receipts_resume_across_batches_and_restart(self):
        bot = self.bot([transaction(i) for i in range(250)])
        result = await service.reconcile(bot, max_pages=2)
        self.assertEqual(result['offset'], 160)
        self.assertEqual(self.settings[service.CURSOR_KEY], '160')
        result = await service.reconcile(bot, max_pages=2)
        self.assertEqual(result['offset'], 0)
        recovered = {call.args[3] for call in self.ledger.credit_payment.call_args_list}
        self.assertEqual(recovered, {'charge-' + str(i) for i in range(250)})
        self.assertEqual([call.kwargs['offset'] for call in bot.get_star_transactions.call_args_list], [0, 80, 0, 160])

    async def test_database_outage_does_not_advance_failed_page(self):
        bot = self.bot([transaction(i) for i in range(250)])
        async def apply(user, invoice, stars, charge):
            if charge == 'charge-150':
                raise OSError('PRIVATE_DATABASE_DETAILS')
        self.ledger.credit_payment.side_effect = apply
        with self.assertRaises(OSError):
            await service.reconcile(bot, max_pages=3)
        self.assertEqual(self.settings[service.CURSOR_KEY], '80')
        self.ledger.credit_payment.side_effect = None
        await service.reconcile(bot, max_pages=3)
        self.assertIn('charge-249', {call.args[3] for call in self.ledger.credit_payment.call_args_list})

    async def test_api_outage_retains_existing_sweep_checkpoint(self):
        self.settings[service.CURSOR_KEY] = '800'
        bot = NS(get_star_transactions=AsyncMock(side_effect=OSError('network')))
        with self.assertRaises(OSError):
            await service.reconcile(bot)
        self.assertEqual(self.settings[service.CURSOR_KEY], '800')

    async def test_known_receipts_do_not_stop_history_scan_early(self):
        self.ledger.credit_payment.return_value = None
        result = await service.reconcile(self.bot([transaction(i) for i in range(220)]), max_pages=5)
        self.assertEqual(result['offset'], 0)
        self.assertIn('charge-219', {call.args[3] for call in self.ledger.credit_payment.call_args_list})

    async def test_unmatched_refund_tombstone_precedes_recovered_payment(self):
        order = []
        async def refund(*args): order.append('tombstone')
        async def credit(*args): order.append('credit')
        self.ledger.record_unmatched_refund.side_effect = refund
        self.ledger.credit_payment.side_effect = credit
        result = await service.reconcile(self.bot([transaction(1), transaction(1, direction='refund', payload=None)]))
        self.assertEqual(order, ['tombstone', 'credit'])
        self.assertEqual(result['unmatched_refunds'], 1)
        self.ledger.record_unmatched_refund.assert_awaited_once_with(42, 100, 'charge-1')

    async def test_known_payloadless_refund_checks_owner_and_amount(self):
        self.ledger.charge_info.return_value = {'invoice_id':INVOICE,'user_id':42,'stars':100}
        result = await service.reconcile(self.bot([transaction(1, direction='refund', payload=None)]))
        self.assertEqual(result['refunds'], 1)
        self.ledger.refund_payment.assert_awaited_once_with(None, 100, 'charge-1', user_id=42)

    async def test_refunds_with_payload_are_applied_before_same_page_payments(self):
        order = []
        async def refund(*args, **kwargs): order.append('refund')
        async def credit(*args): order.append('credit')
        self.ledger.refund_payment.side_effect = refund
        self.ledger.credit_payment.side_effect = credit
        await service.reconcile(self.bot([transaction(1),transaction(1,direction='refund')]))
        self.assertEqual(order,['refund','credit'])

    async def test_unrelated_and_fractional_transactions_never_reach_ledger(self):
        items = [transaction(1, payload='unrelated'), transaction(2, fraction=1), transaction(3, kind='gift_purchase')]
        result = await service.reconcile(self.bot(items))
        self.assertEqual((result['payments'], result['refunds']), (0, 0))
        self.ledger.credit_payment.assert_not_awaited()
        self.ledger.refund_payment.assert_not_awaited()

    async def test_validation_failure_does_not_hide_other_receipts_or_log_secrets(self):
        self.ledger.credit_payment.side_effect = [ValueError('PRIVATE_CHARGE_TOKEN'), None]
        with self.assertLogs(service.logger, level='WARNING') as logs:
            result = await service.reconcile(self.bot([transaction(1), transaction(2)]))
        self.assertEqual((result['rejected'], result['payments']), (1, 1))
        self.assertNotIn('PRIVATE_CHARGE_TOKEN', ''.join(logs.output))

    async def test_mismatched_payloadless_refund_cannot_debit_other_owner(self):
        self.ledger.charge_info.return_value = {'invoice_id':INVOICE,'user_id':99,'stars':100}
        with self.assertLogs(service.logger, level='WARNING'):
            result = await service.reconcile(self.bot([transaction(1, direction='refund', payload=None)]))
        self.assertEqual(result['rejected'], 1)
        self.ledger.refund_payment.assert_not_awaited()
        self.ledger.record_unmatched_refund.assert_not_awaited()
