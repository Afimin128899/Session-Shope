"""One helper role and owner-scoped acquisition campaigns; no referral rewards."""
import re
import secrets
from database import db
from database.admin_tools import _transaction, _record
from database.admin_web import rows

class AccessDenied(PermissionError):
    pass


TOKEN = re.compile(r'[A-Za-z0-9_-]{22}\Z')


def token_from_payload(value):
    return value[3:] if isinstance(value, str) and value.startswith('ad_') and TOKEN.fullmatch(value[3:]) else None


def helper_profile(profile, user_id):
    from config import ADMIN_IDS
    return bool(profile and profile.get('is_helper') == 1 and user_id not in ADMIN_IDS)


async def is_helper(user_id):
    return helper_profile(await db.get_user(user_id), user_id)


async def init_schema(cur, database):
    await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, 'users', 'is_helper'))
    if not await cur.fetchone():
        await cur.execute('ALTER TABLE users ADD COLUMN is_helper TINYINT NOT NULL DEFAULT 0')
    await cur.execute('''CREATE TABLE IF NOT EXISTS advertising_campaigns (
        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
        owner_id BIGINT NOT NULL, token CHAR(22) CHARACTER SET ascii COLLATE ascii_bin NOT NULL UNIQUE,
        name VARCHAR(80) NOT NULL, created_at DATETIME NOT NULL,
        KEY advertising_owner(owner_id,id)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS advertising_users (
        user_id BIGINT PRIMARY KEY, campaign_id BIGINT NOT NULL, created_at DATETIME NOT NULL,
        KEY advertising_campaign(campaign_id,user_id)
    ) ENGINE=InnoDB''')


async def set_helper(actor, user_id, enabled):
    from config import ADMIN_IDS
    if actor not in ADMIN_IDS:
        raise AccessDenied('Доступ только владельцу.')
    if type(user_id) is not int or not 0 < user_id <= 9223372036854775807 or type(enabled) is not bool:
        raise ValueError('Укажите корректный Telegram ID и состояние роли.')
    if user_id in ADMIN_IDS:
        raise ValueError('Администратору нельзя назначить роль помощника.')
    async with _transaction() as cur:
        await cur.execute('SELECT id FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not await cur.fetchone():
            raise ValueError('Пользователь должен сначала запустить бота.')
        await cur.execute('UPDATE users SET is_helper=%s WHERE id=%s', (int(enabled), user_id))
        await _record(cur, actor, 'helper_role', 'user', user_id, {'enabled': enabled})


async def helpers(actor):
    from config import ADMIN_IDS
    if actor not in ADMIN_IDS:
        raise AccessDenied('Доступ только владельцу.')
    return await rows('SELECT id,username FROM users WHERE is_helper=1 ORDER BY id LIMIT 101')


async def require_helper(user_id):
    if not await is_helper(user_id):
        raise AccessDenied('Раздел доступен только помощнику.')


async def create_campaign(user_id, name):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or any(ord(c)<32 for c in name):
        raise ValueError('Название должно содержать от 1 до 80 символов без переводов строки.')
    async with _transaction() as cur:
        await cur.execute('SELECT id,is_helper FROM users WHERE id=%s FOR UPDATE', (user_id,))
        if not helper_profile(await cur.fetchone(), user_id):
            raise AccessDenied('Раздел доступен только помощнику.')
        await cur.execute('SELECT COUNT(*) AS n FROM advertising_campaigns WHERE owner_id=%s', (user_id,))
        if (await cur.fetchone())['n'] >= 100:
            raise ValueError('Максимум 100 рекламных ссылок на помощника.')
        token = secrets.token_urlsafe(16)
        await cur.execute('INSERT INTO advertising_campaigns(owner_id,token,name,created_at) VALUES(%s,%s,%s,UTC_TIMESTAMP())', (user_id, token, name.strip()))
        identity = cur.lastrowid
        await _record(cur, user_id, 'advertising_create', 'campaign', identity, {'name': name.strip()})
        return {'id': identity, 'token': token, 'name': name.strip(), 'users_count': 0}


async def campaigns(user_id):
    await require_helper(user_id)
    return await rows('''SELECT c.id,c.name,c.token,c.created_at,COUNT(a.user_id) AS users_count
        FROM advertising_campaigns c LEFT JOIN advertising_users a ON a.campaign_id=c.id
        WHERE c.owner_id=%s GROUP BY c.id,c.name,c.token,c.created_at ORDER BY c.id DESC LIMIT 100''', (user_id,))


async def campaign_users(user_id, campaign_id, page=0):
    await require_helper(user_id)
    if type(campaign_id) is not int or campaign_id<=0 or type(page) is not int or not 0<=page<=10000:
        raise ValueError('Некорректная страница.')
    campaign = await rows('SELECT id,name,token FROM advertising_campaigns WHERE id=%s AND owner_id=%s', (campaign_id,user_id))
    if not campaign:
        return None
    items = await rows('''SELECT a.user_id,u.username,a.created_at FROM advertising_users a
        JOIN advertising_campaigns c ON c.id=a.campaign_id JOIN users u ON u.id=a.user_id
        WHERE a.campaign_id=%s AND c.owner_id=%s ORDER BY a.user_id DESC LIMIT 16 OFFSET %s''', (campaign_id,user_id,page*15))
    return {'campaign': campaign[0], 'items': items[:15], 'has_more': len(items)>15}


async def attribute_new_user(cur, user_id, token):
    """Called only after the winning new-user INSERT, in that same transaction."""
    if not isinstance(token,str) or not TOKEN.fullmatch(token):
        return
    await cur.execute('''SELECT c.id FROM advertising_campaigns c JOIN users u ON u.id=c.owner_id
        WHERE c.token=%s AND u.is_helper=1 AND c.owner_id<>%s''', (token,user_id))
    campaign=await cur.fetchone()
    if campaign:
        await cur.execute('INSERT IGNORE INTO advertising_users(user_id,campaign_id,created_at) VALUES(%s,%s,UTC_TIMESTAMP())', (user_id,campaign['id']))
