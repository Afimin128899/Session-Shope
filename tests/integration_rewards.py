"""Disposable localhost:13307 only. No production credentials are imported."""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db
import aiomysql
from database import rewards,stars
from miniapp import storage

async def main():
    name='rewards_'+uuid4().hex
    connection=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    try:
        db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await rewards.init_schema(cur)
            await cur.execute('INSERT INTO users(id,balance) VALUES(42,1000),(43,1000),(44,1000),(45,1000)')
            await cur.execute("INSERT INTO payment_logs(user_id,amount,currency,method,reference) VALUES(42,50,'RUB','crypto_pay','test'),(43,49.99,'RUB','lave_pay','test2')")
        async def claim():
            try:return await rewards.claim(42)
            except ValueError:return None
        before=(await db.get_user(42))['balance']
        outcomes=await asyncio.gather(claim(),claim())
        assert sum(r is not None for r in outcomes)==1
        result=next(r for r in outcomes if r)
        assert Decimal(1)<=Decimal(result['amount'])<=Decimal(10)
        assert (await db.get_user(42))['balance']==before+Decimal(result['amount'])
        assert not (await rewards.status(42))['eligible']
        assert not (await rewards.status(43))['eligible']
        print('PASS: only one concurrent reward, exact 1–10 range, no reward below50 and persistent72h cooldown')
        invoice=await stars.register_invoice(44,50)
        await stars.credit_payment(44,invoice['invoice_id'],50,'fixture-stars')
        assert (await rewards.status(44))['eligible']
        await stars.refund_payment(invoice['invoice_id'],50,'fixture-stars',44)
        assert not (await rewards.status(44))['eligible']
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO payment_logs(user_id,amount,currency,method,reference,created_at) VALUES(45,100,'RUB','crypto_pay','old',DATE_SUB(UTC_TIMESTAMP(),INTERVAL 4 DAY))")
        assert not (await rewards.status(45))['eligible']
        print('PASS: paidStars count, refundedStars and old deposits are excluded')
        async with connection.cursor() as cur:
            await cur.execute("INSERT INTO categories(slug,name,is_active) VALUES('reward_test','Test',1)")
            ids=[]
            for i in range(3):
                await cur.execute("INSERT INTO accounts(country,number,price,data,warranty_hours) VALUES('reward_test',%s,100,'FAKE_SESSION',24)",(str(i),));ids.append(cur.lastrowid)
            await cur.execute("INSERT INTO promocodes(code,value,max_uses,kind) VALUES('ONE',10,1,'discount'),('ROLLBACK',20,5,'discount')")
        async def buy(account):
            try:return await storage.checkout(42,account,Decimal(100),promo_code='ONE',expected_total=Decimal(90))
            except storage.CheckoutError:return None
        before=(await db.get_user(42))['balance']
        result=await asyncio.gather(buy(ids[0]),buy(ids[1]))
        assert sum(r is not None for r in result)==1
        assert (await db.get_user(42))['balance']==before-Decimal(90)
        async with connection.cursor() as cur:
            await cur.execute("SELECT uses FROM promocodes WHERE code='ONE'");assert (await cur.fetchone())[0]==1
            await cur.execute("CREATE TRIGGER rewards_fail BEFORE INSERT ON purchases FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Fixture failure'")
        before=(await db.get_user(42))['balance']
        try:await storage.checkout(42,ids[2],Decimal(100),promo_code='ROLLBACK',expected_total=Decimal(80))
        except Exception:pass
        else:raise AssertionError('Expected insert failure')
        assert (await db.get_user(42))['balance']==before
        async with connection.cursor() as cur:
            await cur.execute("SELECT uses FROM promocodes WHERE code='ROLLBACK'");assert (await cur.fetchone())[0]==0
        print('PASS: one-use coupon spent by one buyer; failed purchase rolls back balance, stock and code')
    finally:
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        async with connection.cursor() as cur:await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()

if __name__=='__main__':asyncio.run(main())
