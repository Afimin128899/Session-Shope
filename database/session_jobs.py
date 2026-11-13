"""Short inventory leases for account export/re-authorization jobs."""
import hashlib
from uuid import uuid4
from database.admin_tools import _transaction, _record


async def claim(identity):
    async with _transaction() as cur:
        await cur.execute("SELECT * FROM accounts WHERE id=%s AND status IN ('available','review') AND spam_requested=0 AND (spam_lease_until IS NULL OR spam_lease_until<=UTC_TIMESTAMP()) FOR UPDATE",(identity,))
        row=await cur.fetchone()
        if not row: return None
        await cur.execute('SELECT id FROM purchases WHERE account_id=%s LIMIT 1',(identity,))
        if await cur.fetchone(): return None
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE',(identity,))
        if await cur.fetchone(): return None
        row['lease_token']=uuid4().hex
        await cur.execute('UPDATE accounts SET spam_token=%s,spam_lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 MINUTE) WHERE id=%s',(row['lease_token'],identity))
        return row


async def release(row):
    async with _transaction() as cur:
        await cur.execute('UPDATE accounts SET spam_token=NULL,spam_lease_until=NULL WHERE id=%s AND spam_token=%s',(row['id'],row['lease_token']))


async def save_new(admin,row,result):
    async with _transaction() as cur:
        await cur.execute("SELECT id FROM accounts WHERE id=%s AND data=%s AND spam_token=%s AND spam_lease_until>UTC_TIMESTAMP() AND status IN ('available','review') FOR UPDATE",(row['id'],row['data'],row['lease_token']))
        if not await cur.fetchone(): return False
        # A second identity key keeps duplicate-import protection valid after rotation.
        key='session:'+hashlib.sha256(result['new_session'].encode()).hexdigest()
        await cur.execute('INSERT IGNORE INTO inventory_identities(identity_key,account_id) VALUES(%s,%s)',(key,row['id']))
        await cur.execute('SELECT account_id FROM inventory_identities WHERE identity_key=%s FOR UPDATE',(key,))
        if (await cur.fetchone())['account_id']!=row['id']:
            raise ValueError('Сессия уже привязана к другому товару.')
        await cur.execute('UPDATE accounts SET data=%s,telegram_user_id=%s WHERE id=%s',(result['new_session'],result['telegram_user_id'],row['id']))
        await _record(cur,admin,'session_reauthorized','account',row['id'],{})
        return True
