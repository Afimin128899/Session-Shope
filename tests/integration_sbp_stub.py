"""Disposable localhost:13307 SBP payment path. --serve exposes browser fixture :8091.

All provider calls are fake; this script never loads project .env or contacts a cashier.
"""
import asyncio
from decimal import Decimal as D
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import config,db
from test_miniapp import TEST_TOKEN,signed_data
from database import admin_web,commerce,stars,shop_control
from services import payments,platega,cryptopay
from miniapp.server import create_app
import aiomysql
from aiohttp import ClientSession,web


async def main():
    name='sbp_stub_'+uuid4().hex
    config.ADMIN_IDS=[42];config.BOT_TOKEN=TEST_TOKEN;config.CRYPTO_PAY_TOKEN='fixture-only'
    config.PLATEGA_MERCHANT_ID=config.PLATEGA_SECRET=''
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def sql(query,args=()):
        async with conn.cursor() as cur:
            await cur.execute(query,args)
            return await cur.fetchall()
    async def balances():return [(await db.get_user(user))['balance'] for user in (42,43,44)]
    async def counts():return [(await sql('SELECT COUNT(*) FROM '+table))[0][0] for table in ('payment_invoices','payment_logs','used_transactions','referral_rewards','referral_daily_totals')]
    def report(text):print('PASS: '+text,flush=True)
    async def fake_create(method,path,payload=None):
        assert method=='POST' and path=='/transaction/process'
        assert payload['metadata']=={'user_email':'43@telegram.org'}
        assert payload['paymentDetails']['currency']=='RUB'
        return {'transactionId':str(uuid4()),'redirect':'https://example.test/sbp-payment'}
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,500),(43,100),(44,0)')
        await sql('INSERT INTO referrals(referral_id,referrer_id) VALUES(43,44)')
        assert await db.get_setting('platega_stub')=='1'
        methods={m['id']:m for m in await payments.get_methods()}
        assert methods['platega']['enabled'] and methods['platega']['min']==1 and methods['platega']['max']==10000
        assert methods['crypto']['max']==1000000 and methods['stars']['max']==10000
        before_counts,before_balances=await counts(),await balances()
        with patch.object(platega,'_request',AsyncMock(side_effect=AssertionError('Stub must never call API'))):
            for amount in ['1','500','10000']:
                try:await payments.create_deposit(43,'buyer','platega',amount)
                except payments.PaymentUnavailable:pass
                else:raise AssertionError('Stub created an invoice')
        assert await counts()==before_counts and await balances()==before_balances
        report('Keyless SBP is visible with range RUB 1–10,000; placeholder creates no invoices, wallet credits, markers or referral rewards')
        with patch.object(cryptopay,'create_invoice',AsyncMock(return_value={'invoice_id':123,'bot_invoice_url':'https://t.me/fixture_invoice'})):
            await payments.create_deposit(43,'buyer','crypto','10000.01')
        assert (await commerce.invoice('crypto','123',43))['amount_rub']==D('10000.01')
        star_bill=await stars.register_invoice(43,10000)
        assert star_bill['amount']=='12000.00'
        report('The RUB 10,000 funding cap applies only to SBP; Crypto and native Stars keep their separate limits')
        runner=web.AppRunner(create_app(enable_cart=True,customer_enabled=True,admin_enabled=True,token=TEST_TOKEN,bot=NS(),bot_username='fixture_sbp_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8091).start()
        customer={'Authorization':'tma '+signed_data(43)};admin={'Authorization':'tma '+signed_data(42)}
        origin='http://127.0.0.1:8091'
        with patch.object(platega,'_request',side_effect=fake_create) as cashier:
            async with ClientSession() as session:
                async def post(path,body,headers=customer):
                    response=await session.post(origin+path,headers=headers,json=body)
                    return response.status,await response.json()
                status,result=await post('/api/invoices',{'provider':'platega','amount':'1','stub':False,'user_id':999})
                assert status==409 and result['code']=='payment_unavailable'
                assert (await post('/api/admin/settings',{'platega_stub':'0'},customer))[0]==403
                assert await db.get_setting('platega_stub')=='1'
                for value in ['.99','10000.01','1.001','NaN']:
                    assert (await post('/api/invoices',{'provider':'platega','amount':value}))[0]==409
                assert cashier.call_count==0
                assert (await post('/api/admin/settings',{'platega_stub':'0'},admin))[0]==200
                assert (await post('/api/invoices',{'provider':'platega','amount':'1'}))[0]==409 # keys not configured
                assert cashier.call_count==0
                config.PLATEGA_MERCHANT_ID='631790a6-375b-4dc7-8a19-e9641fb8b0a0';config.PLATEGA_SECRET='fixture-not-real'
                before=await balances()
                prior_calls=cashier.call_count
                for value in ['.99','10000.01','1.001']:
                    assert (await post('/api/invoices',{'provider':'platega','amount':value}))[0]==409
                assert cashier.call_count==prior_calls
                status,invoice=await post('/api/invoices',{'provider':'platega','amount':'1','user_id':999})
                assert status==201 and invoice['amount']=='1'
                assert cashier.call_count==1 and await balances()==before
                assert (await commerce.invoice('platega',invoice['invoice_id'],43))['amount_rub']==1
                await post('/api/admin/settings',{'platega_stub':'1'},admin)
                paid={'id':invoice['invoice_id'],'status':'CONFIRMED','payload':'rub_topup:43:1.00','merchantId':config.PLATEGA_MERCHANT_ID,'paymentDetails':{'amount':1,'currency':'RUB'}}
                with patch.object(platega,'get_invoice',AsyncMock(return_value=paid)):
                    results=await asyncio.gather(payments.check_invoice(43,'platega',invoice['invoice_id']),payments.check_invoice(43,'platega',invoice['invoice_id']))
                assert sum(bool(x['credited']) for x in results)==1
                assert (await db.get_user(43))['balance']==D('101.10')
                assert (await db.get_user(44))['balance']==D('.05')
                report('Only admin can toggle; client flags cannot bypass it; live mode creates a RUB 1 invoice and rejects >10,000; enabling the stub preserves exactly-once settlement of old invoices')
                legacy_id=str(uuid4())
                await commerce.register_invoice('platega',legacy_id,43,D('11111'))
                legacy_paid={'id':legacy_id,'status':'CONFIRMED','payload':'rub_topup:43:11111.00','merchantId':config.PLATEGA_MERCHANT_ID,'paymentDetails':{'amount':11111,'currency':'RUB'}}
                with patch.object(platega,'get_invoice',AsyncMock(return_value=legacy_paid)):
                    assert (await payments.check_invoice(43,'platega',legacy_id))['credited']
                    assert not (await payments.check_invoice(43,'platega',legacy_id))['credited']
                assert (await db.get_user(43))['balance']==D('11212.10')
                report('The NEW SBP limit stays at RUB 10,000; a pre-existing paid legacy invoice settles once without discarding paid money')
                await admin_web.save_settings(42,{'platega_stub':'0'})
                async with conn.cursor() as cur:await shop_control.init_schema(cur,name)
                assert await db.get_setting('platega_stub')=='0'
                await admin_web.save_settings(42,{'platega_stub':'1'})
                report('Repeated migration retains the administrator’s switch and the moderation path is ready without any real payment')
            if '--serve' in sys.argv:
                print('BROWSER FIXTURE: http://127.0.0.1:8091 customer=43 admin=42',flush=True)
                await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
