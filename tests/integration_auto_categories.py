"""Disposable localhost MariaDB :13307, fake verified SpamBot reports; no external API.

--serve retains the fixture on :8093 for tests/auto_categories_browser.cjs.
"""
import asyncio
from decimal import Decimal as D
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from uuid import uuid4
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import db,config
from test_miniapp import TEST_TOKEN,signed_data
from database import spam_checks,admin_tools,imports,admin_web
from services import payments
from miniapp import storage
from miniapp.server import create_app
from aiohttp import web,ClientSession
import aiomysql


async def main():
    name='auto_category_'+uuid4().hex
    config.ADMIN_IDS=[42];config.BOT_TOKEN=TEST_TOKEN
    db.DB_CONFIG=dict(host='127.0.0.1',port=13307,user='root',password='',db=name,autocommit=True)
    conn=await aiomysql.connect(host='127.0.0.1',port=13307,user='root',password='',autocommit=True)
    runner=None
    async def sql(query,args=()):
        async with conn.cursor() as cur:await cur.execute(query,args);return await cur.fetchall()
    async def balance(user):return D(str((await db.get_user(user))['balance']))
    async def create(index):return await db.add_account('auto','+56',f'+5691234{index:04}', '-',100,'FAKE_TEST_SESSION_'+str(index),80000+index)
    async def row(account):return await db.get_account(account)
    def report(message):print('PASS: '+message,flush=True)
    try:
        await db.init_db();await sql(f'USE `{name}`')
        await sql('INSERT INTO users(id,balance) VALUES(42,500),(43,1000)')
        for mode,amount,expected in [('set','1000000','1000000'),('add','250000.00000001','1250000.00000001'),('set','-50','-50')]:
            await admin_tools.change_balance(42,43,amount,'RUB',mode)
            assert await balance(43)==D(expected)
        await admin_tools.change_balance(42,43,'1000','RUB','set')
        results=await asyncio.gather(admin_tools.change_balance(42,43,'100001','RUB','add',request_key='a'*32),admin_tools.change_balance(42,43,'100001','RUB','add',request_key='a'*32),return_exceptions=True)
        assert sum(isinstance(result,ValueError) for result in results)==1 and await balance(43)==101001
        before=await balance(43)
        try:await admin_tools.change_balance(42,43,'9999999999.99999999','RUB','add')
        except ValueError:pass
        else:raise AssertionError('Overflow accepted')
        assert await balance(43)==before
        try:payments.parse_amount('10000.01','platega')
        except ValueError:pass
        else:raise AssertionError('SBP cap changed')
        report('Admin can set/add balances above RUB 10,000 and set debts, exact precision/audit/idempotency remain; SBP still caps NEW invoices at RUB 10,000')

        identities=[await create(index) for index in range(1,7)]
        assert identities[0]==1 and all([(await row(i))['country']=='auto-cl-pending' for i in identities])
        assert not (await storage.catalog(43))['items']
        await admin_web.edit_stock(42,identities[0],{'price':'100','warranty_hours':24,'category':'auto-cl-pending'})
        leases=[await spam_checks.claim() for _ in identities]
        statuses=['clear','permanent','limited','unknown','error','clear']
        for lease,status in zip(leases,statuses):
            assert await spam_checks.finish(lease,{'status':status,'reason':'unrecognized' if status=='unknown' else 'timeout' if status=='error' else None})
            assert not await spam_checks.finish(lease,{'status':'clear','reason':None})
        for i,status in zip(identities,statuses):
            expected='unverified' if status in {'unknown','error'} else status
            assert (await row(i))['country']=='auto-cl-'+expected
        assert (await sql("SELECT COUNT(*) FROM categories WHERE slug='auto-cl-clear'"))[0][0]==1
        catalog=(await storage.catalog(43))['items']
        assert {i['id'] for i in catalog}==set(identities)
        assert next(i for i in catalog if i['id']==1)['product_id']=='#01'
        assert next(i for i in catalog if i['id']==2)['characteristics']['spam_check']['status']=='permanent'
        assert all('SBA-' not in i['product_id'] for i in catalog)
        try:await db.update_account_country(identities[1],'auto-cl-clear')
        except ValueError:pass
        else:raise AssertionError('Permanent account mislabeled clear')
        report('Chile clear/permanent/general limits use distinct reusable categories; unrecognized/error stock sells with an explicit unverified label; IDs are #01/#02 and false manual moves are rejected')

        batch=await imports.create(42)
        await imports.add_item(batch,'chile.session','ready',phone='+56999887766',telegram_id=123456,session='FAKE_IMPORTED_SESSION')
        await imports.finish(batch)
        item=(await imports.preview(42,batch))['items'][0]
        imported=await imports.commit(42,batch,[{'id':item['id'],'price':'150','category':'auto','warranty_hours':24,'spam_status':'clear'}])
        assert (await row(imported[0]))['country']=='auto-cl-pending'
        for phone in ['+79991234567','+380501234567']:
            try:await db.add_account('auto','',phone,'-',100,'FORBIDDEN_FIXTURE',90001)
            except ValueError:pass
            else:raise AssertionError('Forbidden phone accepted')
        report('ZIP publication also waits for a real check; client-supplied clean status cannot bypass it; RF/Ukraine phone restrictions remain active')

        # A migrated legacy product queues a fresh check; its old category name is not evidence.
        await sql("INSERT INTO accounts(country,number,price,data,telegram_user_id,spam_next_check_at) VALUES('us','+56911223344',100,'LEGACY_TEST_SESSION',912345,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 DAY))")
        legacy=(await sql("SELECT id FROM accounts WHERE data='LEGACY_TEST_SESSION'"))[0][0]
        await sql("DELETE FROM settings WHERE `key`='auto_spam_categories_v1'")
        async with conn.cursor() as cur:await spam_checks.init_schema(cur,name)
        assert (await sql('SELECT spam_next_check_at<=UTC_TIMESTAMP() FROM accounts WHERE id=%s',(legacy,)))[0][0]
        # Consume the imported pending item and legacy item from the queue.
        for _ in range(2):
            lease=await spam_checks.claim();assert lease
            assert await spam_checks.finish(lease,{'status':'clear','reason':None})
        assert (await row(legacy))['country']=='auto-cl-clear'
        report('First upgrade queues existing unsold stock for fresh country/status grouping; stale lease results cannot overwrite the completed category')

        # Upgrade previously hidden failed stock, preserve admin-disabled destination.
        await sql("UPDATE accounts SET country='auto-cl-pending' WHERE id=%s", (identities[3],))
        await sql("DELETE FROM settings WHERE `key`='unverified_stock_v1'")
        async with conn.cursor() as cur: await spam_checks.init_schema(cur,name)
        assert (await row(identities[3]))['country']=='auto-cl-unverified'
        cats=(await storage.catalog(43))['categories']
        assert len(cats)>=35
        clear_cat=next(c for c in cats if c['slug']=='auto-cl-clear')
        assert D(clear_cat['min_price'])==100
        from database import bot_store
        bot_categories=[]
        first,total,_=await bot_store.categories(43)
        bot_categories.extend(first)
        for page in range(1,(total+bot_store.PAGE_SIZE-1)//bot_store.PAGE_SIZE):
            more,_,_=await bot_store.categories(43,page)
            bot_categories.extend(more)
        assert {c['slug'] for c in bot_categories}=={c['slug'] for c in cats}
        assert any(c['count']==0 and c['min_price'] is None for c in bot_categories)
        assert [int(c['count']) for c in bot_categories]==sorted([int(c['count']) for c in bot_categories],reverse=True)

        assert [int(c['count']) for c in cats]==sorted([int(c['count']) for c in cats],reverse=True)
        await sql("UPDATE categories SET is_active=0 WHERE slug='auto-cl-unverified'")
        await sql("DELETE FROM settings WHERE `key`='unverified_stock_v1'")
        async with conn.cursor() as cur: await spam_checks.init_schema(cur,name)
        assert (await sql("SELECT is_active FROM categories WHERE slug='auto-cl-unverified'"))[0][0]==0
        await sql("UPDATE categories SET is_active=1 WHERE slug='auto-cl-unverified'")
        report('Popular country seed, stock-first sorting and failed-stock migration work; disabled destinations stay disabled')

        runner=web.AppRunner(create_app(enable_cart=True,customer_enabled=True,admin_enabled=True,token=TEST_TOKEN,bot=NS(),bot_username='auto_fixture_bot'),access_log=None)
        await runner.setup();await web.TCPSite(runner,'127.0.0.1',8093).start()
        async with ClientSession() as client:
            headers={'Authorization':'tma '+signed_data(43)}
            response=await client.post('http://127.0.0.1:8093/api/admin/users/43/balance',headers=headers,json={'mode':'set','currency':'RUB','amount':'999999','operation_id':'b'*32})
            assert response.status==403 and await balance(43)==101001
            response=await client.get('http://127.0.0.1:8093/api/products/1',headers=headers)
            assert response.status==200,(response.status,await response.text())
            assert (await response.json())['product_id']=='#01'
        report('Signed customer cannot adjust a balance; customer product API shows the compact ID and verified category')
        purchase_id=await create(99)
        lease=await spam_checks.claim();assert lease['id']==purchase_id
        assert await spam_checks.finish(lease,{'status':'permanent','reason':None})
        order=await storage.checkout(43,purchase_id,D(100),spam_status='permanent')
        import json
        saved_order=await db.get_purchase_for_user(order['id'],43)
        assert json.loads(saved_order['attributes_snapshot'])['spam_status']=='permanent'
        assert not await spam_checks.finish(lease,{'status':'clear','reason':None})
        report('A purchased permanent-limit account retains its actual spam status in the immutable order snapshot')
        unchecked=await storage.checkout(43,identities[4],D(100),spam_status='error')
        snapshot=await db.get_purchase_for_user(unchecked['id'],43)
        assert json.loads(snapshot['attributes_snapshot'])['spam_status']=='error'
        report('Failed SpamBot check can be purchased and preserves the error status in the receipt')
        from database import sections,tickets
        from database.support_schema import init_support_schema
        await sql('ALTER TABLE support_tickets MODIFY purchase_id INT NOT NULL')
        async with conn.cursor() as cur:await init_support_schema(cur,name)
        async with ClientSession() as client:
            own={'Authorization':'tma '+signed_data(43)}
            foreign={'Authorization':'tma '+signed_data(44)}
            admin={'Authorization':'tma '+signed_data(42)}
            base='http://127.0.0.1:8093/api/'
            # Real rows verify ownership, cursor pagination and exclusion of rewards/refunds.
            await sql("INSERT INTO payment_logs(user_id,amount,currency,method,reference) VALUES(43,10,'RUB','crypto_pay','private-own'),(44,999,'RUB','crypto_pay','private-foreign'),(43,3,'RUB','referral_signup','reward'),(43,-10,'RUB','stars_refund','refund'),(43,20,'RUB','lave_pay','private-lave')")
            history=await (await client.get(base+'payment-history?user_id=44',headers=own)).json()
            assert [item['method'] for item in history['items']]==['lave_pay','crypto_pay']
            assert all(isinstance(item['created_at'],int) for item in history['items'])
            assert not any('reference' in item or 'user_id' in item for item in history['items'])
            older=await (await client.get(base+'payment-history?before='+str(history['items'][0]['id']),headers=own)).json()
            assert len(older['items'])==1 and older['items'][0]['method']=='crypto_pay' and not older['has_more']
            foreign_history=await (await client.get(base+'payment-history',headers=foreign)).json()
            assert len(foreign_history['items'])==1 and D(foreign_history['items'][0]['amount'])==999
            assert (await client.get(base+'payment-history')).status==401
            report('Top-up history isolates users, supports cursors, includes Lava and excludes rewards/refunds and private references')
            summary=await (await client.get(base+'wallet/summary?user_id=44',headers=own)).json()
            assert D(summary['deposited'])==30 and D(summary['spent'])==200 and summary['purchase_count']==2,summary
            other_summary=await (await client.get(base+'wallet/summary',headers=foreign)).json()
            assert D(other_summary['deposited'])==999 and D(other_summary['spent'])==0
            ledger=await (await client.get(base+'wallet/transactions?user_id=44',headers=own)).json()
            assert {event['kind'] for event in ledger['items']} >= {'purchase','payment','adjustment'},ledger
            assert not any(event['amount'] is not None and D(event['amount'])==999 for event in ledger['items'])
            assert 'private-own' not in str(ledger) and 'private-foreign' not in str(ledger)
            assert (await client.get(base+'wallet/summary')).status==401
            assert (await client.get(base+'wallet/transactions?page=-1',headers=own)).status==400
            popular=await (await client.get(base+'catalog?sort=popular',headers=own)).json()
            sold_counts=dict(await sql("SELECT a.country,COUNT(*) FROM purchases p JOIN accounts a ON a.id=p.account_id WHERE p.status<>'refunded' GROUP BY a.country"))
            ranks=[int(sold_counts.get(item['category'],0)) for item in popular['items']]
            assert ranks==sorted(ranks,reverse=True)
            report('Wallet totals are owner-scoped and exclude bonuses; full history includes own adjustments; popularity uses real purchases')
            from database import commerce
            from unittest.mock import patch,AsyncMock
            await commerce.register_invoice('crypto','verified-fixture',43,D(50))
            assert (await client.post(base+'invoices/crypto/verified-fixture/check')).status==401
            assert (await client.post(base+'invoices/crypto/verified-fixture/check',headers=foreign,json={})).status==404
            before=await balance(43)
            provider_reply={'invoice_id':'verified-fixture','status':'paid','payload':'rub_topup:43:50.00','currency_type':'fiat','fiat':'RUB','amount':'50.00'}
            with patch.object(payments.cryptopay,'get_invoice',AsyncMock(return_value=provider_reply)) as get:
                verified=await client.post(base+'invoices/crypto/verified-fixture/check',headers=own,json={})
                assert verified.status==200 and (await verified.json())['status']=='credited'
                after=await balance(43);assert after-before==55
                assert (await client.post(base+'invoices/crypto/verified-fixture/check',headers=own,json={})).status==200
                assert await balance(43)==after and get.await_count==1
            assert (await client.get(base+'admin/payments',headers=own)).status==403
            admin_payments=await (await client.get(base+'admin/payments?q=43',headers=admin)).json()
            assert admin_payments['items'][0]['status']=='credited'
            assert (await client.post(base+'admin/payments/check',headers=own,json={'provider':'crypto','invoice_id':'verified-fixture'})).status==403
            report('Manual payment verification authenticates owner and credits one confirmed payment once; payment administration is admin-only')
            heleket_id='11111111-1111-4111-8111-111111111111'
            await commerce.register_invoice('heleket',heleket_id,43,D(50))
            heleket_row=await commerce.invoice('heleket',heleket_id,43)
            heleket_paid={'id':heleket_id,'uuid':heleket_id,'status':'paid','is_final':True,'amount':'50.00','currency':'RUB','payload':'rub_topup:43:50.00'}
            before=await balance(43)
            assert await payments.settle_invoice(heleket_row,heleket_paid)==(50.0,0.0)
            assert await payments.settle_invoice(heleket_row,heleket_paid) is None
            assert await balance(43)==before+50
            assert (await sql("SELECT COUNT(*) FROM payment_logs WHERE user_id=43 AND method='heleket_pay'"))[0][0]==1
            refreshed=await (await client.get(base+'wallet/summary',headers=own)).json()
            assert D(refreshed['deposited'])==130
            report('Confirmed Heleket payment credits exactly once through the existing ledger, with correct wallet totals')


            d=await (await client.get(base+'departments',headers=own)).json()
            assert len(d['items'])==8 and all(not item['is_active'] for item in d['items'])
            denied=await client.post(base+'admin/categories',headers=own,json={'slug':'section-gmail','name':'Gmail','active':True})
            assert denied.status==403
            enabled=await client.post(base+'admin/categories',headers=admin,json={'slug':'section-gmail','name':'Gmail','active':True})
            assert enabled.status==200,(enabled.status,await enabled.text())
            d=await (await client.get(base+'departments',headers=own)).json()
            assert next(i for i in d['items'] if i['slug']=='section-gmail')['is_active']==1
            assert next(i for i in d['items'] if i['slug']=='section-gmail')['count']==0
            await sql("INSERT INTO accounts(country,number,price,data,telegram_user_id) VALUES('section-gmail','+56912340555',100,'SECTION_COUNT_TEST',95555)")
            assert next(i for i in await sections.listing(43) if i['slug']=='section-gmail')['count']==1
            await sql("UPDATE accounts SET status='sold' WHERE data='SECTION_COUNT_TEST'")
            assert next(i for i in await sections.listing(43) if i['slug']=='section-gmail')['count']==0

            assert not any(c['slug'].startswith('section-') for c in (await storage.catalog(43))['categories'])
            assert not any(c['slug'].startswith('section-') for c in (await bot_store.categories(43))[0])
            async with conn.cursor() as cur:await sections.seed(cur)
            assert next(i for i in await sections.listing() if i['slug']=='section-gmail')['is_active']==1
            replies=await asyncio.gather(*[client.post(base+'support',headers=own,json={'body':'Question '+str(i)}) for i in range(2)])
            assert all(r.status==201 for r in replies)
            created=[await r.json() for r in replies];identity=created[0]['ticket_id']
            assert created[1]['ticket_id']==identity
            history=await client.get(base+'support/'+str(identity),headers=own)
            assert history.status==200 and len((await history.json())['messages'])==2
            denied=await client.get(base+'support/'+str(identity),headers=foreign);assert denied.status==404
            denied=await client.post(base+'support/'+str(identity)+'/reply',headers=foreign,json={'body':'wrong owner'});assert denied.status==400
            inbox=await (await client.get(base+'support',headers=foreign)).json();assert not inbox['items']
            sent=await client.post(base+'support/'+str(identity)+'/reply',headers=own,json={'body':'<script>customer content</script>'});assert sent.status==200
            sent=await client.post(base+'admin/tickets/'+str(identity)+'/reply',headers=admin,json={'body':'Support answer'});assert sent.status==200
            history=await (await client.get(base+'support/'+str(identity),headers=own)).json()
            assert history['messages'][0]['author_role']=='admin' and history['messages'][0]['body']=='Support answer'
            await tickets.close_ticket(identity,42)
            sent=await client.post(base+'support/'+str(identity)+'/reply',headers=own,json={'body':'Reopen'});assert sent.status==200
            assert (await tickets.get_ticket(identity,43))['status']=='open'
        report('Departments toggle only for admins, survive seeding and stay out of Telegram sales; general support migration, concurrent reuse, ownership isolation, admin replies and reopen work')
        if '--serve' in sys.argv:
            print('BROWSER FIXTURE: http://127.0.0.1:8093 customer=43 admin=42',flush=True)
            await asyncio.Event().wait()
    finally:
        if runner:await runner.cleanup()
        if db.pool:db.pool.close();await db.pool.wait_closed();db.pool=None
        try:await sql(f'DROP DATABASE IF EXISTS `{name}`')
        finally:conn.close()


if __name__=='__main__':asyncio.run(main())
