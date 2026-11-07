"""Publish a synthetic fixture after a synthetic verified SpamBot result.

This helper belongs to tests only; it never calls Telegram or loads real sessions.
"""
from uuid import uuid4
from test_payments import db
from database import spam_checks


async def confirm_fixture_account(account_id, status='clear'):
    row=await db.get_account(account_id)
    token=uuid4().hex
    async with db._get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE accounts SET spam_token=%s,spam_lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 MINUTE) WHERE id=%s AND status='available'",(token,account_id))
    assert await spam_checks.finish({'id':account_id,'token':token,'data':row['data']},{'status':status,'reason':None})
