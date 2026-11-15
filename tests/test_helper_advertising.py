"""Helper ACL, campaign ownership and atomic acquisition without referral payouts."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager
from decimal import Decimal
from test_payments import db,config
import test_miniapp
from database import advertising as ads,referrals,welcome
from utils import referral_link

TOKEN='a'*22


class AdvertisingAPITests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=test_miniapp.MiniAppAPITests.asyncSetUp
    asyncTearDown=test_miniapp.MiniAppAPITests.asyncTearDown

    async def test_helper_identity_is_not_full_admin(self):
        with patch.object(db,'get_user',AsyncMock(return_value={'is_helper':1})),patch.object(config,'ADMIN_IDS',[99]):
            r=await self.client.get('/api/admin/identity',headers=self.headers)
            self.assertEqual(r.status,200);data=await r.json()
            self.assertTrue(data['is_helper']);self.assertFalse(data['is_admin'])

    async def test_helper_cannot_use_owner_apis_even_with_forged_body(self):
        with patch.object(db,'get_user',AsyncMock(return_value={'is_helper':1})),patch.object(config,'ADMIN_IDS',[99]):
            for method,path in [('GET','overview'),('GET','users'),('POST','users/43/balance'),('GET','users/43/referrals'),('POST','stock/bulk'),('POST','app-access'),('GET','helpers'),('POST','helpers'),('GET','imports'),('GET','settings')]:
                with self.subTest(path=path,method=method):
                    r=await self.client.request(method,'/api/admin/'+path,headers=self.headers,json={'is_admin':True,'owner_id':99})
                    self.assertEqual(r.status,403,await r.text())

    async def test_campaign_owner_is_signed_user_not_request_body(self):
        with patch.object(db,'get_user',AsyncMock(return_value={'is_helper':1})),patch.object(config,'ADMIN_IDS',[99]),patch.object(ads,'create_campaign',AsyncMock(return_value={'id':7,'token':TOKEN})) as create:
            r=await self.client.post('/api/admin/advertising',headers=self.headers,json={'name':'Канал','owner_id':43})
            self.assertEqual(r.status,201);create.assert_awaited_once_with(42,'Канал')

    async def test_foreign_campaign_is_not_found(self):
        with patch.object(db,'get_user',AsyncMock(return_value={'is_helper':1})),patch.object(config,'ADMIN_IDS',[99]),patch.object(ads,'rows',AsyncMock(return_value=[])) as rows:
            r=await self.client.get('/api/admin/advertising/7/users?owner_id=43',headers=self.headers)
            self.assertEqual(r.status,404)
            self.assertEqual(rows.call_args.args[1],(7,42))

    async def test_ordinary_users_and_owner_do_not_get_advertising_section(self):
        for profile,admins in [({},[99]),({'is_helper':1},[42])]:
            with patch.object(db,'get_user',AsyncMock(return_value=profile)),patch.object(config,'ADMIN_IDS',admins):
                r=await self.client.get('/api/admin/advertising',headers=self.headers)
                self.assertEqual(r.status,403)
        self.assertEqual((await self.client.get('/api/admin/advertising')).status,401)

    async def test_role_revocation_closes_stale_session(self):
        profile={'is_helper':1}
        with patch.object(db,'get_user',AsyncMock(side_effect=lambda _:dict(profile))),patch.object(config,'ADMIN_IDS',[99]),patch.object(ads,'campaigns',AsyncMock(return_value=[])) as campaigns:
            self.assertEqual((await self.client.get('/api/admin/advertising',headers=self.headers)).status,200)
            profile['is_helper']=0
            self.assertEqual((await self.client.get('/api/admin/advertising',headers=self.headers)).status,403)
            self.assertEqual(campaigns.await_count,1)

    async def test_only_owner_can_assign_helper(self):
        with patch.object(config,'ADMIN_IDS',[99]),patch.object(ads,'_transaction') as transaction:
            with self.assertRaises(PermissionError):await ads.set_helper(42,43,True)
            transaction.assert_not_called()
        with patch.object(config,'ADMIN_IDS',[42]),patch.object(ads,'set_helper',AsyncMock()) as assign,patch.object(ads,'helpers',AsyncMock(return_value=[])):
            r=await self.client.post('/api/admin/helpers',headers=self.headers,json={'user_id':43,'enabled':True})
            self.assertEqual(r.status,200);assign.assert_awaited_once_with(42,43,True)


class RegistrationTests(unittest.IsolatedAsyncioTestCase):
    setUp=test_miniapp.CheckoutTests.setUp

    async def test_new_ad_signup_never_creates_personal_referral_or_payout(self):
        self.cur.rowcount=1
        with patch.object(ads,'attribute_new_user',AsyncMock()) as attach,patch.object(welcome,'credit_new_user',AsyncMock(return_value=Decimal(0))),patch.object(referrals,'_award',AsyncMock()) as award:
            await referrals.register_user(42,43,'customer',ad_token=TOKEN)
            attach.assert_awaited_once_with(self.cur,42,TOKEN);award.assert_not_awaited()
            self.assertFalse(any('INSERT INTO referrals' in call.args[0] for call in self.cur.execute.call_args_list))
        self.conn.commit.assert_awaited_once()

    async def test_existing_user_is_never_backfilled_or_counted_again(self):
        self.cur.rowcount=0
        with patch.object(ads,'attribute_new_user',AsyncMock()) as attach:
            self.assertEqual(await referrals.register_user(42,None,ad_token=TOKEN),0)
            attach.assert_not_awaited()

    async def test_attribution_failure_rolls_back_signup(self):
        self.cur.rowcount=1
        with patch.object(ads,'attribute_new_user',AsyncMock(side_effect=OSError('fixture'))):
            with self.assertRaises(OSError):await referrals.register_user(42,None,ad_token=TOKEN)
        self.conn.rollback.assert_awaited_once();self.conn.commit.assert_not_awaited()


class AdvertisingRulesTests(unittest.IsolatedAsyncioTestCase):
    async def test_subscription_preserves_campaign_and_not_personal_referrer(self):
        values={'pending_referrer':43}
        async def update(**kwargs):values.update(kwargs)
        state=NS(get_data=AsyncMock(side_effect=lambda:dict(values)),update_data=update)
        await referral_link.remember(NS(text='/start ad_'+TOKEN,from_user=NS(id=42)),state)
        self.assertEqual(values['pending_ad'],TOKEN);self.assertIsNone(values['pending_referrer'])
        with patch.object(referrals,'register_user',AsyncMock()) as register:
            await referral_link.complete(NS(id=42,username='alex'),state)
            register.assert_awaited_once_with(42,None,'alex',ad_token=TOKEN)
        self.assertIsNone(values['pending_ad'])

    async def test_invalid_payloads_are_rejected(self):
        for value in ['ad_../.env','ad_'+('a'*65),'ref_42','ad_'+('я'*22),None]:
            self.assertIsNone(ads.token_from_payload(value))
        self.assertEqual(ads.token_from_payload('ad_'+TOKEN),TOKEN)

    async def test_attribution_ignores_unknown_links_and_self_clicks(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value=None))
        await ads.attribute_new_user(cur,42,TOKEN)
        self.assertEqual(cur.execute.await_count,1)
        sql,args=cur.execute.call_args.args
        self.assertIn('c.owner_id<>%s',sql);self.assertIn('u.is_helper=1',sql)
        self.assertEqual(args,(TOKEN,42))

    async def test_list_query_is_scoped_and_never_selects_financial_data(self):
        with patch.object(ads,'require_helper',AsyncMock()),patch.object(ads,'rows',AsyncMock(side_effect=[[{'id':7,'name':'test','token':TOKEN}],[{'user_id':43,'username':'alex','created_at':'2026-11-15'}]])) as rows:
            result=await ads.campaign_users(42,7)
            self.assertEqual(len(result['items']),1)
            sql,args=rows.call_args.args
            self.assertIn('c.owner_id=%s',sql);self.assertNotIn('balance',sql);self.assertEqual(args,(7,42,0))

    async def test_create_rechecks_role_under_transaction_lock(self):
        cur=NS(execute=AsyncMock(),fetchone=AsyncMock(return_value={'id':42,'is_helper':0}))
        @asynccontextmanager
        async def transaction():yield cur
        with patch.object(config,'ADMIN_IDS',[]),patch.object(ads,'_transaction',transaction):
            with self.assertRaises(PermissionError):await ads.create_campaign(42,'test')
        self.assertIn('FOR UPDATE',cur.execute.call_args.args[0])
        self.assertEqual(cur.execute.await_count,1)


class BotRoleTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_ad_payload_registers_campaign_not_personal_referrer(self):
        from handlers.user import start
        message=NS(from_user=NS(id=42,username='visitor',first_name='Guest'),answer=AsyncMock())
        with patch.object(start,'is_new_user',AsyncMock(return_value=True)),patch.object(start,'create_user_with_referrer',AsyncMock()) as personal,patch.object(referrals,'register_user',AsyncMock(return_value=Decimal(0))) as register,patch.object(start,'update_user_username',AsyncMock()),patch.object(start,'main_menu',AsyncMock(return_value=None)),patch.object(start,'answer_screen',AsyncMock()):
            await start.cmd_start(message,NS(args='ad_'+TOKEN))
        personal.assert_not_awaited();register.assert_awaited_once_with(42,None,'visitor',ad_token=TOKEN)

    async def test_helper_admin_entry_has_only_advertising_actions(self):
        from handlers.admin import admin_panel,advertising
        message=NS(from_user=NS(id=42),answer=AsyncMock())
        state=NS(clear=AsyncMock())
        with patch.object(admin_panel,'is_admin',return_value=False),patch.object(ads,'is_helper',AsyncMock(return_value=True)),patch('utils.miniapp.admin_miniapp_url',return_value=None):
            await admin_panel.admin_start(message,state)
        state.clear.assert_awaited_once()
        keyboard=message.answer.call_args.kwargs['reply_markup']
        self.assertEqual({b.callback_data for row in keyboard.inline_keyboard for b in row},{'advertising:list','main_menu'})
        self.assertIn('Реклама',[b.text for row in keyboard.inline_keyboard for b in row])

    async def test_revoked_helper_cannot_use_old_bot_button(self):
        from handlers.admin import advertising
        call=NS(from_user=NS(id=42),data='advertising:list')
        state=NS(clear=AsyncMock())
        with patch.object(ads,'is_helper',AsyncMock(return_value=False)),patch.object(ads,'campaigns',AsyncMock()) as campaigns,patch.object(advertising,'answer_safe',AsyncMock()) as answer:
            await advertising.advertising_action(call,state)
        campaigns.assert_not_awaited();answer.assert_awaited_once()

    async def test_owner_keyboard_has_management_but_no_advertising_button(self):
        from keyboards.admin_kb import get_admin_panel
        callbacks={b.callback_data for row in get_admin_panel().inline_keyboard for b in row}
        self.assertIn('helper_manage',callbacks)
        self.assertFalse(any(value and value.startswith('advertising:') for value in callbacks))


if __name__=='__main__':unittest.main()
