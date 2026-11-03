"""Disposable MySQL only: durable spam-check leases, ownership races and snapshots."""
import asyncio
from decimal import Decimal
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import aiomysql
from test_payments import db
from database import spam_checks, commerce, admin_web
from miniapp import storage


async def main():
    name='spam_integration_'+uuid4().hex
    connection=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    try:
        db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await spam_checks.init_schema(cur,name)
            await spam_checks.init_schema(cur,name)
            await cur.execute('INSERT INTO users(id,balance) VALUES(42,1000),(43,0)')
            await cur.execute("INSERT INTO categories(slug,name,is_active) VALUES('spam_test','Test',1)")
            ids=[]
            for i in range(5):
                await cur.execute("INSERT INTO accounts(country,number,price,data,telegram_user_id,warranty_hours,status) VALUES('spam_test',%s,100,%s,%s,24,%s)",
                                  (f'+7999000{i:04}','FIXTURE_SESSION_PRIVATE_'+str(i)*200,9000+i,'sold' if i==4 else 'available'))
                ids.append(cur.lastrowid)
        print('PASS: additive spam schema can be applied repeatedly')
        await commerce.add_to_cart(42,ids[0])
        leases=await asyncio.gather(spam_checks.claim(),spam_checks.claim(),spam_checks.claim())
        assert {r['id'] for r in leases}==set(ids[1:4])
        assert await spam_checks.claim() is None
        lease=next(r for r in leases if r['id']==ids[1])
        catalog=await storage.catalog(42)
        checking=next(r for r in catalog['items'] if r['id']==lease['id'])
        assert not checking['available'] and checking['characteristics']['spam_check']['running']
        assert 'FIXTURE_SESSION_PRIVATE' not in str(catalog)
        stock=await admin_web.stock()
        assert 'FIXTURE_SESSION_PRIVATE' not in str(stock) and all('spam_token' not in r for r in stock['items'])
        print('PASS: leases are exclusive across workers; sold and reserved accounts are skipped; APIs hide sessions/tokens')
        try:
            await storage.checkout(42,lease['id'],Decimal(100))
        except storage.CheckoutError as error:
            assert error.code=='checking'
        else:
            raise AssertionError('Account sold during SpamBot check')
        try:
            await commerce.add_to_cart(42,lease['id'])
        except ValueError:
            pass
        else:
            raise AssertionError('Account reserved during SpamBot check')
        assert await db.buy_account(42,lease['id'],100,'fixture',currency='RUB') is None
        assert await db.buy_account_with_referral(42,lease['id'],100,'fixture',0,0,currency='RUB') is None
        assert (await db.get_user(42))['balance']==1000
        print('PASS: shared checkout, old checkout and cart cannot transfer a live checking account')
        assert await spam_checks.finish(lease,{'status':'clear','reason':None})
        assert not await spam_checks.finish(lease,{'status':'limited','reason':None})
        order=await storage.checkout(42,lease['id'],Decimal(100),spam_status='clear')
        snapshot=json.loads((await db.get_purchase_for_user(order['id'],42))['attributes_snapshot'])
        assert snapshot['spam_status']=='clear' and snapshot['spam_checked_at']
        assert await spam_checks.enqueue(7,lease['id'])==0
        print('PASS: completed result releases stock; sale saves historical spam status and sold accounts cannot be queued')
        stale=next(r for r in leases if r['id']==ids[2])
        async with connection.cursor() as cur:
            await cur.execute("UPDATE accounts SET status='sold' WHERE id=%s",(stale['id'],))
        assert not await spam_checks.finish(stale,{'status':'clear','reason':None})
        changed=next(r for r in leases if r['id']==ids[3])
        async with connection.cursor() as cur:
            await cur.execute('UPDATE accounts SET data=%s,spam_lease_until=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 SECOND) WHERE id=%s',('DIFFERENT_PRIVATE_SESSION_'*20,changed['id']))
        assert not await spam_checks.finish(changed,{'status':'clear','reason':None})
        replacement=await spam_checks.claim()
        assert replacement['id']==changed['id'] and replacement['token']!=changed['token']
        await spam_checks.release(changed)
        assert await spam_checks.finish(replacement,{'status':'limited','reason':None})
        assert (await db.get_account(changed['id']))['spam_status']=='limited'
        print('PASS: sold/changed-session/expired-lease results cannot overwrite newer checks')
        assert await spam_checks.enqueue(7,changed['id'])==0
        async with connection.cursor() as cur:
            await cur.execute('UPDATE accounts SET spam_checked_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 MINUTE) WHERE id=%s',(changed['id'],))
        assert await spam_checks.enqueue(7,changed['id'])==1
        manual=await spam_checks.claim()
        assert manual['id']==changed['id']
        assert await spam_checks.finish(manual,{'status':'error','reason':'flood_wait','retry_after':7200})
        async with connection.cursor() as cur:
            await cur.execute('UPDATE accounts SET spam_checked_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 MINUTE) WHERE id=%s',(changed['id'],))
            await cur.execute('SELECT TIMESTAMPDIFF(SECOND,UTC_TIMESTAMP(),spam_next_check_at) FROM accounts WHERE id=%s',(changed['id'],))
            assert (await cur.fetchone())[0]>=7190
        assert await spam_checks.enqueue(7,changed['id'])==0
        assert await spam_checks.claim() is None
        print('PASS: manual cooldown and Telegram FloodWait survive queue requests without early retry')
        async with connection.cursor() as cur:
            await cur.execute("UPDATE accounts SET spam_status='limited',spam_checked_at=UTC_TIMESTAMP() WHERE id=%s",(ids[0],))
        before=(await db.get_user(42))['balance']
        cart_quote={'account_id':ids[0],'price':'100.00','warranty_hours':24,'spam_status':'clear'}
        try:
            await storage.checkout_cart(42,[cart_quote])
        except storage.CheckoutError as error:
            assert error.code=='terms_changed'
        else:
            raise AssertionError('Changed spam status did not require confirmation')
        assert (await db.get_user(42))['balance']==before
        result=await storage.checkout_cart(42,[cart_quote|{'spam_status':'limited'}])
        snapshot=json.loads((await db.get_purchase_for_user(result['order_ids'][0],42))['attributes_snapshot'])
        assert snapshot['spam_status']=='limited'
        print('PASS: cart quotes revalidate spam status, retain funds on conflict and snapshot explicitly confirmed limits')
        print('All real-DB SpamBot queue scenarios passed.',flush=True)
    finally:
        if db.pool:
            db.pool.close();await db.pool.wait_closed();db.pool=None
        async with connection.cursor() as cur:
            await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__=='__main__':
    asyncio.run(main())
