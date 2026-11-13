"""Quarantine failed session checks, delete only after the export was delivered."""
from database.admin_tools import _transaction, _record

PENDING = 'session_audit_export_pending'


async def hide_failed(admin, account, token):
    async with _transaction() as cur:
        await cur.execute("SELECT id FROM accounts WHERE id=%s AND data=%s AND spam_token=%s AND status IN ('available','review') FOR UPDATE", (account['id'],account['data'],token))
        if not await cur.fetchone():
            return False
        await cur.execute('SELECT id FROM purchases WHERE account_id=%s LIMIT 1', (account['id'],))
        if await cur.fetchone():
            return False
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (account['id'],))
        if await cur.fetchone():
            return False
        await cur.execute('DELETE FROM shopping_cart WHERE account_id=%s', (account['id'],))
        await cur.execute("UPDATE accounts SET status='review',review_reason=%s,review_admin_id=%s,review_started_at=UTC_TIMESTAMP(),spam_requested=0 WHERE id=%s", (PENDING,admin,account['id']))
        await _record(cur,admin,'session_audit_hidden','account',account['id'],{})
        return True


async def delete_delivered(admin, account):
    async with _transaction() as cur:
        await cur.execute("SELECT id FROM accounts WHERE id=%s AND data=%s AND status='review' AND review_reason=%s FOR UPDATE", (account['id'],account['data'],PENDING))
        if not await cur.fetchone():
            return False
        await cur.execute('SELECT id FROM purchases WHERE account_id=%s LIMIT 1', (account['id'],))
        if await cur.fetchone():
            return False
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (account['id'],))
        if await cur.fetchone():
            return False
        await cur.execute('DELETE FROM shopping_cart WHERE account_id=%s',(account['id'],))
        await cur.execute('DELETE FROM accounts WHERE id=%s',(account['id'],))
        await _record(cur,admin,'session_audit_deleted','account',account['id'],{})
        return True
