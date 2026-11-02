"""Extra real MariaDB/API scenarios; run through integration_miniapp.py."""
import asyncio
from decimal import Decimal
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from test_payments import db
from test_miniapp import signed_data
from database import commerce
from services import payments, market_notifications

BASE='http://127.0.0.1:8085/api/'


async def marketplace_scenarios(session, connection, headers):
    other={'Authorization':'tma '+signed_data(43)}
    async def request(path, body=None, auth=headers, method='GET'):
        res=await session.request(method,BASE+path,headers=auth,json=body)
        return res.status,await res.json()
    async with connection.cursor() as cur:
        await cur.execute('UPDATE users SET balance=10000 WHERE id IN (42,43)')
        ids=[]
        for i in range(3):
            await cur.execute("INSERT INTO accounts (country,number,password,price,data,telegram_user_id,compare_price) VALUES ('us',%s,'test',100,'NEVER_EXPOSE_SESSION',%s,200)", ('+1555999000'+str(i),8880000000+i))
            ids.append(cur.lastrowid)
    status,data=await request('catalog?min_price=90&max_price=96&sort=discount&q='+str(8880000000))
    assert status==200 and [i['id'] for i in data['items']]==[ids[0]]
    assert data['items'][0]['product_id']==f'SBA-{ids[0]:06d}' and data['items'][0]['telegram_user_id']=='8880000000'
    assert Decimal(data['items'][0]['discount'])==Decimal('52.5')
    assert (await request('catalog?min_price=NaN'))[0]==400
    print('PASS: both IDs, price-range validation and historical discount ordering')
    results=await asyncio.gather(request('cart',{'account_id':ids[0]},method='POST'),request('cart',{'account_id':ids[0]},auth=other,method='POST'))
    assert sorted(r[0] for r in results)==[200,409]
    owner=headers if results[0][0]==200 else other
    outsider=other if owner is headers else headers
    owner_id=42 if owner is headers else 43
    await request('cart',{'account_id':ids[0]},auth=owner,method='DELETE')
    assert (await request('cart',{'account_id':ids[0]},method='POST'))[0]==200
    assert (await request('purchase',{'account_id':ids[0],'price':'100.00'},auth=other,method='POST'))[0]==409
    assert await db.buy_account(43,ids[0],Decimal(100),'2026-01-01 00:00:00') is None
    assert await db.buy_account_with_referral(43,ids[0],100,'2026-01-01 00:00:00',5,5) is None
    assert ids[0] not in {i['id'] for i in (await request('catalog',auth=other))[1]['items']}
    # Refresh and repeated clicks cannot extend an active reservation.
    async with connection.cursor() as cur:
        await cur.execute('SELECT expires_at FROM account_reservations WHERE account_id=%s',(ids[0],));expiry=(await cur.fetchone())[0]
    await request('cart',{'account_id':ids[0]},method='POST')
    async with connection.cursor() as cur:
        await cur.execute('SELECT expires_at FROM account_reservations WHERE account_id=%s',(ids[0],));assert (await cur.fetchone())[0]==expiry
    assert (await request('cart',{'account_id':ids[0]},auth=other,method='DELETE'))[0]==200
    assert (await request('cart'))[1]['items'][0]['reserved_until']
    print('PASS: concurrent reservation has one owner; bot and web checkout honor it; outsiders cannot release it')
    await request('cart',{'account_id':ids[1]},method='POST')
    before=(await db.get_user(42))['balance']
    quotes=[{'account_id':i,'price':'95.00'} for i in ids[:2]]
    stale=[dict(i) for i in quotes];stale[1]['price']='1.00'
    status,result=await request('cart/checkout',{'items':stale},method='POST')
    assert status==409 and result['code']=='price_changed' and (await db.get_user(42))['balance']==before
    async with connection.cursor() as cur:
        await cur.execute('UPDATE account_reservations SET expires_at=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE account_id=%s',(ids[1],))
    assert (await request('cart/checkout',{'items':quotes},method='POST'))[0]==409
    await request('cart',{'account_id':ids[1]},method='POST')
    results=await asyncio.gather(request('cart/checkout',{'items':quotes},method='POST'),request('cart/checkout',{'items':quotes},method='POST'))
    assert sorted(r[0] for r in results)==[201,409]
    assert (await db.get_user(42))['balance']==before-Decimal(190)
    assert not (await request('cart'))[1]['items']
    print('PASS: stale price and expired reservation charge nothing; concurrent bulk checkout commits exactly once')
    assert (await request('favorites',{'account_id':ids[2],'enabled':True},method='POST'))[0]==200
    assert len((await request('favorites'))[1]['items'])==1
    async with connection.cursor() as cur:
        await cur.execute('UPDATE accounts SET price=80 WHERE id=%s',(ids[2],))
    bot=AsyncMock()
    await market_notifications.price_alerts(bot);await market_notifications.price_alerts(bot)
    assert bot.send_message.await_count==1
    await request('favorites',{'account_id':ids[2],'enabled':False},method='POST')
    await market_notifications.price_alerts(bot)
    assert bot.send_message.await_count==1
    print('PASS: opt-in price alert is sent once; removing favorite revokes subscription')
    await commerce.register_invoice('crypto','test-auto-1',42,Decimal(100))
    row=await commerce.invoice('crypto','test-auto-1',42)
    assert await commerce.lease_invoice('crypto','test-auto-1')
    assert not await commerce.lease_invoice('crypto','test-auto-1')
    bad={'invoice_id':'test-auto-1','status':'paid','payload':'rub_topup:43:100.00'}
    try: await payments.settle_invoice(row,bad)
    except ValueError: pass
    else: raise AssertionError('wrong owner accepted')
    before=(await db.get_user(42))['balance']
    paid=bad|{'payload':'rub_topup:42:100.00'}
    result=await payments.settle_invoice(row,paid)
    assert result is not None
    assert await payments.settle_invoice(row,paid) is None
    assert (await db.get_user(42))['balance']==before+Decimal(str(result[0]))
    assert (await request('invoices/crypto/test-auto-1',auth=other))[0]==404
    assert (await request('invoices/crypto/test-auto-1'))[1]['status']=='credited'
    print('PASS: persistent invoice lease, owner validation, automatic credit idempotency and private status')
    bot=AsyncMock()
    with patch.object(market_notifications,'ADMIN_IDS',[999]):
        now=datetime.now(market_notifications.MOSCOW).replace(hour=10)
        await market_notifications.send_reports(bot,now);await market_notifications.send_reports(bot,now)
    assert bot.send_message.await_count==1
    assert 'МСК' in bot.send_message.call_args.args[1]
    print('PASS: daily admin report survives repeat worker runs without duplicate delivery')
