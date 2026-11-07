"""Group unsold stock by verified phone country and the actual SpamBot result."""
from utils.country_codes import detect_country, detect_country_flag
from utils.commerce_policy import require_phone
from database.admin_tools import _record

LABELS = {'clear': 'Без спамблока', 'permanent': 'Вечный спамблок',
          'limited': 'Есть ограничения'}


def specification(phone, status):
    phone = '+' + require_phone(phone)
    name, flag = detect_country(phone), detect_country_flag(phone)
    country = ''.join(chr(ord(c) - 0x1F1E6 + ord('a')) for c in flag) if len(flag) == 2 else 'unknown'
    verified = status in LABELS and country != 'unknown'
    state = status if verified else 'pending'
    label = LABELS[status] if verified else 'Проверка спамблока'
    return {'slug': f'auto-{country}-{state}', 'name': f'{name} {flag} · {label}',
            'emoji': flag, 'active': int(verified)}


async def ensure(cur, phone, status):
    spec = specification(phone, status)
    # Preserve a manually disabled category; pending stock cannot be published
    # merely by editing the category before a successful check.
    await cur.execute('INSERT INTO categories(slug,name,emoji,is_active) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE name=VALUES(name),emoji=VALUES(emoji),is_active=IF(VALUES(is_active)=0,0,is_active)',
                      (spec['slug'], spec['name'], spec['emoji'], spec['active']))
    return spec['slug']


async def move_checked(cur, account_id, status):
    await cur.execute('SELECT a.number,a.country,c.is_active FROM accounts a LEFT JOIN categories c ON c.slug=a.country WHERE a.id=%s', (account_id,))
    row = await cur.fetchone()
    if not row or (row['is_active'] == 0 and not (str(row['country'] or '').startswith('auto-') and str(row['country'] or '').endswith('-pending'))):
        return
    try:
        specification(row['number'], status)
    except ValueError:
        # Country policy remains authoritative for legacy invalid inventory.
        return
    target = await ensure(cur, row['number'], status)
    if target != row['country']:
        await cur.execute('UPDATE accounts SET country=%s WHERE id=%s', (target, account_id))
        await _record(cur, 0, 'auto_category', 'account', account_id,
                      {'before': row['country'], 'after': target, 'spam_status': status})


def validate_selection(phone, status, checked_at, category, source=None):
    if category.startswith('auto-') or str(source or '').startswith('auto-'):
        expected = specification(phone, status if checked_at else 'not_checked')['slug']
        if category != expected:
            from utils.i18n import tr
            raise ValueError(tr('Автокатегория должна соответствовать стране и подтверждённому спамблоку аккаунта.'))
