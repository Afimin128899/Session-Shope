"""Offline referral configuration/ledger and blocked official SpamBot contracts."""
from decimal import Decimal
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from test_payments import config
import test_miniapp
import test_spam_checks
from database import referrals, admin_web, spam_checks
from handlers.admin import referrals as admin_ui
from services import spam_check
from telethon.errors import YouBlockedUserError, FloodWaitError
from telethon.tl.functions.contacts import UnblockRequest


class ReferralRulesTests(unittest.TestCase):
    def test_zero_disables_rewards_and_fractions_are_retained(self):
        values=referrals.validate_settings({'referral_signup_bonus':'0','referral_deposit_pct':'7.25','referral_purchase_pct':'100','referral_discount_pct':'0'})
        self.assertEqual(values['referral_deposit_pct'],Decimal('7.25'))
        self.assertEqual(values['referral_signup_bonus'],0)

    def test_invalid_admin_rates_and_rewards_are_rejected(self):
        for key,value in [('referral_deposit_pct','100.01'),('referral_purchase_pct','-1'),('referral_signup_bonus','10000.01'),('referral_signup_bonus','NaN'),('referral_discount_pct',True),('referral_deposit_pct','0.001'),('referral_deposit_pct','Infinity')]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):referrals.validate_settings({key:value})


class ReferralLedgerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        async def allocate(cur,user,amount,values):return amount,None,referrals.reward_day()
        p=patch.object(referrals,'allocation',side_effect=allocate);p.start();self.addCleanup(p.stop)
    def cursor(self,found=None,rowcount=1):
        return NS(execute=AsyncMock(),fetchone=AsyncMock(return_value=found),fetchall=AsyncMock(),rowcount=rowcount)

    async def test_percent_applies_to_principal_and_snapshot_is_recorded_once(self):
        cur=self.cursor({'discount_pct':5,'bonus_pct':5,'signup_bonus':3,'deposit_pct':'5.25'})
        self.assertEqual(await referrals.credit_deposit(cur,100,43,Decimal('100'),'crypto','invoice-1'),Decimal('5.25'))
        insert=next(c for c in cur.execute.call_args_list if 'INSERT IGNORE INTO referral_rewards' in c.args[0])
        self.assertEqual(insert.args[1][6:9],(Decimal(100),Decimal('5.25'),Decimal('5.25')))
        credit=next(c for c in cur.execute.call_args_list if 'UPDATE users' in c.args[0])
        self.assertEqual(credit.args[1],(Decimal('5.25'),43))

    async def test_duplicate_reward_never_credits_or_logs_money(self):
        cur=self.cursor({'discount_pct':5,'bonus_pct':5,'signup_bonus':3,'deposit_pct':5},rowcount=0)
        self.assertIsNone(await referrals.credit_deposit(cur,100,43,100,'crypto','invoice-1'))
        self.assertFalse(any('UPDATE users' in c.args[0] or 'INSERT INTO payment_logs' in c.args[0] for c in cur.execute.call_args_list))

    async def test_no_referrer_does_not_create_a_wallet_reward(self):
        cur=self.cursor()
        self.assertIsNone(await referrals.credit_deposit(cur,100,None,100,'crypto','invoice-1'))
        cur.execute.assert_not_awaited()

    async def test_reversal_uses_original_reward_not_current_percent(self):
        cur=self.cursor({'user_id':100,'referrer_id':43,'amount':'5.25','reversed':0})
        with patch.object(referrals,'read_settings',AsyncMock(side_effect=AssertionError('Must not reprice old rewards'))):
            self.assertEqual(await referrals.reverse_deposit(cur,100,'stars','charge-1'),Decimal('5.25'))
        self.assertEqual(next(c for c in cur.execute.call_args_list if 'UPDATE users' in c.args[0]).args[1],(Decimal('5.25'),43))
        cur.fetchone.return_value['reversed']=1;cur.execute.reset_mock()
        self.assertIsNone(await referrals.reverse_deposit(cur,100,'stars','charge-1'))
        self.assertEqual(cur.execute.await_count,1)

    async def test_wallet_locks_are_sorted_including_a_lower_referrer_id(self):
        cur=self.cursor({'referrer_id':43});cur.fetchall.return_value=[{'id':43},{'id':100}]
        self.assertEqual(await referrals.lock_participants(cur,100),43)
        self.assertEqual(cur.execute.call_args.args[1],(43,100))
        self.assertIn('ORDER BY id FOR UPDATE',cur.execute.call_args.args[0])


class ReferralAccessTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_customer_can_only_read_their_own_referral_summary(self):
        with patch.object(referrals,'summary',AsyncMock(return_value={'count':0,'earned':'0','settings':{}})) as get,patch.object(referrals,'invited',AsyncMock(return_value={'items':[],'has_more':False})) as listing:
            response=await self.client.get('/api/referrals?user_id=99',headers=self.headers)
            self.assertEqual(response.status,200);get.assert_awaited_once_with(42);listing.assert_awaited_once_with(42,0)

    async def test_customer_cannot_change_rewards_by_spoofing_admin_id(self):
        with patch.object(config,'ADMIN_IDS',[7]),patch.object(admin_web,'save_settings',AsyncMock()) as save:
            response=await self.client.post('/api/admin/settings',headers=self.headers,json={'referral_signup_bonus':'10000','admin_id':7})
            self.assertEqual(response.status,403);save.assert_not_awaited()

    async def test_live_spam_status_uses_authenticated_owner_and_bounded_ids(self):
        with patch.object(spam_checks,'catalog_status',AsyncMock(return_value=[])) as read:
            response=await self.client.get('/api/spam-status?ids=1,2&user_id=99',headers=self.headers)
            self.assertEqual(response.status,200);read.assert_awaited_once_with(42,[1,2])
            for value in ('','1,1','1,-2','1e3',','.join(str(i) for i in range(1,52))):
                response=await self.client.get('/api/spam-status',params={'ids':value},headers=self.headers)
                self.assertEqual(response.status,400)
            self.assertEqual(read.await_count,1)

    async def test_bot_settings_reject_non_admin_before_reading_fsm_or_wallets(self):
        call=NS(from_user=NS(id=999),data='admin_referral_field:referral_signup_bonus')
        state=NS(clear=AsyncMock(),get_data=AsyncMock(),set_state=AsyncMock())
        with patch.object(admin_ui,'is_admin',return_value=False),patch.object(admin_ui,'answer_safe',AsyncMock()),patch.object(referrals,'settings',AsyncMock()) as read,patch.object(admin_web,'save_settings',AsyncMock()) as save:
            await admin_ui.show(call,state);await admin_ui.choose(call,state)
            await admin_ui.save(NS(from_user=NS(id=999)),state)
            read.assert_not_awaited();save.assert_not_awaited();state.get_data.assert_not_awaited()


class RPCClient(NS):
    async def __call__(self,request):return await self.rpc(request)


class BlockedSpamBotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        test_spam_checks.ConversationTests.setUp(self)
        self.client=RPCClient(**vars(self.client),rpc=AsyncMock())
        spam_check.create_client.return_value=self.client
    check=test_spam_checks.ConversationTests.check

    async def test_blocked_official_bot_is_unblocked_then_a_fresh_start_is_verified(self):
        self.dialog.send_message.side_effect=[YouBlockedUserError(request=None),self.sent]
        result=await self.check()
        self.assertEqual(result['status'],'clear')
        self.assertEqual(self.dialog.send_message.await_count,2)
        request=self.client.rpc.call_args.args[0]
        self.assertIsInstance(request,UnblockRequest)
        self.assertIs(request.id,self.client.get_entity.return_value)
        self.dialog.get_response.assert_awaited_once_with(self.sent)
        self.client.disconnect.assert_awaited_once()

    async def test_wrong_peer_never_gets_unblocked(self):
        self.client.get_entity.return_value.username='OtherBot'
        self.assertEqual((await self.check())['reason'],'wrong_peer')
        self.client.rpc.assert_not_awaited();self.dialog.send_message.assert_not_awaited()

    async def test_unblock_flood_wait_is_reported_without_retrying_or_claiming_clear(self):
        self.dialog.send_message.side_effect=YouBlockedUserError(request=None)
        self.client.rpc.side_effect=FloodWaitError(request=None,capture=1800)
        result=await self.check()
        self.assertEqual(result,{'status':'error','reason':'flood_wait','retry_after':1800})
        self.dialog.send_message.assert_not_awaited()
        self.dialog.get_response.assert_not_awaited()


class DailyAllocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_allowance_can_only_pay_the_actual_remainder(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(side_effect=[None,{'issued':'29.25'}]))
        paid,reason,day=await referrals.allocation(cur,43,Decimal('5'),{'daily_limit':Decimal(30)})
        self.assertEqual((paid,reason),(Decimal('.75'),'daily_limit'))
        self.assertEqual(day,referrals.reward_day())
        self.assertIn('FOR UPDATE',cur.execute.call_args.args[0])

    async def test_blocked_recipient_receives_zero_without_touching_daily_allowance(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value={'blocked':1}))
        paid,reason,_=await referrals.allocation(cur,43,Decimal(3),{'daily_limit':Decimal(30)})
        self.assertEqual((paid,reason),(0,'blocked'))
        self.assertEqual(cur.execute.await_count,1)

    async def test_invalid_blacklist_id_never_starts_a_transaction(self):
        for value in [True,0,-1,'123',123.0,9223372036854775808]:
            with self.assertRaises(ValueError):await referrals.set_block(42,value,True)


class PendingReferralTests(unittest.IsolatedAsyncioTestCase):
    async def test_referral_survives_subscription_prompt_and_is_completed_for_the_verified_user(self):
        from utils.referral_link import remember,complete
        from test_payments import db
        values={}
        async def update(**kwargs):values.update(kwargs)
        state=NS(get_data=AsyncMock(side_effect=lambda:dict(values)),update_data=AsyncMock(side_effect=update))
        user=NS(id=100,username='verified_buyer')
        await remember(NS(text='/start ref_43',from_user=user),state)
        await remember(NS(text='/start ref_44',from_user=user),state)
        self.assertEqual(values['pending_referrer'],43)
        with patch.object(db,'create_user_with_referrer',AsyncMock()) as register:
            await complete(user,state)
            register.assert_awaited_once_with(100,43,'verified_buyer')
        self.assertIsNone(values['pending_referrer'])
