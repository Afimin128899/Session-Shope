"""Real SQL regression checks on a fresh disposable localhost:13307 database only."""
import asyncio
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import AsyncMock, patch
from uuid import uuid4

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
import aiomysql
from test_payments import db
from database import bot_store, commerce, refunds
from miniapp import storage
from services import payments


async def main():
    name = 'bot_reliability_' + uuid4().hex
    connection = await aiomysql.connect(host='127.0.0.1', port=13307, user='root', password='', autocommit=True)
    try:
        db.DB_CONFIG = dict(host='127.0.0.1', port=13307, user='root', password='', db=name, autocommit=True)
        await db.init_db()
        async with connection.cursor() as cur:
            await cur.execute(f'USE `{name}`')
            await cur.execute('INSERT INTO users(id,balance) VALUES(42,10000),(43,0)')
            await cur.execute("INSERT INTO categories(slug,name,is_active) VALUES('bot_test','Тест <bot>',1)")
            await cur.execute('INSERT INTO referrals(referral_id,referrer_id) VALUES(42,43)')
            await cur.execute('UPDATE referral_settings SET discount_pct=5,bonus_pct=5 WHERE id=1')
            for i in range(17):
                await cur.execute("INSERT INTO accounts(country,number,password,price,data,warranty_hours) VALUES('bot_test',%s,'PRIVATE_PASSWORD',100,'PRIVATE_SESSION',24)", (f'+1555000{i:04}',))
            await cur.execute("SELECT id FROM accounts WHERE country='bot_test' ORDER BY id")
            ids = [r[0] for r in await cur.fetchall()]
        first, total, page = await bot_store.products(42, 'bot_test', 0)
        last, _, last_page = await bot_store.products(42, 'bot_test', 99999)
        assert len(first) == 8 and len(last) == 1 and total == 17 and page == 0 and last_page == 2
        assert all(row['price'] == Decimal(95) for row in first)
        assert 'PRIVATE_SESSION' not in str(first) and 'PRIVATE_PASSWORD' not in str(first)
        print('PASS: bounded stock pages, clamped stale pages, shared referral prices, no private list fields')

        quote = await bot_store.product(42, ids[0])
        async def buy():
            try:
                return await storage.checkout(42, ids[0], quote['price'], warranty_hours=24)
            except storage.CheckoutError as error:
                return error.code
        results = await asyncio.gather(buy(), buy())
        assert sum(isinstance(result, dict) for result in results) == 1
        success = next(r for r in results if isinstance(r, dict))
        order = await db.get_purchase_for_user(success['id'], 42)
        assert order['paid_amount'] == Decimal(95) and order['currency'] == 'RUB'
        assert (await db.get_user(42))['balance'] == Decimal(9905)
        print('PASS: concurrent single checkout charges once, stores RUB price and synchronizes with bot orders')

        async with connection.cursor() as cur:
            await cur.execute('UPDATE accounts SET price=200 WHERE id=%s', (ids[1],))
            await cur.execute('UPDATE accounts SET warranty_hours=0 WHERE id=%s', (ids[2],))
        for account, price, expected in [(ids[1], Decimal(95), 'price_changed'), (ids[2], Decimal(95), 'terms_changed')]:
            try:
                await storage.checkout(42, account, price, warranty_hours=24)
            except storage.CheckoutError as error:
                assert error.code == expected
            else:
                raise AssertionError('Stale quote was charged')
        assert (await db.get_user(42))['balance'] == Decimal(9905)
        await commerce.add_to_cart(43, ids[3])
        assert await bot_store.product(42, ids[3]) is None
        assert await bot_store.product(43, ids[3]) is not None
        await commerce.remove_from_cart(43, ids[3])
        print('PASS: price/warranty changes do not debit; live Mini App reservations hide stock in bot')

        try:
            await bot_store.complete_order(43, success['id'])
        except ValueError:
            pass
        else:
            raise AssertionError('Other buyer completed order')
        assert await bot_store.complete_order(42, success['id']) is True
        assert await bot_store.complete_order(42, success['id']) is False
        order = await db.get_purchase_for_user(success['id'], 42)
        assert order['data'] == bot_store.DELETED_SESSION and order['status'] == 'completed'
        await refunds.refund_order(7, success['id'], 'Fixture refund after completion')
        try:
            await bot_store.complete_order(42, success['id'])
        except ValueError:
            pass
        else:
            raise AssertionError('Refunded order was completed')
        order = await db.get_purchase_for_user(success['id'], 42)
        assert order['status'] == 'refunded' and order['data'] == ''
        assert (await db.get_user(42))['balance'] == Decimal(10000)
        assert (await db.get_user(43))['balance'] == 0
        print('PASS: owner-only idempotent completion, refund priority, referral reversal')

        for account_id in ids[4:13]:
            quote = await bot_store.product(42, account_id)
            await storage.checkout(42, account_id, quote['price'], warranty_hours=24)
        orders, total, _ = await bot_store.orders(42)
        second, _, _ = await bot_store.orders(42, 1)
        assert len(orders) == 8 and len(second) == 2 and total == 10
        assert not ({r['id'] for r in orders} & {r['id'] for r in second})
        assert await bot_store.orders(43) == ([], 0, 0)
        assert not any('data' in row or 'password' in row for row in orders)
        print('PASS: large private order history is paged without session/password projection')

        invoice_id = 'fixture-' + uuid4().hex
        await commerce.register_invoice('crypto', invoice_id, 42, Decimal(100))
        before = Decimal(str((await db.get_user(42))['balance']))
        paid = {'invoice_id':invoice_id, 'status':'paid', 'payload':'rub_topup:42:100'}
        with patch.object(payments.cryptopay, 'get_invoice', AsyncMock(return_value=paid)):
            results = await asyncio.gather(payments.check_invoice(42,'crypto',invoice_id), payments.check_invoice(42,'crypto',invoice_id))
        assert sum(bool(r['credited']) for r in results) == 1
        assert (await db.get_user(42))['balance'] == before + Decimal(110)
        assert (await commerce.invoice('crypto',invoice_id,42))['status'] == 'credited'
        assert await commerce.invoice('crypto',invoice_id,43) is None
        print('PASS: concurrent payment checks credit once with first-deposit bonus and private invoice ownership')
        print('All real-DB bot reliability scenarios passed.', flush=True)
    finally:
        if db.pool:
            db.pool.close()
            await db.pool.wait_closed()
            db.pool = None
        async with connection.cursor() as cur:
            await cur.execute(f'DROP DATABASE IF EXISTS `{name}`')
        connection.close()


if __name__ == '__main__':
    asyncio.run(main())
