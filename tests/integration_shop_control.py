"""Disposable localhost:13307 SQL/HTTP checks. Never imports the repository .env.

--serve leaves the isolated browser fixture on localhost:8088 until interrupted.
"""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db, config
from test_miniapp import TEST_TOKEN, signed_data
import aiomysql
from aiohttp import ClientSession, web
from database import shop_control, commerce, admin_web, preferences, bot_store
from miniapp import storage
from miniapp.server import create_app


async def main():
    name='shop_control_'+uuid4().hex
    config.ADMIN_IDS=[42]
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    connection=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def execute(sql,args=()):
        async with connection.cursor() as cur:
            await cur.execute(sql,args)
            return await cur.fetchall()
    def report(text):print('PASS: '+text,flush=True)
    try:
        await db.init_db()
        await execute(f'USE `{name}`')
        await execute('INSERT INTO users(id,balance) VALUES(42,10000),(43,1000)')
        await execute("INSERT INTO categories(slug,name,is_active) VALUES('controls','Каталог',1)")
        ids=[]
        for i in range(8):
            async with connection.cursor() as cur:
                await cur.execute("INSERT INTO accounts(country,number,price,password,data,warranty_hours,spam_status) VALUES('controls',%s,100,%s,'PRIVATE_TEST_SESSION',24,'clear')",
                                  (f'+15558888{i:03d}','Мой профиль {0} $& <secret>'))
                ids.append(cur.lastrowid)
        paid=await storage.checkout(43,ids[-1],Decimal(100))
        await commerce.add_to_cart(43,ids[0])
        before=(await db.get_user(43))['balance']
        await shop_control.set_review(42,ids[0],True,'Private review reason')
        assert not await execute('SELECT * FROM shopping_cart WHERE account_id=%s',(ids[0],))
        assert not await execute('SELECT * FROM account_reservations WHERE account_id=%s',(ids[0],))
        assert await bot_store.product(43,ids[0]) is None
        assert ids[0] not in {x['id'] for x in (await storage.catalog(43))['items']}
        try:await storage.checkout(43,ids[0],Decimal(100))
        except storage.CheckoutError as e:assert e.code=='sold'
        else:raise AssertionError('Review account was sold')
        assert (await db.get_user(43))['balance']==before
        await shop_control.set_review(42,ids[0],False,'Verified and fixed')
        assert await bot_store.product(43,ids[0])
        history=await execute("SELECT action,details FROM admin_audit_log WHERE target_type='account' AND target_id=%s ORDER BY id",(str(ids[0]),))
        assert [r[0] for r in history]==['account_review','account_release']
        assert 'Private review reason' in history[-1][1]
        report('Review hides stock, cancels holds/cart without charging, explicitly releases and preserves reasons')

        await commerce.add_to_cart(43,ids[1])
        await admin_web.save_settings(42,{'sales_paused':'1'})
        for action in [storage.checkout(43,ids[0],Decimal(100)),storage.checkout_cart(43,[{'account_id':ids[1],'price':'100'}]),commerce.add_to_cart(43,ids[2])]:
            try:await action
            except storage.CheckoutError as e:assert e.code=='sales_paused'
            else:raise AssertionError('Paused sales allowed a purchase/reservation')
        assert await db.buy_account(43,ids[0],100,'fixture',currency='RUB') is None
        assert await db.buy_account_with_referral(43,ids[0],100,'fixture',0,0,currency='RUB') is None
        assert (await db.get_user(43))['balance']==before
        # Existing payment settlement is independent of the sales switch.
        credited=await db.credit_paid_deposit(43,50,'crypto','local-fixture-confirmed')
        assert credited and (await db.get_user(43))['balance']>before
        report('Single/cart/legacy checkouts and reservations stop; confirmed top-ups continue')

        runner=web.AppRunner(create_app(enable_cart=True,customer_enabled=True,admin_enabled=True,token=TEST_TOKEN,bot=SimpleNamespace(),bot_username='local_fixture_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8088).start()
        buyer={'Authorization':'tma '+signed_data(43)}
        admin={'Authorization':'tma '+signed_data(42)}
        origin='http://127.0.0.1:8088'
        async with ClientSession() as session:
            async def get(path,headers=buyer):
                response=await session.get(origin+path,headers=headers)
                return response.status,await response.json(),response.headers
            async def post(path,body,headers=buyer):
                response=await session.post(origin+path,headers=headers,json=body)
                return response.status,await response.json(),response.headers
            assert (await get('/api/orders'))[0]==200
            code,details,_=await get('/api/orders/'+str(paid['id']))
            assert code==200 and details['password']=='Мой профиль {0} $& <secret>'
            assert (await post('/api/preferences/language',{'language':'en','user_id':42}))[0]==200
            assert await preferences.get_language(43)=='en' and await preferences.get_language(42)=='ru'
            code,me,headers=await get('/api/me')
            assert code==200 and me['language']=='en' and headers['Content-Language']=='en'
            code,details,_=await get('/api/orders/'+str(paid['id']))
            assert details['password']=='Мой профиль {0} $& <secret>'
            code,data,_=await get('/api/catalog')
            assert any(x['name']=='Каталог' for x in data['items'])
            report('Purchases remain accessible while paused; language persists without altering account data')
            await admin_web.save_settings(42,{'maintenance_mode':'1','maintenance_reason':'Fixture <reason>','maintenance_eta':'18:00 MSK'})
            code,data,_=await get('/api/me')
            assert code==503 and 'Maintenance' in data['error'] and data['shop_status']['reason']=='Fixture <reason>'
            assert (await get('/api/status'))[0]==200 and (await get('/api/me',admin))[0]==200
            assert (await post('/api/preferences/language',{'language':'ru'}))[0]==200
            assert await preferences.get_language(43)=='ru'
            code,data,_=await get('/api/me')
            assert code==503 and 'технические' in data['error']
            report('Full maintenance has a status screen; administrator access and language selection remain available')
        await admin_web.save_settings(42,{'maintenance_mode':'0','sales_paused':'0'})

        # A checkout waiting for inventory must re-read the sales switch after pause.
        blocker=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=False)
        try:
            await blocker.begin()
            async with blocker.cursor() as cur:await cur.execute('SELECT id FROM accounts WHERE id=%s FOR UPDATE',(ids[3],))
            pending=asyncio.create_task(storage.checkout(43,ids[3],Decimal(100)))
            await asyncio.sleep(.05)
            await admin_web.save_settings(42,{'sales_paused':'1'})
            await blocker.commit()
            try:await pending
            except storage.CheckoutError as e:assert e.code=='sales_paused'
            else:raise AssertionError('A waiting checkout bypassed pause')
        finally:blocker.close()
        await admin_web.save_settings(42,{'sales_paused':'0'})
        async def race_purchase():
            try:return await storage.checkout(43,ids[4],Decimal(100))
            except storage.CheckoutError:return None
        async def race_review():
            try:return await shop_control.set_review(42,ids[4],True,'Concurrent review')
            except ValueError:return None
        a,b=await asyncio.gather(race_purchase(),race_review())
        assert (isinstance(a,dict) and b is None) or (a is None and b=='review')
        report('Concurrent review/purchase has one winner; a waiting checkout cannot bypass a committed pause')

        # Repeated startup must preserve new preferences and reviewed stock.
        await preferences.set_language(43,'en')
        await shop_control.set_review(42,ids[5],True,'Retain over restart')
        db.pool.close();await db.pool.wait_closed();db.pool=None
        await db.init_db()
        assert await preferences.get_language(43)=='en'
        assert (await db.get_account(ids[5]))['status']=='review'
        report('Repeated schema initialization preserves language, review status and audit history')
        await preferences.set_language(43,'ru')
        if '--serve' in sys.argv:
            print('Control browser fixture listening on localhost:8088',flush=True)
            await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        await execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__=='__main__':asyncio.run(main())
