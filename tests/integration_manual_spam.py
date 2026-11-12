"""Local disposable DB: upload is sellable/unverified, only explicit checks run."""
import asyncio
from pathlib import Path
import sys
from uuid import uuid4
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db
from database import spam_checks,imports,shop_navigation
import aiomysql


async def main():
    name='manual_spam_'+uuid4().hex
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    async def sql(query,args=()):
        async with conn.cursor() as cur:await cur.execute(query,args);return await cur.fetchall()
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,1000),(43,2000)')
        first=await db.add_account('auto','+1','+15550000222','-',74,'SYNTHETIC_MANUAL',90002)
        row=await db.get_account(first)
        assert row['country']=='auto-us-unverified' and row['spam_status']=='not_checked'
        assert not row['spam_requested'] and await spam_checks.claim() is None
        groups=await shop_navigation.countries(43,'auto')
        assert len(groups)==1 and groups[0]['nation']=='us~unverified' and groups[0]['count']==1
        batch=await imports.create(42)
        await imports.add_item(batch,'fixture.session','ready',phone='+15550000333',telegram_id=90003,session='SYNTHETIC_ZIP_SESSION')
        await imports.finish(batch);item=(await imports.preview(42,batch))['items'][0]
        ids=await imports.commit(42,batch,[{'id':item['id'],'price':'59','warranty_hours':24,'category':'auto','password':'-'}])
        assert (await db.get_account(ids[0]))['country']=='auto-us-unverified'
        assert await spam_checks.claim() is None
        assert await spam_checks.enqueue(42,first)==1
        assert await spam_checks.enqueue(42,first)==0
        lease=await spam_checks.claim();assert lease['id']==first
        assert await spam_checks.claim() is None
        assert await spam_checks.finish(lease,{'status':'clear','reason':None})
        assert not await spam_checks.finish(lease,{'status':'permanent'})
        assert (await db.get_account(first))['country']=='auto-us-clear'
        assert await spam_checks.claim() is None
        await sql('UPDATE accounts SET spam_next_check_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 DAY),spam_checked_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 DAY) WHERE id=%s',(first,))
        assert await spam_checks.claim() is None,'Old timestamps must not automatically start another check'
        assert await spam_checks.enqueue(42,first)==1
        lease=await spam_checks.claim();assert lease['id']==first
        assert await spam_checks.finish(lease,{'status':'error','reason':'flood_wait','retry_after':7200})
        await sql('UPDATE accounts SET spam_checked_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 MINUTE) WHERE id=%s',(first,))
        assert await spam_checks.enqueue(42,first)==0
        assert await spam_checks.claim() is None
        # Simulate a legacy initially hidden upload and repeat the additive migration.
        await sql("INSERT INTO categories(slug,name,is_active) VALUES('auto-us-pending','Legacy waiting',0)")
        await sql("UPDATE accounts SET country='auto-us-pending' WHERE id=%s",(ids[0],))
        await sql("DELETE FROM settings WHERE `key`='manual_spam_checks_v1'")
        async with conn.cursor() as cur:await spam_checks.init_schema(cur,name)
        assert (await db.get_account(ids[0]))['country']=='auto-us-unverified'
        assert await spam_checks.claim() is None
        assert (await db.get_user(42))['balance']==1000 and (await db.get_user(43))['balance']==2000
        assert (await db.get_account(first))['price']==74 and (await db.get_account(ids[0]))['price']==59
        print('PASS: upload/ZIP never trigger SpamBot; explicit queue only, one-time result, cooldown/FloodWait, legacy migration and balances preserved')
    finally:
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
