"""Disposable localhost:13307 checks; all provider responses/credentials are synthetic.

--serve keeps the isolated buyer/admin fixture on localhost:8089 for browser tests.
"""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db, config
from test_miniapp import signed_data, TEST_TOKEN
import aiomysql
from aiohttp import ClientSession, web
from database import admin_web, admin_tools, commerce, imports, sales_policy, shop_control, stars as ledger
from miniapp import storage
from miniapp.server import create_app
from services import payments, platega


async def main():
    name='platega_policy_'+uuid4().hex
    config.ADMIN_IDS=[42]
    config.PLATEGA_MERCHANT_ID='631790a6-375b-4dc7-8a19-e9641fb8b0a0'
    config.PLATEGA_SECRET='fixture-not-real'
    config.BOT_TOKEN=TEST_TOKEN
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    connection=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def sql(query,args=()):
        async with connection.cursor() as cur:
            await cur.execute(query,args)
            return await cur.fetchall()
    async def insert(phone,price=100,country='us',status='available'):
        async with connection.cursor() as cur:
            await cur.execute('INSERT INTO accounts(country,number,price,data,status) VALUES(%s,%s,%s,%s,%s)',(country,phone,price,'PRIVATE_FIXTURE_SESSION',status))
            return cur.lastrowid
    async def denied(action):
        try:await action
        except ValueError:return
        raise AssertionError('Restricted operation was accepted')
    def report(text):print('PASS: '+text,flush=True)
    try:
        await db.init_db();await sql(f'USE `{name}`')
        assert not await sql("SELECT slug FROM categories WHERE slug IN ('ru','ua') AND is_active=1")
        await sql('INSERT INTO users(id,balance) VALUES(42,30000),(43,30000)')
        await sql("UPDATE settings SET value='fixture_support' WHERE `key`='support_username'")
        await admin_web.save_settings(42,{'platega_stub':'0'})
        for slug,label in [('ru','Россия'),('ua','Украина'),('custom','🇷🇺 Premium')]:
            await denied(admin_web.save_category(42,{'slug':slug,'name':label}))
        for phone in ['+79991234567','+380991234567']:
            await denied(db.add_account('us','',phone,'-',100,'fixture-'+phone))
        await denied(db.add_account('us','','+15551230001','-',10001,'fixture-high-price'))
        assert not await sql('SELECT identity_key FROM inventory_identities')
        await db.add_account('kz','','+77011234567','-',100,'fixture-kz')
        await db.add_account('us','','+15551230002','-',10000,'fixture-at-limit')
        from database import spam_checks
        for _ in range(2):
            lease=await spam_checks.claim()
            assert await spam_checks.finish(lease,{'status':'clear','reason':None})
        report('Defaults exclude restricted categories; adding/category creation reject blocked origins and prices; Kazakhstan works')

        batch=await imports.create(42)
        await imports.add_item(batch,'account.session','ready',phone='+380991234567',telegram_id=10001,session='fixture-invalid-draft')
        await imports.finish(batch)
        draft=await imports.preview(42,batch)
        await denied(imports.commit(42,batch,[{'id':draft['items'][0]['id'],'category':'us','price':'100'}]))
        assert (await imports.preview(42,batch))['status']=='ready'
        assert not await sql("SELECT id FROM accounts WHERE number='+380991234567'")
        report('Old or manipulated import drafts cannot bypass phone-origin checks at publication')

        # Legacy mislabelled stock is rechecked under the buyer lock, even before migration.
        russian=await insert('+79991230001')
        expensive=await insert('+15551230003',10001)
        await denied(storage.checkout(43,russian,Decimal(100)))
        await denied(storage.checkout(43,expensive,Decimal(10001)))
        await denied(commerce.add_to_cart(43,russian))
        assert (await db.get_user(43))['balance']==30000
        legacy=await insert('+15551239999',100)
        assert await db.buy_account(43,legacy,10001,'fixture',currency='RUB') is None
        assert await db.buy_account_with_referral(43,legacy,10001,'fixture',0,0,currency='RUB') is None
        assert (await db.get_user(43))['balance']==30000
        first=await insert('+15551230004',6000);second=await insert('+15551230005',6000)
        await commerce.add_to_cart(43,first);await commerce.add_to_cart(43,second)
        await denied(storage.checkout_cart(43,[{'account_id':first,'price':'6000'},{'account_id':second,'price':'6000'}],expected_total=Decimal(10200)))
        assert (await db.get_user(43))['balance']==30000
        assert len(await sql('SELECT account_id FROM shopping_cart WHERE user_id=43'))==2
        order=await storage.checkout(43,(await sql("SELECT id FROM accounts WHERE number='+15551230002'"))[0][0],Decimal(10000))
        assert order['paid_amount']=='10000.00'
        report('Single/cart checkout validate actual stock and RUB 10,000 total atomically; denied purchases never debit or clear carts')

        # Migration must neither delete old orders nor silently discount forbidden stock.
        await sql("INSERT INTO categories(slug,name,is_active) VALUES('legacy-country','Россия 🇷🇺',1)")
        another=await insert('+380991230001',100,'legacy-country')
        sold=await insert('+79991230002',20000,'us','sold')
        async with connection.cursor() as cur:await sales_policy.migrate(cur)
        for account in [russian,expensive,another]:
            assert (await sql('SELECT status FROM accounts WHERE id=%s',(account,)))[0][0]=='review'
            await denied(shop_control.set_review(42,account,False,'Try to release'))
        assert (await sql('SELECT status,price FROM accounts WHERE id=%s',(sold,)))[0]==('sold',Decimal(20000))
        assert not (await sql("SELECT is_active FROM categories WHERE slug='legacy-country'"))[0][0]
        before=len(await sql("SELECT id FROM admin_audit_log WHERE action='policy_review'"))
        async with connection.cursor() as cur:await sales_policy.migrate(cur)
        assert len(await sql("SELECT id FROM admin_audit_log WHERE action='policy_review'"))==before
        assert not await admin_tools.change_account_price(42,sold,100)
        await admin_tools.change_category_price(42,'us',6000)
        assert (await sql('SELECT price FROM accounts WHERE id=%s',(sold,)))[0][0]==20000
        await admin_tools.change_balance(42,43,10001,'RUB','add')
        report('Idempotent migration withdraws legacy stock; category repricing preserves sold history; administrative balance changes are independent of SBP limits')

        identity='1a413e35-0db0-48b5-bf29-2461e0652df0'
        pending={'id':identity,'pay_url':'https://app.platega.io/pay/fixture'}
        paid={'id':identity,'status':'CONFIRMED','payload':'rub_topup:43:500.00','paymentDetails':{'amount':500,'currency':'RUB'},'merchantId':config.PLATEGA_MERCHANT_ID}
        with patch.object(platega,'create_invoice',AsyncMock(return_value=pending)):
            await payments.create_deposit(43,'ignored-for-identity','platega','500')
        before=(await db.get_user(43))['balance']
        with patch.object(platega,'get_invoice',AsyncMock(return_value=paid)):
            await denied(payments.check_invoice(42,'platega',identity))
            results=await asyncio.gather(payments.check_invoice(43,'platega',identity),payments.check_invoice(43,'platega',identity))
            assert sum(bool(result['credited']) for result in results)==1
        assert (await db.get_user(43))['balance']==before+550
        assert len(await sql("SELECT id FROM payment_logs WHERE method='platega_pay'"))==1
        assert (await commerce.invoice('platega',identity,43))['status']=='credited'
        report('Confirmed Platega invoice credits once under concurrent checks; another buyer cannot inspect it')

        stars=await ledger.register_invoice(43,8333)
        assert stars['amount']=='9999.60'
        await denied(ledger.register_invoice(43,10001))
        old_id=uuid4().hex
        await sql("INSERT INTO payment_invoices(provider,invoice_id,user_id,amount_rub,stars_count,created_at,expires_at,next_check_at) VALUES('stars',%s,43,12000,10000,UTC_TIMESTAMP(),UTC_TIMESTAMP()+INTERVAL 1 HOUR,UTC_TIMESTAMP())",(old_id,))
        assert (await ledger.check_precheckout(43,ledger.PAYLOAD_PREFIX+old_id,'XTR',10000))['stars']==10000
        before=(await db.get_user(43))['balance']
        assert await ledger.credit_payment(43,old_id,10000,'fixture-legacy-charge')==12000
        assert await ledger.credit_payment(43,old_id,10000,'fixture-legacy-charge') is None
        assert (await db.get_user(43))['balance']==before+12000
        report('Stars retain their native 10,000 count ceiling independently of SBP; historical receipts remain exactly-once credited')

        runner=web.AppRunner(create_app(enable_cart=True,customer_enabled=True,admin_enabled=True,token=TEST_TOKEN,bot=SimpleNamespace(),bot_username='fixture_store_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8089).start()
        async with ClientSession() as session:
            res=await session.get('http://127.0.0.1:8089/about')
            body=await res.text();assert res.status==200 and 'mekbuda' in body and '10 000' in body and 'telegra.ph/POLITIKA' in body
            headers={'Authorization':'tma '+signed_data(43)}
            res=await session.post('http://127.0.0.1:8089/api/invoices',headers=headers,json={'provider':'platega','amount':'10000.01'})
            assert res.status==409
            with patch.object(platega,'create_invoice',AsyncMock(return_value={**pending,'id':str(uuid4())})) as create:
                res=await session.post('http://127.0.0.1:8089/api/invoices',headers=headers,json={'provider':'platega','amount':'100','user_id':999,'email':'untrusted@example.test'})
                assert res.status==201;assert create.call_args.args[-1]==43
        report('Unauthenticated review page works; signed API enforces the amount and ignores a spoofed payer/email')
        if '--serve' in sys.argv:
            print('BROWSER FIXTURE: http://127.0.0.1:8089 buyer=43 admin=42',flush=True)
            await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:
            db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:connection.close()


if __name__=='__main__':asyncio.run(main())
