"""Disposable localhost:13307 ledger checks; --serve keeps browser fixture :8090.

Never imports project .env or contacts Telegram/payment services.
"""
import asyncio
from decimal import Decimal as D
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db,config
from test_miniapp import TEST_TOKEN,signed_data
from database import referrals,admin_web,commerce,stars,refunds,spam_checks
from miniapp import storage
from miniapp.server import create_app
import aiomysql
from aiohttp import ClientSession,web


async def main():
    name='referrals_'+uuid4().hex
    config.ADMIN_IDS=[42];config.BOT_TOKEN=TEST_TOKEN
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def sql(query,args=()):
        async with conn.cursor() as cur:
            await cur.execute(query,args)
            return await cur.fetchall()
    async def balance(user):return D(str((await db.get_user(user))['balance']))
    async def stock(index,price=100):
        async with conn.cursor() as cur:
            await cur.execute("INSERT INTO accounts(country,number,price,password,data,telegram_user_id,warranty_hours,spam_status) VALUES('us',%s,%s,'fixture-password','PRIVATE_REFERRAL_SESSION',%s,24,'clear')",(f'+1555123{index:04}',price,80000+index))
            return cur.lastrowid
    def report(text):print('PASS: '+text,flush=True)
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,1000),(43,0),(44,0)')
        await admin_web.save_settings(42,{'referral_daily_limit':'10000'})
        await asyncio.gather(db.create_user_with_referrer(100,43,'new_buyer'),db.create_user_with_referrer(100,44,'new_buyer'))
        owner=await db.get_referrer(100);assert owner in (43,44)
        # Normalize the chosen recipient ID locally, keeping the relationship immutable.
        inviter=owner;other=44 if inviter==43 else 43
        assert await balance(inviter)==3 and await balance(other)==0
        await db.create_user_with_referrer(100,other,'renamed_buyer')
        await db.create_user_with_referrer(other,inviter,'existing_buyer')
        await db.create_user_with_referrer(105,105,'self_link')
        await db.create_user_with_referrer(106,999999,'invalid_link')
        assert await db.get_referrer(100)==inviter and await db.get_referrer(other) is None
        assert await db.get_referrer(105) is None and await db.get_referrer(106) is None
        assert await balance(inviter)==3
        report('Concurrent first starts pay exactly one RUB 3 reward; old users, self-links and changed links never earn another signup reward')

        credited=await asyncio.gather(db.credit_paid_deposit(100,1000,'crypto','deposit-1'),db.credit_paid_deposit(100,1000,'crypto','deposit-1'))
        assert sum(value is not None for value in credited)==1
        assert await balance(100)==1104 and await balance(inviter)==53
        for provider in ['xrocket','lave','platega']:
            await db.credit_paid_deposit(100,100,provider,'deposit-'+provider)
        assert await balance(inviter)==68
        # A reward failure rolls back payer credit, idempotency marker AND inviter credit.
        before_buyer,before_inviter=await balance(100),await balance(inviter)
        original=referrals._award
        async def fail_after_award(*args,**kwargs):
            await original(*args,**kwargs)
            raise OSError('fixture reward failure')
        with patch.object(referrals,'_award',fail_after_award):
            try:await db.credit_paid_deposit(100,100,'crypto','retry-after-rollback')
            except OSError:pass
            else:raise AssertionError('Injected failure was swallowed')
        assert await balance(100)==before_buyer and await balance(inviter)==before_inviter
        assert not await sql("SELECT event_key FROM referral_rewards WHERE reference='retry-after-rollback'")
        await db.credit_paid_deposit(100,100,'crypto','retry-after-rollback')
        assert await balance(inviter)==before_inviter+5
        report('All external providers reward the actual principal once; first-deposit bonus is excluded and a failed reward rolls back the entire payment')

        await admin_web.save_settings(42,{'referral_signup_bonus':'4','referral_deposit_pct':'7.50','referral_purchase_pct':'12.50','referral_discount_pct':'10'})
        before=await balance(inviter)
        await db.create_user_with_referrer(101,inviter,'second_buyer')
        assert await balance(inviter)==before+4
        before=await balance(inviter)
        await db.credit_paid_deposit(100,200,'crypto','new-rate')
        assert await balance(inviter)==before+15
        old=(await sql("SELECT amount,rate FROM referral_rewards WHERE reference='deposit-1'"))[0]
        assert old==(D(50),D(5))
        report('Changed signup/deposit/purchase settings apply to future operations only and preserve old snapshots')

        invoice=await stars.register_invoice(100,100)
        before=await balance(inviter)
        assert await stars.credit_payment(100,invoice['invoice_id'],100,'charge-1')==120
        assert await stars.credit_payment(100,invoice['invoice_id'],100,'charge-1') is None
        assert await balance(inviter)==before+9
        assert await stars.credit_payment(100,invoice['invoice_id'],100,'charge-2')==120
        assert await balance(inviter)==before+18
        await admin_web.save_settings(42,{'referral_deposit_pct':'90'})
        assert await stars.refund_payment(invoice['invoice_id'],100,'charge-1',user_id=100)==120
        assert await stars.refund_payment(invoice['invoice_id'],100,'charge-1',user_id=100) is None
        assert await balance(inviter)==before+9
        assert await stars.refund_payment(invoice['invoice_id'],100,'charge-refund-first',user_id=100) is None
        assert await stars.credit_payment(100,invoice['invoice_id'],100,'charge-refund-first') is None
        assert await balance(inviter)==before+9
        report('Distinct real Stars charges each reward once; refunds reverse the original RUB 9 despite a new rate; refund-before-paid grants no reward')

        account=await stock(1)
        before=await balance(inviter)
        order=await storage.checkout(100,account,D(90))
        assert order['paid_amount']=='90.00'
        assert await balance(inviter)==before+D('11.25')
        pair=[await stock(2),await stock(3)]
        for identity in pair:await commerce.add_to_cart(100,identity)
        await sql("INSERT INTO promocodes(code,value,max_uses,kind) VALUES('REF10',10,1,'discount')")
        before=await balance(inviter)
        cart=await storage.checkout_cart(100,[{'account_id':i,'price':'90'} for i in pair],promo_code='REF10',expected_total=D(162))
        assert D(cart['paid_amount'])==162
        assert await balance(inviter)==before+D('20.25')
        await admin_web.save_settings(42,{'referral_purchase_pct':'90'})
        before=await balance(inviter)
        await refunds.refund_order(42,order['id'],'Fixture original-rate refund')
        assert await refunds.refund_order(42,order['id'],'Fixture retry') is None
        assert await balance(inviter)==before-D('11.25')
        report('Single/cart rewards use net prices after discounts and promo; refunds reverse the saved purchase bonus rather than the new rate')

        # Refunded rewards already spent may make the inviter negative, without blocking a genuine refund.
        await sql('UPDATE users SET balance=0 WHERE id=%s',(inviter,))
        await stars.refund_payment(invoice['invoice_id'],100,'charge-2',user_id=100)
        assert await balance(inviter)==-9
        new_account=await stock(4)
        lease=await spam_checks.claim()
        assert lease['id']==new_account
        live=await spam_checks.catalog_status(100,[new_account,account])
        assert len(live)==1 and live[0]['spam_check']['running'] and not live[0]['available']
        assert 'PRIVATE_REFERRAL_SESSION' not in str(live) and 'token' not in str(live)
        assert await spam_checks.finish(lease,{'status':'limited','reason':None})
        live=await spam_checks.catalog_status(100,[new_account])
        assert live[0]['spam_check']['status']=='limited' and not live[0]['spam_check']['running']
        report('Spent referral bonuses do not block Stars refunds; live spam projection updates immediately after worker completion and hides credentials')

        from integration_referral_limits import limit_scenarios
        await limit_scenarios(sql,balance,stock)

        for i in range(10,40):await stock(i)
        await admin_web.save_settings(42,{'referral_signup_bonus':'3','referral_deposit_pct':'5','referral_purchase_pct':'5','referral_discount_pct':'5'})
        runner=web.AppRunner(create_app(token=TEST_TOKEN,bot=SimpleNamespace(),bot_username='fixture_referral_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8090).start()
        async with ClientSession() as session:
            customer={'Authorization':'tma '+signed_data(100)};admin={'Authorization':'tma '+signed_data(42)}
            response=await session.get('http://127.0.0.1:8090/api/referrals?user_id='+str(inviter),headers=customer)
            data=await response.json();assert response.status==200 and data['count']==0
            response=await session.get('http://127.0.0.1:8090/api/referrals',headers={'Authorization':'tma '+signed_data(inviter)})
            data=await response.json();assert data['count']==2 and D(data['settings']['signup_bonus'])==3
            response=await session.post('http://127.0.0.1:8090/api/admin/settings',headers=customer,json={'referral_signup_bonus':'9999','admin_id':42})
            assert response.status==403
            response=await session.get('http://127.0.0.1:8090/api/admin/settings',headers=admin)
            data=await response.json();assert data['referral_signup_bonus']=='3.00'
            response=await session.post('http://127.0.0.1:8090/api/admin/settings',headers=admin,json={'referral_signup_bonus':'3.25'})
            assert response.status==200 and (await referrals.settings())['signup_bonus']==D('3.25')
        report('Verified HTTP identity scopes referral stats; only the administrator can edit amounts; settings are shared with the bot')
        # Re-run migration with old rows. It must not issue signup or deposit rewards retroactively.
        before=await balance(inviter);count=len(await sql('SELECT event_key FROM referral_rewards'))
        async with conn.cursor() as cur:await referrals.init_schema(cur,name)
        assert await balance(inviter)==before and len(await sql('SELECT event_key FROM referral_rewards'))==count
        report('Repeated migration preserves settings, previous rewards and reversal markers without retroactive credits')
        if '--serve' in sys.argv:
            print(f'BROWSER FIXTURE: http://127.0.0.1:8090 buyer=100 admin=42 inviter={inviter}',flush=True)
            await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
