"""Real MariaDB shopping/reservation tests on disposable localhost:13307 only."""
import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import aiomysql
from test_payments import db
from inventory_fixture import confirm_fixture_account
from database import shop_navigation as store, commerce
from miniapp.storage import checkout_cart, CheckoutError


async def main():
    name = 'shopping_' + uuid4().hex
    conn = await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    try:
        db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
        await db.init_db()
        async with conn.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await cur.execute('INSERT INTO users(id,balance) VALUES(42,10000),(43,10000)')
            await cur.execute('INSERT INTO referrals(referral_id,referrer_id) VALUES(42,43)')
            await cur.execute('UPDATE referral_settings SET discount_pct=5,bonus_pct=5 WHERE id=1')
            await cur.execute("INSERT INTO settings(`key`,`value`) VALUES('wholesale_min_total','100'),('wholesale_pct','15') ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)")
        async def stock(phone,price,registered=None,premium=False,status='clear'):
            await db.add_account('us','US',phone,'fixture-password',price,'fixture-'+phone,telegram_user_id=int(phone.lstrip('+')),is_premium=premium)
            async with conn.cursor() as cur:
                await cur.execute('SELECT id FROM accounts WHERE number=%s',(phone,)); identity=(await cur.fetchone())[0]
            await confirm_fixture_account(identity,status)
            async with conn.cursor() as cur:
                await cur.execute('UPDATE accounts SET registration_date=%s WHERE id=%s',(registered,identity))
            return identity
        one=await stock('+15550000001',100)
        two=await stock('+15550000002',110)
        old=await stock('+15550000003',200,date(2014,1,1))
        recent=await stock('+919900000001',70,date.today())
        premium=await stock('+15550000004',300,date(2020,1,1),True)
        permanent=await stock('+15550000009',20,date(2015,1,1),status='permanent')
        kz=await stock('+77010000001',150)
        hidden=await stock('+56990000001',1)
        checking=await stock('+56990000002',2)
        async with conn.cursor() as cur:
            await cur.execute("UPDATE accounts SET status='review' WHERE id=%s",(hidden,))
            await cur.execute('UPDATE accounts SET spam_lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 MINUTE) WHERE id=%s',(checking,))
            # Legacy unavailable countries must not be revived by screenshot menus.
            await cur.execute("INSERT INTO categories(slug,name,is_active) VALUES('legacy-ru','Старый раздел',1)")
            await cur.execute("INSERT INTO accounts(country,number,price,data,status) VALUES('legacy-ru','+79990000001',1,'fixture','available')")
        auto=await store.countries(42,'auto')
        assert {x['country'] for x in auto}=={'us','in','kz'}
        assert next(x for x in auto if x['nation']=='us~clear')['min_price']==Decimal('95.00')
        assert (await store.countries(42,'auto','US'))[0]['country']=='us'
        assert (await store.countries(42,'auto','+77'))[0]['country']=='kz'
        assert await store.countries(42,'auto','not-a-country')==[]
        assert {x['country'] for x in await store.countries(42,'aged')}=={'us'}
        assert sum(x['count'] for x in await store.countries(42,'premium'))==1
        years=await store.years(42,'aged','us~clear')
        assert {x['year'] for x in years}=={2014,2020}
        items,total,_=await store.products(42,'aged','us~clear',2014)
        assert total==1 and items[0]['id']==old
        assert 'data' not in items[0] and 'password' not in items[0]
        assert (await store.products(42,'auto',quantity=1))[0][0]['id']==permanent
        assert next(x for x in auto if x['nation']=='us~permanent')['name']=='США Вечный СБ'
        assert next(x for x in auto if x['nation']=='us~permanent')['min_price']==Decimal('19.00')
        permanent_rows,permanent_count,_=await store.products(42,'aged','us~permanent',2015)
        assert permanent_count==1 and permanent_rows[0]['id']==permanent
        assert all(row['spam_status']=='clear' for row in (await store.products(42,'auto','us~clear'))[0])
        permanent_quote=await store.reserve_bulk(42,'aged','us~permanent',1,2015)
        assert len(permanent_quote['items'])==1 and permanent_quote['items'][0]['account_id']==permanent
        await commerce.remove_from_cart(42,permanent)
        print('PASS: permanent spam groups have separate names, prices, years and bulk selection')
        print('PASS: actual countries, years, Premium, age, cheapest, referral prices and hidden stock')
        # Existing another-user holds are excluded; cancellation leaves earlier cart alone.
        await commerce.add_to_cart(43,one)
        assert next(x for x in await store.countries(42,'auto') if x['nation']=='us~clear')['count']==2
        await commerce.remove_from_cart(43,one)
        await commerce.add_to_cart(42,one)
        cancelled=await store.reserve_bulk(42,'auto','us~clear',2)
        assert cancelled['created_ids']==[two]
        for identity in cancelled['created_ids']: await commerce.remove_from_cart(42,identity)
        async with conn.cursor() as cur:
            await cur.execute('SELECT account_id FROM shopping_cart WHERE user_id=42')
            assert {row[0] for row in await cur.fetchall()}=={one}
        await commerce.remove_from_cart(42,one)
        quote=await store.reserve_bulk(42,'auto','us~clear',2)
        assert {x['account_id'] for x in quote['items']}=={one,two}
        assert quote['total']=='169.58' and quote['rate']=='15'
        balance=(await db.get_user(42))['balance']
        # Removing a discount must not charge more than the confirmed total.
        async with conn.cursor() as cur:
            await cur.execute("UPDATE settings SET `value`='0' WHERE `key`='wholesale_pct'")
        try: await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        except CheckoutError as exc: assert exc.code=='price_changed'
        else: raise AssertionError('Removed discount charged a higher total')
        assert (await db.get_user(42))['balance']==balance
        async with conn.cursor() as cur:
            await cur.execute("UPDATE settings SET `value`='15' WHERE `key`='wholesale_pct'")
        result=await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        assert len(result['order_ids'])==2
        assert (await db.get_user(42))['balance']==balance-Decimal('169.58')
        assert all([await db.get_purchase_for_user(identity,42) for identity in result['order_ids']])
        try: await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        except CheckoutError: pass
        else: raise AssertionError('Repeated purchase succeeded')
        assert (await db.get_user(42))['balance']==balance-Decimal('169.58')
        print('PASS: shared wholesale rules, atomic orders and no repeat debit')
        # Changed prices and expired reservations cannot debit a wallet.
        quote=await store.reserve_bulk(42,'auto','us~clear',1)
        before=(await db.get_user(42))['balance']
        async with conn.cursor() as cur:
            await cur.execute("UPDATE accounts SET registration_date='2021-01-01' WHERE id=%s",(old,))
        try: await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        except CheckoutError as exc: assert exc.code=='terms_changed'
        else: raise AssertionError('Changed registration year accepted')
        assert (await db.get_user(42))['balance']==before
        async with conn.cursor() as cur:
            await cur.execute("UPDATE accounts SET registration_date='2014-01-01' WHERE id=%s",(old,))
        async with conn.cursor() as cur: await cur.execute('UPDATE accounts SET price=price+1 WHERE id=%s',(old,))
        try: await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        except CheckoutError as exc: assert exc.code=='price_changed'
        else: raise AssertionError('Stale price accepted')
        assert (await db.get_user(42))['balance']==before
        await commerce.remove_from_cart(42,old)
        quote=await store.reserve_bulk(42,'auto','kz',1)
        async with conn.cursor() as cur:
            await cur.execute('UPDATE account_reservations SET expires_at=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE account_id=%s',(kz,))
        try: await checkout_cart(42,quote['items'],expected_total=Decimal(quote['total']))
        except CheckoutError as exc: assert exc.code=='reservation_expired'
        else: raise AssertionError('Expired reservation accepted')
        assert (await db.get_user(42))['balance']==before
        print('PASS: stale prices and expired holds leave balances intact')
        # Two buyers cannot reserve the same last Premium item.
        outcomes=await asyncio.gather(store.reserve_bulk(42,'premium','us',1),store.reserve_bulk(43,'premium','us',1),return_exceptions=True)
        assert sum(isinstance(value,dict) for value in outcomes)==1
        assert sum(isinstance(value,CheckoutError) for value in outcomes)==1
        print('PASS: concurrent last-item reservations have one winner')
    finally:
        if db.pool:
            db.pool.close();await db.pool.wait_closed();db.pool=None
        async with conn.cursor() as cur: await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        conn.close()


if __name__=='__main__': asyncio.run(main())
