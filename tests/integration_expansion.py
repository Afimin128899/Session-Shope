"""Actual transactions for the 4.2 inventory workflows."""
from decimal import Decimal
from unittest.mock import AsyncMock
from test_payments import db
from inventory_fixture import confirm_fixture_account
from database import expansion,commerce,tickets
from miniapp import storage


async def expansion_scenarios(connection):
    async with connection.cursor() as cur:
        await cur.execute('UPDATE users SET balance=10000 WHERE id=42')
    ids=[]
    for i in range(3):
        await db.add_account('us','US',f'+1555666100{i}','expansion-password',300,'expand-fixture-'+str(i),telegram_user_id=6660000000+i,is_premium=True)
        async with connection.cursor() as cur:
            await cur.execute('SELECT id FROM accounts WHERE data=%s',('expand-fixture-'+str(i),));ids.append((await cur.fetchone())[0])
    for account in ids:
        await confirm_fixture_account(account)
    await expansion.bulk_edit(999,ids,'features_note','Checked in batch')
    for item in ids[:2]: await commerce.add_to_cart(42,item)
    quotes=[{'account_id':i,'price':'285.00','warranty_hours':24} for i in ids[:2]]
    before=(await db.get_user(42))['balance']
    try: await storage.checkout_cart(42,quotes,expected_total=Decimal('570'))
    except storage.CheckoutError: pass
    else: raise AssertionError('Unconfirmed wholesale discount accepted')
    result=await storage.checkout_cart(42,quotes,expected_total=Decimal('484.50'))
    assert (await db.get_user(42))['balance']==before-Decimal('484.50')
    order=result['order_ids'][0]
    ticket=await tickets.create_ticket(42,order,'Screenshot',photo='test-photo-id')
    assert (await tickets.history(ticket,42))[0]['photo_id']=='test-photo-id'
    assert not await tickets.history(ticket,43)
    await expansion.replace(999,order,ids[2],'Warranty replacement')
    assert (await db.get_purchase_for_user(order,42))['account_id']==ids[2]
    async with connection.cursor() as cur:
        await cur.execute('SELECT status,password,data FROM accounts WHERE id=%s',(ids[0],));assert await cur.fetchone()==('replaced',None,None)
    try: await expansion.replace(999,order,ids[1],'Duplicate replacement')
    except ValueError: pass
    else: raise AssertionError('Duplicate replacement accepted')
    # Configure a low threshold in the disposable fixture to test approval.
    async with connection.cursor() as cur:
        await cur.execute("UPDATE settings SET `value`='200' WHERE `key`='refund_approval_threshold'")
    pending=await expansion.request_refund(999,order,'Approved fixture refund')
    assert pending['pending']
    try: await expansion.approve_refund(999,order)
    except ValueError: pass
    else: raise AssertionError('Self approval accepted')
    returned=await expansion.approve_refund(998,order)
    assert Decimal(returned['amount'])==Decimal('242.25')
    assert await expansion.approve_refund(998,order) is None
    try: await expansion.bulk_edit(999,ids,'price','100')
    except ValueError: pass
    else: raise AssertionError('Batch changed sold stock')
    found=await storage.orders(42,query=str(order))
    assert [r['id'] for r in found['items']]==[order]
    filtered=await storage.catalog(42,premium=0,min_age=365)
    assert not filtered['items']
    bot=AsyncMock()
    await expansion.stock_notifications(bot,[999]);count=bot.send_message.await_count
    await expansion.stock_notifications(bot,[999]);assert bot.send_message.await_count==count
    # Leave stock totals and default policy unchanged for existing browser fixtures.
    async with connection.cursor() as cur:
        await cur.execute("UPDATE settings SET `value`='600' WHERE `key`='refund_approval_threshold'")
    print('PASS: wholesale total, private photo, atomic replacement, dual approval, bulk protection, order search and stock alert cooldown')
