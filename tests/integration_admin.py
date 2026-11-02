"""Real DB/admin API tests; session verification uses an explicit local fixture."""
import asyncio
import io
import zipfile
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from test_payments import config,db
from test_miniapp import signed_data
from database import imports,admin_web
from services import telethon_auth


def fixture_zip(names=('one.session','two.session','duplicate.session','broken.session')):
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',compression=zipfile.ZIP_STORED) as z:
        for name in names:
            payload=b'broken' if name=='broken.session' else b'SQLite format 3\x00'+(b'ONE' if name in {'one.session','duplicate.session'} else b'TWO')
            z.writestr(name,payload)
    return result.getvalue()


async def fixture_verify(path,metadata=None):
    data=Path(path).read_bytes()
    tag=1 if b'ONE' in data else 2
    metadata.update(telegram_user_id=8800000000+tag,is_premium=tag==1)
    return 'TEST-SESSION-PRIVATE-'+str(tag),'+1555888000'+str(tag),None


async def admin_scenarios(session,connection,headers):
    config.ADMIN_IDS=[42,44]
    other={'Authorization':'tma '+signed_data(43)};second={'Authorization':'tma '+signed_data(44)}
    async def api(path,body=None,method='GET',auth=headers):
        r=await session.request(method,'http://127.0.0.1:8085/api/admin/'+path,headers=auth,json=body)
        return r.status,await r.json()
    for path in ['overview','stock','orders','tickets','settings','users','audit','imports','approvals','categories','promos']:
        assert (await api(path,auth=other))[0]==403
    assert (await api('overview'))[0]==200
    for path in ['stock','orders','categories','settings','promos','approvals','audit']:
        status,data=await api(path);assert status==200,(path,data)
        assert 'quality-session' not in str(data) and 'NEVER_EXPOSE_SESSION' not in str(data)
    print('PASS: admin role enforced across routes; stock/orders never project session data')
    with patch.object(telethon_auth,'import_session_file',fixture_verify):
        r=await session.post('http://127.0.0.1:8085/api/admin/imports',headers=headers|{'Content-Type':'application/zip'},data=fixture_zip())
        assert r.status==202,await r.text()
        batch=(await r.json())['batch_id']
        for _ in range(100):
            status,preview=await api('imports/'+batch)
            if preview['status']!='checking': break
            await asyncio.sleep(.02)
        assert preview['status']=='ready',preview
    assert [r['state'] for r in preview['items']]==['ready','ready','duplicate','error']
    assert 'TEST-SESSION-PRIVATE' not in str(preview) and 'session_data' not in str(preview)
    assert (await api('imports/'+batch,auth=second))[0]==400
    assert (await api('imports/'+batch+'/commit',{'items':[]},'POST',auth=second))[0]==400
    selections=[{'id':r['id'],'price':'200.00','category':'us','warranty_hours':24} for r in preview['items'] if r['state']=='ready']
    bad=[dict(i) for i in selections];bad[-1]['category']='missing-category'
    assert (await api('imports/'+batch+'/commit',{'items':bad},'POST'))[0]==400
    async with connection.cursor() as cur:
        await cur.execute('SELECT COUNT(*) FROM accounts WHERE telegram_user_id IN (8800000001,8800000002)');assert (await cur.fetchone())[0]==0
    status,result=await api('imports/'+batch+'/commit',{'items':selections},'POST')
    assert status==201,result
    ids=result['account_ids']
    assert (await api('imports/'+batch+'/commit',{'items':selections},'POST'))[0]==400
    async with connection.cursor() as cur:
        await cur.execute('SELECT COUNT(*) FROM import_items WHERE batch_id=%s AND session_data IS NOT NULL',(batch,));assert (await cur.fetchone())[0]==0
    print('PASS: ZIP preview verifies/deduplicates, hides secrets, binds owner and publishes atomically exactly once')
    try: await db.add_account('us','US','+15558880001','-',200,'DIFFERENT-SESSION',telegram_user_id=8800000001)
    except ValueError: pass
    else: raise AssertionError('Single-account path bypassed deduplication')
    # Two confirmed drafts racing for the same genuine identity.
    batches=[]
    for admin in (42,44):
        batch=await imports.create(admin)
        await imports.add_item(batch,'race.session','ready',phone='+15558880003',telegram_id=8800000003,premium=False,session='RACE-PRIVATE-SESSION')
        await imports.finish(batch)
        item=(await imports.preview(admin,batch))['items'][0]
        batches.append((admin,batch,[{'id':item['id'],'price':'100','category':'us','warranty_hours':24}]))
    results=await asyncio.gather(*(imports.commit(*args) for args in batches),return_exceptions=True)
    assert sum(isinstance(r,list) for r in results)==1
    print('PASS: concurrent drafts and old bot upload cannot duplicate a verified account')
    expired=await imports.create(42)
    try: await imports.create(42)
    except ValueError: pass
    else: raise AssertionError('Overlapping verification accepted')
    await imports.add_item(expired,'expired.session','ready',phone='+15558880009',telegram_id=8800000009,session='EXPIRED-PRIVATE')
    await imports.finish(expired)
    async with connection.cursor() as cur: await cur.execute('UPDATE import_batches SET expires_at=UTC_TIMESTAMP()-INTERVAL 1 SECOND WHERE id=%s',(expired,))
    try: await imports.preview(42,expired)
    except ValueError: pass
    else: raise AssertionError('Expired draft visible')
    await imports.cleanup()
    async with connection.cursor() as cur:
        await cur.execute('SELECT session_data FROM import_items WHERE batch_id=%s',(expired,));assert (await cur.fetchone())[0] is None
    discarded=await imports.create(42)
    await imports.add_item(discarded,'discarded.session','ready',phone='+15558880008',telegram_id=8800000008,session='DISCARDED-PRIVATE')
    await imports.discard(42,discarded)
    async with connection.cursor() as cur:
        await cur.execute('SELECT session_data FROM import_items WHERE batch_id=%s',(discarded,));assert (await cur.fetchone())[0] is None
    print('PASS: overlapping checks rejected; discarded and expired drafts lose session material')

    before=(await db.get_user(43))['balance'];body={'amount':'25','currency':'RUB','mode':'add','operation_id':'f'*32}
    assert (await api('users/43/balance',body,'POST'))[0]==200
    assert (await api('users/43/balance',body,'POST'))[0]==400
    assert (await db.get_user(43))['balance']==before+Decimal(25)
    status,data=await api('stock/'+str(ids[0]),{'price':'150.00','category':'us','warranty_hours':48,'registration_date':'2020-01-01','is_premium':True,'note':'Edited via API'},'PATCH')
    assert status==200,data
    stock=await db.get_account(ids[0]);assert stock['price']==150 and stock['warranty_hours']==48
    from database import commerce
    await commerce.add_to_cart(43,ids[0])
    assert (await api('stock/'+str(ids[0]),{'price':'100.00','category':'us','warranty_hours':24,'note':''},'PATCH'))[0]==400
    assert (await api('stock/'+str(ids[0]),method='DELETE'))[0]==400
    await commerce.remove_from_cart(43,ids[0])
    assert (await api('categories',{'slug':'admin-test','name':'Тестовая категория','active':True},'POST'))[0]==200
    assert (await api('promos',{'kind':'balance','code':'WEBBAL25','percent':'25','limit':10},'POST'))[0]==200
    assert (await api('promos/disable',{'code':'WEBBAL25'},'POST'))[0]==200
    assert (await api('settings',{'support_hours':'Fixture hours','support_eta':'Fixture ETA','low_stock_limit':'3.00'},'POST'))[0]==200
    inbox=(await api('tickets'))[1]['items']
    if inbox:
        ticket=inbox[0]['id']
        assert (await api('tickets/'+str(ticket)))[0]==200
        assert (await api('tickets/'+str(ticket)+'/reply',{'body':'Fixture admin reply'},'POST'))[0]==200
        assert (await api('tickets/'+str(ticket)+'/close',{},'POST'))[0]==200
    r=await session.get('http://127.0.0.1:8085/api/shop-info',headers=headers);assert r.status==200,await r.text()
    print('PASS: web editing, category/promo/settings management, support replies and replay-safe balance update')
    # Browser uploads get distinct fixture identities, never actual Telegram sessions.
    async def browser_verifier(path,metadata=None):
        data=Path(path).read_bytes();tag=1 if b'ONE' in data else 2
        metadata.update(telegram_user_id=8900000000+tag,is_premium=tag==1)
        return 'BROWSER-SESSION-PRIVATE-'+str(tag),'+1555899000'+str(tag),None
    telethon_auth.import_session_file=browser_verifier
    return ids
