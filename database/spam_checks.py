"""Durable, bounded SpamBot checks for unsold inventory, shared by all interfaces."""
from utils.i18n import tr
from datetime import datetime, timezone
from uuid import uuid4

from database.admin_tools import _transaction, _record

LABELS = {'not_checked': 'Не проверен', 'clear': 'Ограничений не обнаружено',
          'limited': 'Есть ограничения', 'unknown': 'Ответ не распознан', 'error': 'Не удалось проверить'}
CHECK_FREE = '(a.spam_lease_until IS NULL OR a.spam_lease_until<=UTC_TIMESTAMP())'


async def init_schema(cur, database):
    fields = [
        ('spam_status', "VARCHAR(16) NOT NULL DEFAULT 'not_checked'"),
        ('spam_checked_at', 'DATETIME DEFAULT NULL'), ('spam_reason', 'VARCHAR(32) DEFAULT NULL'),
        ('spam_next_check_at', 'DATETIME DEFAULT NULL'), ('spam_token', 'CHAR(32) DEFAULT NULL'),
        ('spam_lease_until', 'DATETIME DEFAULT NULL'),
    ]
    for column, definition in fields:
        await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, 'accounts', column))
        if not await cur.fetchone():
            await cur.execute(f'ALTER TABLE accounts ADD COLUMN {column} {definition}')
    await cur.execute("SELECT INDEX_NAME FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='accounts' AND INDEX_NAME='spam_check_queue'", (database,))
    if not await cur.fetchone():
        await cur.execute('CREATE INDEX spam_check_queue ON accounts(status,spam_next_check_at,id)')


def public(row):
    status = row.get('spam_status') or 'not_checked'
    if status not in LABELS:
        status = 'unknown'
    checked = row.get('spam_checked_at')
    if isinstance(checked, str):
        try:
            checked = datetime.fromisoformat(checked)
        except ValueError:
            checked = None
    running = row.get('spam_lease_until')
    if isinstance(running, str):
        running = datetime.fromisoformat(running)
    return {'status': status, 'label': tr(LABELS[status]),
            'checked_at': checked.replace(tzinfo=timezone.utc).isoformat() if checked else None,
            'running': bool(running and running.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc))}


def description(row):
    from zoneinfo import ZoneInfo
    check = public(row)
    label = (tr('Проверяется… Последний результат: ') if check['running'] else '') + check['label']
    if check['checked_at']:
        stamp = datetime.fromisoformat(check['checked_at']).astimezone(ZoneInfo('Europe/Moscow'))
        label += tr(' · {0} МСК', f'{stamp:%d.%m.%Y %H:%M}')
    return label


async def claim():
    async with _transaction() as cur:
        await cur.execute("SELECT a.id,a.data,a.number,a.telegram_user_id FROM accounts a WHERE a.status='available' "
                          "AND (a.spam_next_check_at IS NULL OR a.spam_next_check_at<=UTC_TIMESTAMP()) AND " + CHECK_FREE +
                          " AND NOT EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP()) "
                          "ORDER BY a.spam_next_check_at,a.id LIMIT 1 FOR UPDATE")
        row = await cur.fetchone()
        if not row:
            return None
        # Current locking read after the account lock also covers a concurrent cart insert.
        await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (row['id'],))
        if await cur.fetchone():
            return None
        row['token'] = uuid4().hex
        await cur.execute('UPDATE accounts SET spam_token=%s,spam_lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 MINUTE) WHERE id=%s', (row['token'], row['id']))
        return row


async def finish(lease, report):
    status = report['status'] if report['status'] in {'clear', 'limited', 'unknown', 'error'} else 'unknown'
    reason = report.get('reason')
    if reason not in {None, 'unrecognized', 'unauthorized', 'identity_mismatch', 'wrong_peer', 'no_session', 'flood_wait', 'timeout', 'connection'}:
        reason = 'connection'
    delay = 86400 if status in {'clear', 'limited'} else 3600 if status == 'unknown' else 900
    if reason == 'flood_wait':
        delay = max(delay, int(report.get('retry_after') or delay))
    async with _transaction() as cur:
        await cur.execute("UPDATE accounts SET spam_status=%s,spam_checked_at=UTC_TIMESTAMP(),spam_reason=%s,"
                          "spam_next_check_at=DATE_ADD(UTC_TIMESTAMP(),INTERVAL %s SECOND),spam_token=NULL,spam_lease_until=NULL "
                          "WHERE id=%s AND spam_token=%s AND status='available' AND data=%s AND spam_lease_until>UTC_TIMESTAMP()",
                          (status, reason, delay, lease['id'], lease['token'], lease['data']))
        return cur.rowcount > 0


async def release(lease):
    async with _transaction() as cur:
        await cur.execute('UPDATE accounts SET spam_token=NULL,spam_lease_until=NULL WHERE id=%s AND spam_token=%s', (lease['id'], lease['token']))


async def enqueue(admin_id, account_id=None):
    async with _transaction() as cur:
        condition = "status='available' AND (spam_lease_until IS NULL OR spam_lease_until<=UTC_TIMESTAMP()) "
        condition += "AND (spam_checked_at IS NULL OR spam_checked_at<=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 5 MINUTE)) "
        condition += "AND NOT (COALESCE(spam_reason,'')='flood_wait' AND spam_next_check_at>UTC_TIMESTAMP())"
        if account_id is not None:
            condition += ' AND id=%s'
        await cur.execute('UPDATE accounts SET spam_next_check_at=UTC_TIMESTAMP() WHERE ' + condition,
                          (account_id,) if account_id is not None else ())
        count = cur.rowcount
        await _record(cur, admin_id, 'spam_check_queued', 'account' if account_id else 'stock', account_id or 'all', {'count': count})
        return count
