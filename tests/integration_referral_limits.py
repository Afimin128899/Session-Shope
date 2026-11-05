"""Scenarios invoked from integration_referrals.py against its disposable database."""
import asyncio
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch
from database import referrals,db,admin_web,stars,refunds
from miniapp import storage


async def limit_scenarios(sql,balance,stock):
    await admin_web.save_settings(42,{'referral_daily_limit':'30','referral_signup_bonus':'3','referral_deposit_pct':'5','referral_purchase_pct':'5','referral_discount_pct':'5'})
    await db.create_user_with_referrer(200,None)
    await db.create_user_with_referrer(300,200,'limit_buyer')
    await db.create_user_with_referrer(301,200,'limit_buyer_2')
    assert await balance(200)==6
    await db.credit_paid_deposit(300,1000,'crypto','daily-first')
    assert await balance(300)==1100 and await balance(200)==30
    # Reaching the cap does not stop future real top-ups or create deferred rewards.
    await db.credit_paid_deposit(301,200,'xrocket','daily-full')
    await db.create_user_with_referrer(302,200,'limit_buyer_3')
    assert await balance(301)==220 and await balance(200)==30
    assert (await referrals.summary(200))['daily']['remaining']=='0'
    assert (await sql("SELECT amount,requested_amount,limit_reason FROM referral_rewards WHERE reference='daily-first'"))[0]==(D(24),D(50),'daily_limit')
    print('PASS: RUB 30/day is shared by signups and deposits; partial final rewards stop exactly at the cap without losing payer money',flush=True)

    tomorrow=referrals.reward_day()+timedelta(days=1)
    with patch.object(referrals,'reward_day',return_value=tomorrow):
        await db.credit_paid_deposit(301,200,'lave','next-day-first')
        await db.create_user_with_referrer(303,200,'tomorrow_buyer')
        assert await balance(200)==43
        bill=await stars.register_invoice(300,100)
        await stars.credit_payment(300,bill['invoice_id'],100,'limited-star-charge')
        assert await balance(200)==49
        await referrals.set_block(42,200,True,'Fixture blocked inviter')
        before=await balance(301)
        await db.credit_paid_deposit(301,200,'platega','blocked-payer-still-credited')
        assert await balance(301)==before+200 and await balance(200)==49
        identity=await stock(70)
        order=await storage.checkout(300,identity,D(95))
        assert order['paid_amount']=='95.00' and await balance(200)==49
        assert (await sql('SELECT referral_bonus FROM purchases WHERE id=%s',(order['id'],)))[0][0]==0
        await refunds.refund_order(42,order['id'],'Blocked inviter does not block a refund')
        await stars.refund_payment(bill['invoice_id'],100,'limited-star-charge',user_id=300)
        assert await balance(200)==43
        # Refund reverses actual credit, but never opens the same daily allowance again.
        assert D((await referrals.summary(200))['daily']['issued'])==19
        await referrals.set_block(42,200,False,'Fixture unblocked')
        await db.credit_paid_deposit(301,1000,'crypto','remaining-after-unblock')
        assert await balance(200)==54
        assert D((await referrals.summary(200))['daily']['issued'])==30
        assert (await sql("SELECT amount FROM referral_rewards WHERE reference='remaining-after-unblock'"))[0][0]==11
    print('PASS: Moscow date changes reset allowance; blocked recipients earn zero while buyer payments/purchases/refunds continue; refunds do not replenish the cap',flush=True)

    await db.create_user_with_referrer(500,None)
    await db.create_user_with_referrer(600,500)
    await db.create_user_with_referrer(601,500)
    await asyncio.gather(db.credit_paid_deposit(600,1000,'crypto','concurrent-cap-a'),db.credit_paid_deposit(601,1000,'crypto','concurrent-cap-b'))
    assert await balance(500)==30
    assert await balance(600)==1100 and await balance(601)==1100
    # Cap purchases too, with an actual saved partial bonus that can later be refunded.
    await db.create_user_with_referrer(700,None)
    await db.create_user_with_referrer(701,700)
    await sql('UPDATE users SET balance=1000 WHERE id=701')
    await sql('UPDATE users SET balance=29 WHERE id=700')
    await sql('UPDATE referral_daily_totals SET issued=29 WHERE referrer_id=700 AND reward_day=%s',(referrals.reward_day(),))
    identity=await stock(71)
    order=await storage.checkout(701,identity,D(95))
    assert await balance(700)==30
    assert (await sql('SELECT referral_bonus FROM purchases WHERE id=%s',(order['id'],)))[0][0]==1
    await refunds.refund_order(42,order['id'],'Return actual partial referral amount')
    assert await balance(700)==29 and D((await referrals.summary(700))['daily']['issued'])==30
    print('PASS: simultaneous deposits cannot exceed the cap; purchases save and refund the actual partial reward',flush=True)

    # Old ledger-free purchases today count towards the allowance after upgrade.
    await db.create_user_with_referrer(800,None)
    await db.create_user_with_referrer(801,None)
    identity=await stock(72)
    await sql("UPDATE accounts SET status='sold' WHERE id=%s",(identity,))
    await sql("INSERT INTO purchases(user_id,account_id,date,currency,paid_amount,referrer_id,referral_bonus) VALUES(801,%s,%s,'RUB',100,800,25)",(identity,str(referrals.reward_day())+' 00:01:00'))
    await db.create_user_with_referrer(802,800)
    assert await balance(800)==3
    assert D((await referrals.summary(800))['daily']['issued'])==28
    await referrals.set_block(42,888888,True,'Block future ID')
    await db.create_user_with_referrer(888888,None)
    await db.create_user_with_referrer(888889,888888)
    assert await balance(888888)==0
    assert (await referrals.summary(888888))['daily']['blocked']
    listing=await referrals.invited(200)
    assert {item['id'] for item in listing['items']}=={300,301,302,303}
    assert not ({item['id'] for item in (await referrals.invited(500))['items']} & {300,301,302,303})
    assert 'balance' not in str(listing) and 'PRIVATE_REFERRAL_SESSION' not in str(listing)
    await db.create_user_with_referrer(900,None)
    for user_id in range(1000,1025):
        await db.create_user_with_referrer(user_id,900,'ref_user_'+str(user_id))
    assert len((await referrals.invited(900,0))['items'])==20 and (await referrals.invited(900,0))['has_more']
    assert len((await referrals.invited(900,1))['items'])==5 and not (await referrals.invited(900,1))['has_more']
    assert await balance(900)==30
    print('PASS: legacy grants count towards today’s cap; future IDs can be blocked; referral lists are scoped to their owner and omit wallet/session data',flush=True)
