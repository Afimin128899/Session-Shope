"""Real financial tests on a disposable localhost:13307 DB; never loads repository .env."""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from uuid import uuid4

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import aiomysql
from test_payments import db
from database import stars,commerce


async def main():
    name='stars_integration_'+uuid4().hex
    connection=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    try:
        db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await stars.init_schema(cur,name)
            await stars.init_schema(cur,name)
            await cur.execute('INSERT INTO users(id,balance) VALUES(42,0),(43,0)')
        invoice=await stars.register_invoice(42,100)
        identity=invoice['invoice_id']
        assert invoice['amount']=='120.00'
        await stars.check_precheckout(42,'sband_stars:'+identity,'XTR',100)
        for user,currency,count in ((43,'XTR',100),(42,'RUB',100),(42,'XTR',101)):
            try:await stars.check_precheckout(user,'sband_stars:'+identity,currency,count)
            except ValueError:pass
            else:raise AssertionError('Invalid pre-checkout accepted')
        print('PASS: repeated additive schema, owner/count/currency-bound native invoices at exact rate')

        results=await asyncio.gather(stars.credit_payment(42,identity,100,'charge-one'),stars.credit_payment(42,identity,100,'charge-one'))
        assert sum(result is not None for result in results)==1
        user=await db.get_user(42)
        assert user['balance']==Decimal(120) and user['first_deposit_bonus_used']==0
        assert (await commerce.invoice('stars',identity,42))['status']=='credited'
        async with connection.cursor() as cur:
            await cur.execute("SELECT COUNT(*),SUM(amount) FROM payment_logs WHERE method='stars_pay'")
            assert await cur.fetchone()==(1,Decimal(120))
        print('PASS: duplicate/concurrent charge credits exactly once, no first-deposit bonus consumed')

        await stars.credit_payment(42,identity,100,'charge-two')
        assert (await db.get_user(42))['balance']==Decimal(240)
        results=await asyncio.gather(stars.refund_payment(identity,100,'charge-one'),stars.refund_payment(identity,100,'charge-one'))
        assert sum(result is not None for result in results)==1
        assert (await db.get_user(42))['balance']==Decimal(120)
        assert (await commerce.invoice('stars',identity,42))['credited_amount']==Decimal(120)
        async with connection.cursor() as cur:await cur.execute('UPDATE users SET balance=0 WHERE id=42')
        await stars.refund_payment(None,100,'charge-two',user_id=42)
        assert (await db.get_user(42))['balance']==Decimal(-120)
        assert (await commerce.invoice('stars',identity,42))['status']=='refunded'
        print('PASS: distinct real charges each credit; refunds reverse once and retain debt if funds were spent')

        before=(await db.get_user(42))['balance']
        tombstone=await stars.register_invoice(42,10)
        await stars.refund_payment(tombstone['invoice_id'],10,'refund-first')
        await stars.credit_payment(42,tombstone['invoice_id'],10,'refund-first')
        assert (await db.get_user(42))['balance']==before
        unmatched=await stars.register_invoice(42,10)
        await stars.record_unmatched_refund(42,10,'missing-payload')
        assert (await stars.charge_info('missing-payload'))['invoice_id'] is None
        await stars.credit_payment(42,unmatched['invoice_id'],10,'missing-payload')
        record=await stars.charge_info('missing-payload')
        assert record['invoice_id']==unmatched['invoice_id'] and record['refunded_seen'] and record['paid_seen']
        assert (await db.get_user(42))['balance']==before
        print('PASS: refunded-before-paid and no-payload refund tombstones never resurrect money')

        late=await stars.register_invoice(42,1)
        async with connection.cursor() as cur:
            await cur.execute("UPDATE payment_invoices SET expires_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 HOUR),status='expired' WHERE provider='stars' AND invoice_id=%s",(late['invoice_id'],))
        try:await stars.check_precheckout(42,'sband_stars:'+late['invoice_id'],'XTR',1)
        except ValueError:pass
        else:raise AssertionError('Expired invoice pre-checkout accepted')
        assert await stars.credit_payment(42,late['invoice_id'],1,'late-charge')==Decimal('1.20')
        await stars.credit_payment(42,late['invoice_id'],1,'Charge-Case')
        await stars.credit_payment(42,late['invoice_id'],1,'charge-case')
        assert (await db.get_user(42))['balance']==before+Decimal('3.60')
        print('PASS: paid receipts arriving late are honored and charge IDs remain case-sensitive')

        rollback=await stars.register_invoice(42,10)
        before=(await db.get_user(42))['balance']
        async with connection.cursor() as cur:
            await cur.execute("""CREATE TRIGGER stars_log_failure BEFORE INSERT ON payment_logs FOR EACH ROW BEGIN
                IF NEW.reference='rollback-charge' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Fixture failure'; END IF; END""")
        try:await stars.credit_payment(42,rollback['invoice_id'],10,'rollback-charge')
        except Exception:pass
        else:raise AssertionError('Intentional ledger failure did not abort transaction')
        assert (await db.get_user(42))['balance']==before
        assert await stars.charge_info('rollback-charge') is None
        async with connection.cursor() as cur:await cur.execute('DROP TRIGGER stars_log_failure')
        assert await stars.credit_payment(42,rollback['invoice_id'],10,'rollback-charge')==Decimal(12)
        print('PASS: log failure rolls back balance, charge and replay marker together; retry recovers')
        print('All real-DB Stars ledger scenarios passed.',flush=True)
    finally:
        if db.pool:
            db.pool.close();await db.pool.wait_closed();db.pool=None
        async with connection.cursor() as cur:await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__=='__main__':asyncio.run(main())
