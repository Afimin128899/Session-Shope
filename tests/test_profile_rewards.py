import unittest
from datetime import datetime,timezone
from decimal import Decimal
from unittest.mock import AsyncMock,patch
from test_payments import db
import test_miniapp
from database import rewards,coupons
from miniapp import storage
from handlers.user import shop
from types import SimpleNamespace as NS


class RewardTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_miniapp.CheckoutTests.setUp

    async def test_reward_is_atomic_and_does_not_unlock_itself(self):
        self.cur.fetchone.side_effect=[{'balance':Decimal(100)},None,{'total':Decimal(50)},{'total':0}]
        with patch.object(rewards.secrets,'randbelow',return_value=8):
            result=await rewards.claim(42)
        self.assertEqual(result,{'amount':'9','balance':'109'})
        self.conn.commit.assert_awaited_once()
        sql=' '.join(c.args[0] for c in self.cur.execute.call_args_list)
        self.assertNotIn('INSERT INTO payment_logs',sql)
        self.assertNotIn('first_deposit_bonus_used',sql)
        self.assertIn('INSERT INTO reward_claims',sql)

    async def test_low_paid_amount_or_recent_claim_cannot_credit(self):
        for last,paid in [(None,'49.99'),({'created_at':datetime.now(timezone.utc).replace(tzinfo=None)},'100')]:
            self.cur.reset_mock()
            self.cur.fetchone.side_effect=[{'balance':100},last,{'total':Decimal(paid)},{'total':0}]
            with self.assertRaises(ValueError): await rewards.claim(42)
            self.assertFalse(any('UPDATE users' in c.args[0] for c in self.cur.execute.call_args_list))

    async def test_failure_rolls_back_reward_marker_and_credit(self):
        self.cur.fetchone.side_effect=[{'balance':100},None,{'total':50},{'total':0}]
        async def execute(sql,*args):
            if 'admin_audit_log' in sql: raise OSError('audit unavailable')
        self.cur.execute.side_effect=execute
        with self.assertRaises(OSError): await rewards.claim(42)
        self.conn.rollback.assert_awaited_once()
        self.conn.commit.assert_not_awaited()


class PurchaseCouponTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_miniapp.CheckoutTests.setUp

    async def test_discount_consumed_only_with_successful_purchase(self):
        self.cur.fetchone.side_effect=[{'id':1,'price':100,'country':'us'},None,None]
        self.cur.fetchall.return_value=[{'id':42,'balance':500}]
        promo={'code':'SALE','kind':'discount','value':10}
        with patch.object(coupons,'validate',AsyncMock(return_value=promo)),patch.object(coupons,'consume',AsyncMock()) as consume:
            result=await storage.checkout(42,1,Decimal(100),promo_code='SALE',expected_total=Decimal(90))
        self.assertEqual(result['paid_amount'],'90.00')
        consume.assert_awaited_once_with(self.cur,42,promo)
        self.conn.commit.assert_awaited_once()

    async def test_changed_discount_or_insufficient_funds_does_not_spend_code(self):
        for expected,balance in [(Decimal(91),500),(Decimal(90),5)]:
            self.cur.fetchone.side_effect=[{'id':1,'price':100,'country':'us'},None,None]
            self.cur.fetchall.return_value=[{'id':42,'balance':balance}]
            with patch.object(coupons,'validate',AsyncMock(return_value={'code':'SALE','kind':'discount','value':10})),patch.object(coupons,'consume',AsyncMock()) as consume:
                with self.assertRaises(storage.CheckoutError): await storage.checkout(42,1,Decimal(100),promo_code='SALE',expected_total=expected)
                consume.assert_not_awaited()

    async def test_invalid_purchase_code_keeps_input(self):
        message=NS(from_user=NS(id=42),text='BAD',answer=AsyncMock())
        state=NS(get_data=AsyncMock(return_value={'promo_account_id':1}),clear=AsyncMock())
        with patch.object(coupons,'preview',AsyncMock(side_effect=ValueError('Код не найден'))):
            await shop.enter_purchase_promo(message,state)
        state.clear.assert_not_awaited()
        self.assertIn('другой код',message.answer.call_args.args[0])


class RewardsAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_reward_always_uses_signed_owner(self):
        with patch.object(rewards,'claim',AsyncMock(return_value={'amount':'3','balance':'103'})) as claim:
            response=await self.client.post('/api/rewards/claim',headers=self.headers,json={'user_id':99})
            self.assertEqual(response.status,200)
            claim.assert_awaited_once_with(42)
        self.assertEqual((await self.client.post('/api/rewards/claim',json={})).status,401)
