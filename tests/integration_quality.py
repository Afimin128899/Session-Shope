"""Real MariaDB assertions for warranties, reviews, coupons and private history."""
import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock,patch
from types import SimpleNamespace as NS
from test_payments import db
from handlers import direct_support
from inventory_fixture import confirm_fixture_account
from test_miniapp import signed_data
from database import quality,coupons,commerce,activity,tickets,refunds
from miniapp import storage
from services.operations import payment_health


async def quality_scenarios(session,connection,headers):
    other={'Authorization':'tma '+signed_data(43)}
    async def api(path,body=None,auth=headers,method='GET'):
        r=await session.request(method,'http://127.0.0.1:8085/api/'+path,headers=auth,json=body)
        return r.status,await r.json()
    async with connection.cursor() as cur:
        # Repeatable migration, including the existing orders with unknown warranty.
        await quality.init_schema(cur,db.DB_CONFIG['db'])
        await cur.execute('SELECT warranty_until FROM purchases ORDER BY id LIMIT 1')
        assert (await cur.fetchone())[0] is None
        await cur.execute('UPDATE users SET balance=10000 WHERE id IN (42,43)')
    ids=[]
    for i in range(4):
        await db.add_account('us','US',f'+1555777000{i}','test-quality-password',100,f'quality-session-{i}',telegram_user_id=7770000000+i,is_premium=True)
        async with connection.cursor() as cur:
            await cur.execute('SELECT id,warranty_hours FROM accounts WHERE data=%s',(f'quality-session-{i}',))
            account,hours=await cur.fetchone();ids.append(account);assert hours==24
    for account in ids:
        await confirm_fixture_account(account)
    await quality.edit_characteristics(999,ids[0],hours=24,registered='2020-03-02',premium=True,note='Fixture account')
    result=await storage.checkout(42,ids[0],Decimal(95))
    order=result['id']
    row=await db.get_purchase_for_user(order,42)
    assert quality.warranty(row)['active'] and row['warranty_hours']==24
    original_until=row['warranty_until'];original_attributes=row['attributes_snapshot']
    await quality.edit_characteristics(999,ids[0],hours=72,registered=None,premium=False,note='Changed after sale')
    row=await db.get_purchase_for_user(order,42)
    assert row['warranty_until']==original_until and row['attributes_snapshot']==original_attributes
    status,data=await api(f'orders/{order}')
    assert status==200 and data['warranty']['active'] and data['characteristics']['registration_date']=='2020-03-02'
    assert 'quality-session' not in str(data) and 'test-quality-password' not in str(data['characteristics'])
    print('PASS: new stock gets 24h; old orders do not; order snapshots survive admin edits')
    # HTTP ticket creation is retired; warranty messages go straight to admins.
    assert (await api(f'orders/{order}/warranty-claim',{'body':'Login problem'},auth=other,method='POST'))[0]==410
    assert (await api(f'orders/{order}/warranty-claim',{'body':'Login problem'},method='POST'))[0]==410
    msg=NS(from_user=NS(id=42,full_name='Fixture',username='fixture'),chat=NS(id=42),message_id=1,
           answer=AsyncMock(),bot=NS(send_message=AsyncMock(),copy_message=AsyncMock()))
    with patch.object(direct_support,'ADMIN_IDS',[999]):
        assert await direct_support.relay(msg,order=order,warranty=True)
        msg.bot.copy_message.assert_awaited_once()
        async with connection.cursor() as cur:
            await cur.execute('SELECT COUNT(*) FROM support_tickets WHERE purchase_id=%s',(order,))
            assert (await cur.fetchone())[0]==0
            await cur.execute('UPDATE purchases SET warranty_until=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE id=%s',(order,))
        msg.bot.copy_message.reset_mock()
        assert not await direct_support.relay(msg,order=order,warranty=True)
        msg.bot.copy_message.assert_not_awaited()
    print('PASS: direct warranty messages validate deadline; retired HTTP endpoints create no tickets')
    assert (await api('reviews',{'purchase_id':order,'rating':5,'body':'Forged'},auth=other,method='POST'))[0]==409
    assert (await api('reviews',{'purchase_id':order,'rating':5,'body':'test-quality-password'},method='POST'))[0]==409
    assert (await api('reviews',{'purchase_id':order,'rating':5,'body':'Great <script>window.BAD=1</script>'},method='POST'))[0]==201
    await quality.save_review(42,order,4,'Updated review <script>window.BAD=1</script>')
    data=(await api('reviews'))[1]
    assert data['count']==1 and Decimal(data['average'])==4
    assert len((await quality.reviews(per_page=1))['items'])==1
    assert set(data['items'][0])=={'rating','body','updated_at'}
    print('PASS: only buyer can review; one editable review; public projection hides identifiers and passwords')
    # Race the last coupon activation using separate inventory rows.
    await coupons.create_discount(999,'LAST10',10,1)
    for user,account in [(42,ids[1]),(43,ids[2])]: await commerce.add_to_cart(user,account)
    async def buy(user,account,price,total):
        try: return await storage.checkout_cart(user,[{'account_id':account,'price':price,'warranty_hours':24}],'LAST10',Decimal(total))
        except storage.CheckoutError: return None
    results=await asyncio.gather(buy(42,ids[1],'95.00','85.50'),buy(43,ids[2],'100.00','90.00'))
    assert sum(r is not None for r in results)==1
    for user,account,price,result in zip((42,43),ids[1:3],('95.00','100.00'),results):
        if result is None: await storage.checkout_cart(user,[{'account_id':account,'price':price}])
    async with connection.cursor() as cur:
        await cur.execute("SELECT uses FROM promocodes WHERE code='LAST10'");assert (await cur.fetchone())[0]==1
    print('PASS: last discount activation can be spent by only one concurrent buyer')
    await coupons.create_discount(999,'ROLLBACK10',10,5)
    await commerce.add_to_cart(42,ids[3])
    quote=[{'account_id':ids[3],'price':'95.00','warranty_hours':24}]
    before=(await db.get_user(42))['balance']
    await quality.edit_characteristics(999,ids[3],hours=48,registered=None,premium=None,note='Changed offer')
    try:
        await storage.checkout_cart(42,quote)
    except storage.CheckoutError as exc:
        assert exc.code=='terms_changed'
    else: raise AssertionError('Changed warranty accepted')
    await quality.edit_characteristics(999,ids[3],hours=24,registered=None,premium=None,note='Restored offer')
    status,data=await api('cart/checkout',{'items':quote,'promo_code':'ROLLBACK10','expected_total':'1.00'},method='POST')
    assert status==409 and data['code']=='price_changed'
    async with connection.cursor() as cur:
        await cur.execute(f"CREATE TRIGGER quality_fail BEFORE INSERT ON purchases FOR EACH ROW BEGIN IF NEW.account_id={ids[3]} THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='Test rollback'; END IF; END")
    try:
        await storage.checkout_cart(42,quote,'ROLLBACK10',Decimal('85.50'))
    except Exception: pass
    else: raise AssertionError('Expected rollback')
    async with connection.cursor() as cur:
        await cur.execute('DROP TRIGGER quality_fail')
        await cur.execute("SELECT uses FROM promocodes WHERE code='ROLLBACK10'");assert (await cur.fetchone())[0]==0
        await cur.execute("SELECT COUNT(*) FROM customer_events WHERE reference='ROLLBACK10'");assert (await cur.fetchone())[0]==0
    assert (await db.get_user(42))['balance']==before
    result=await storage.checkout_cart(42,quote,'ROLLBACK10',Decimal('85.50'))
    assert result['paid_amount']=='85.50'
    print('PASS: stale quotes and failed order insert consume neither funds, coupon nor history event')
    async with connection.cursor() as cur:
        await cur.execute("INSERT INTO promocodes(code,value,max_uses) VALUES('BONUS25',25,2)")
    results=await asyncio.gather(coupons.redeem_balance(42,'BONUS25'),coupons.redeem_balance(42,'BONUS25'),return_exceptions=True)
    assert sum(isinstance(r,Decimal) for r in results)==1
    assert await db.check_and_use_promo(42,'BONUS25')==0
    assert (await api('promo/redeem',{'code':'ROLLBACK10'},method='POST'))[0]==409
    print('PASS: balance promo is credited once across concurrent requests; discount cannot credit balance')
    await refunds.refund_order(999,order,'Fixture refund')
    # Refunding an order cannot erase a genuine buyer review.
    assert (await quality.reviews())['count']==1
    await activity.history(42)
    data=await activity.history(42)
    assert {r['kind'] for r in data['items']} >= {'purchase','payment','refund','balance_code'}
    assert any(r['reference']=='BONUS25' and r['amount']==Decimal('25') for r in data['items'])
    assert (await api('activity'))[0]==404
    assert (await api('activity',auth=other))[0]==404
    await payment_health('crypto',False);await payment_health('crypto',False);await payment_health('crypto',False)
    async with connection.cursor() as cur:
        await cur.execute("SELECT active,failures FROM operational_incidents WHERE incident_key='payments:crypto'");assert await cur.fetchone()==(1,3)
    await payment_health('crypto',True)
    async with connection.cursor() as cur:
        await cur.execute("SELECT active FROM operational_incidents WHERE incident_key='payments:crypto'");assert (await cur.fetchone())[0]==0
        # Browser fixtures: remaining stock now shows accurate characteristics.
        await cur.execute("UPDATE accounts SET warranty_hours=24,registration_date='2020-03-02',is_premium=1,attributes_checked_at=UTC_TIMESTAMP() WHERE status='available'")
        await cur.execute("INSERT INTO promocodes(code,value,max_uses,kind) VALUES('BROWSER10',10,10,'discount'),('BROWSER25',25,10,'balance')")
    print('PASS: private activity includes actual refunds and promo credits; incident counters recover')
