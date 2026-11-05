"""Offline financial checks. All credentials/configuration come from local fixtures."""
import asyncio
from decimal import Decimal
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import db
from database import stars, admin_tools

IDENTITY='a'*32
INVOICE={'invoice_id':IDENTITY,'user_id':42,'stars_count':100,'amount_rub':Decimal('120.00'),'status':'pending','expired':False}
PAYMENT={'invoice_id':IDENTITY,'user_id':42,'stars':100,'amount_rub':Decimal('120.00'),'paid_seen':1,'refunded_seen':0,'credited_amount':Decimal('120.00')}


class ParsingTests(unittest.TestCase):
    def test_star_count_is_integral_bounded_and_exact(self):
        self.assertEqual(stars.parse_count('100'),100)
        self.assertEqual(stars.parse_count(1)*stars.STARS_RATE,Decimal('1.20'))
        for value in (True,0,-1,10001,1.0,'1.0','1e2','١٠٠','1'*100,None):
            with self.subTest(value=value),self.assertRaises(ValueError):stars.parse_count(value)

    def test_only_our_opaque_payload_is_accepted(self):
        self.assertEqual(stars.invoice_id('sband_stars:'+IDENTITY),IDENTITY)
        for payload in ('stars:'+IDENTITY,'sband_stars:42','sband_stars:'+'A'*32,'x'*500,None):
            with self.assertRaises(ValueError):stars.invoice_id(payload)


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cur=MagicMock(execute=AsyncMock(),fetchone=AsyncMock(),fetchall=AsyncMock())
        self.conn=MagicMock(begin=AsyncMock(),commit=AsyncMock(),rollback=AsyncMock())
        self.conn.cursor.return_value.__aenter__.return_value=self.cur
        pool=MagicMock();pool.acquire.return_value.__aenter__.return_value=self.conn
        patcher=patch.object(admin_tools,'_get_pool',return_value=pool)
        patcher.start();self.addCleanup(patcher.stop)
        from database import referrals
        for name in ('lock_participants','credit_deposit','reverse_deposit'):
            reward_patch=patch.object(referrals,name,AsyncMock(return_value=None))
            reward_patch.start();self.addCleanup(reward_patch.stop)

    async def test_credit_has_exact_rate_no_first_bonus_or_bonus_flag_consumption(self):
        self.cur.fetchone.side_effect=[INVOICE,None,{'balance':Decimal('3')},{'total':Decimal('120'),'refunded':0}]
        self.assertEqual(await stars.credit_payment(42,IDENTITY,100,'charge-1'),Decimal('120'))
        calls=self.cur.execute.call_args_list
        user_update=next(c for c in calls if c.args[0].startswith('UPDATE users'))
        self.assertEqual(user_update.args[1],(Decimal('123'),42))
        log=next(c for c in calls if c.args[0].startswith('INSERT INTO payment_logs'))
        self.assertEqual(log.args[1],(42,Decimal('120'),'stars_pay','charge-1'))
        self.assertFalse(any('first_deposit_bonus_used' in c.args[0] for c in calls))
        self.conn.commit.assert_awaited_once()

    async def test_duplicate_paid_charge_does_not_mutate_funds(self):
        self.cur.fetchone.side_effect=[INVOICE,PAYMENT]
        self.assertIsNone(await stars.credit_payment(42,IDENTITY,100,'charge-1'))
        self.assertEqual(self.cur.execute.await_count,2)

    async def test_actual_paid_receipt_is_honored_after_invoice_expiry(self):
        self.cur.fetchone.side_effect=[INVOICE|{'status':'expired','expired':True},None,{'balance':0},{'total':120,'refunded':0}]
        self.assertEqual(await stars.credit_payment(42,IDENTITY,100,'late-charge'),Decimal('120'))

    async def test_wrong_invoice_owner_count_or_rate_never_reaches_balance(self):
        for changed in ({'user_id':43},{'stars_count':101},{'amount_rub':121}):
            self.cur.fetchone.return_value=INVOICE|changed
            with self.assertRaises(ValueError):await stars.credit_payment(42,IDENTITY,100,'charge-1')
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_charge_cannot_be_reused_for_another_owner_or_invoice(self):
        self.cur.fetchone.side_effect=[INVOICE,PAYMENT|{'user_id':43}]
        with self.assertRaises(ValueError):await stars.credit_payment(42,IDENTITY,100,'charge-1')
        self.conn.rollback.assert_awaited_once()

    async def test_credit_log_failure_rolls_back_charge_marker_and_balance(self):
        self.cur.fetchone.side_effect=[INVOICE,None,{'balance':0}]
        async def execute(sql,args=()):
            if sql.startswith('INSERT INTO payment_logs'):raise OSError('fixture failure')
        self.cur.execute.side_effect=execute
        with self.assertRaises(OSError):await stars.credit_payment(42,IDENTITY,100,'charge-1')
        self.conn.rollback.assert_awaited_once();self.conn.commit.assert_not_awaited()

    async def test_cancellation_rolls_back(self):
        self.cur.execute.side_effect=asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):await stars.credit_payment(42,IDENTITY,100,'charge-1')
        self.conn.rollback.assert_awaited_once()

    async def test_refund_reverses_only_once_even_if_credit_was_spent(self):
        self.cur.fetchone.side_effect=[INVOICE,PAYMENT,{'balance':10},{'total':0,'refunded':1}]
        self.assertEqual(await stars.refund_payment(IDENTITY,100,'charge-1',user_id=42),Decimal(120))
        update=next(c for c in self.cur.execute.call_args_list if c.args[0].startswith('UPDATE users'))
        self.assertEqual(update.args[1],(Decimal(-110),42))
        self.cur.reset_mock();self.cur.fetchone.side_effect=[INVOICE,PAYMENT|{'refunded_seen':1,'credited_amount':0}]
        self.assertIsNone(await stars.refund_payment(IDENTITY,100,'charge-1'))
        self.assertEqual(self.cur.execute.await_count,2)

    async def test_refund_before_paid_creates_zero_credit_tombstone(self):
        self.cur.fetchone.side_effect=[INVOICE,None,{'total':0,'refunded':1}]
        self.assertIsNone(await stars.refund_payment(IDENTITY,100,'charge-1'))
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))
        self.assertTrue(any('INSERT INTO star_payments' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_paid_after_unmatched_refund_binds_invoice_without_credit(self):
        self.cur.fetchone.side_effect=[INVOICE,PAYMENT|{'invoice_id':None,'paid_seen':0,'refunded_seen':1,'credited_amount':0},{'total':0,'refunded':1}]
        self.assertIsNone(await stars.credit_payment(42,IDENTITY,100,'charge-1'))
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))
        binding=next(c for c in self.cur.execute.call_args_list if c.args[0].startswith('UPDATE star_payments'))
        self.assertEqual(binding.args[1],(IDENTITY,'charge-1'))

    async def test_unknown_refund_is_recorded_for_known_user_without_balance_change(self):
        self.cur.fetchone.side_effect=[None,{'id':42}]
        self.assertIsNone(await stars.record_unmatched_refund(42,100,'charge-1'))
        self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))
        insert=next(c for c in self.cur.execute.call_args_list if 'INSERT INTO star_payments' in c.args[0])
        self.assertEqual(insert.args[1],('charge-1',42,100,Decimal(120)))

    async def test_unknown_user_refund_does_not_create_ledger_entry(self):
        self.cur.fetchone.side_effect=[None,None]
        await stars.record_unmatched_refund(43,100,'charge-unknown')
        self.assertFalse(any('INSERT INTO star_payments' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_unmatched_refund_that_races_with_paid_receipt_uses_normal_refund(self):
        self.cur.fetchone.return_value=PAYMENT
        with patch.object(stars,'refund_payment',AsyncMock(return_value=Decimal(120))) as refund:
            self.assertEqual(await stars.record_unmatched_refund(42,100,'charge-1'),Decimal(120))
        refund.assert_awaited_once_with(IDENTITY,100,'charge-1',user_id=42)
        self.conn.commit.assert_awaited_once()

    async def test_precheckout_rejects_expiry_prior_payment_currency_and_wrong_payer(self):
        for changed in ({'expired':True},{'status':'credited'},{'status':'refunded'},{'user_id':43}):
            self.cur.fetchone.return_value=INVOICE|changed
            with self.assertRaises(ValueError):await stars.check_precheckout(42,'sband_stars:'+IDENTITY,'XTR',100)
        with self.assertRaises(ValueError):await stars.check_precheckout(42,'sband_stars:'+IDENTITY,'RUB',100)

    async def test_precheckout_accepts_only_exact_owner_and_count(self):
        self.cur.fetchone.return_value=INVOICE
        result=await stars.check_precheckout(42,'sband_stars:'+IDENTITY,'XTR',100)
        self.assertEqual(result,{'invoice_id':IDENTITY,'stars':100,'amount':'120.00'})
