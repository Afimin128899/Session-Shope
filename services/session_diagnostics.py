"""Offline structural diagnostics. A valid format does not prove Telegram access."""
import base64
import binascii
import hashlib
import ipaddress
import struct
from collections import Counter

from services.session_validation import NETWORKS


def inspect_session(value):
    """Return a public reason and an internal key fingerprint, never credentials."""
    if value is None or value == '':
        return 'missing', None
    if not isinstance(value, str) or len(value) not in (353, 369):
        return 'invalid_format', None
    if value[0] != '1':
        return 'unsupported_version', None
    try:
        payload = base64.b64decode(value[1:], altchars=b'-_', validate=True)
        address_size = 4 if len(value) == 353 else 16
        dc, address, port, key = struct.unpack(f'>B{address_size}sH256s', payload)
    except (ValueError, binascii.Error, struct.error):
        return 'invalid_format', None
    ip = ipaddress.ip_address(address)
    if dc not in range(1, 6) or port not in {443, 80, 5222} or not any(ip in network for network in NETWORKS):
        return 'invalid_endpoint', None
    if not any(key):
        return 'empty_auth_key', None
    return 'format_ok', hashlib.sha256(key).digest()


async def report_batches(fetch):
    """Bound each attachment to 500 rows; detect repeated keys across batches."""
    snapshot = await fetch("SELECT COALESCE(MAX(id),0) AS maximum FROM accounts WHERE status IN ('available','review')")
    maximum = snapshot[0]['maximum']
    last = 0
    seen = {}
    counts = Counter()
    while last < maximum:
        batch = await fetch("SELECT id,data FROM accounts WHERE status IN ('available','review') AND id>%s AND id<=%s ORDER BY id LIMIT 500", (last, maximum))
        if not batch:
            break
        items = []
        for account in batch:
            last = account['id']
            status, fingerprint = inspect_session(account['data'])
            item = {'account_id': last, 'status': status}
            if fingerprint is not None:
                if fingerprint in seen:
                    item.update(status='duplicate_key', duplicate_of=seen[fingerprint])
                else:
                    seen[fingerprint] = last
            counts[item['status']] += 1
            items.append(item)
        yield {'scope': 'unsold_inventory', 'snapshot_max_id': maximum,
               'telegram_checked': False, 'items': items, 'cumulative_counts': dict(counts)}
    if not counts:
        yield {'scope': 'unsold_inventory', 'snapshot_max_id': maximum,
               'telegram_checked': False, 'items': [], 'cumulative_counts': {}}


async def send_report(bot, admin):
    import json
    from datetime import datetime, timezone
    from aiogram.types import BufferedInputFile
    from database.admin_web import rows

    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    part = 0
    async for report in report_batches(rows):
        part += 1
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        await bot.send_document(admin, BufferedInputFile(payload.encode('utf-8'), filename=f'session-diagnostics-{stamp}-{part}.json'),
            caption='Диагностика сессий: часть %s. Только формат и дубликаты; вход в Telegram не проверялся. Сессии и пароли в отчёт не включены.' % part)
