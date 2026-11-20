"""Persistent browser identities and opaque login sessions.

Telegram users keep their real Telegram ID. Email-only users receive an ID in
a reserved range above Telegram's documented 52-bit identifier space, so the
existing wallet and order tables remain the single source of truth.
"""
import hashlib
import hmac
import secrets

import aiomysql

from database.admin_tools import _transaction
from database.db import _get_pool


TELEGRAM_ID_LIMIT = 2**52
WEB_USER_ID_BASE = 2**62
SESSION_TOKEN_BYTES = 32


class EmailCodeError(ValueError):
    pass


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode('ascii')).hexdigest()


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS web_identities (
        id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        provider VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        subject VARCHAR(254) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        user_id BIGINT DEFAULT NULL,
        email VARCHAR(254) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
        first_name VARCHAR(100) DEFAULT NULL,
        username VARCHAR(64) DEFAULT NULL,
        created_at DATETIME NOT NULL,
        verified_at DATETIME NOT NULL,
        last_login_at DATETIME NOT NULL,
        UNIQUE KEY web_identity_subject (provider,subject),
        UNIQUE KEY web_identity_provider_user (provider,user_id),
        KEY web_identity_user (user_id),
        CONSTRAINT web_identity_user_fk FOREIGN KEY (user_id) REFERENCES users(id)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS web_email_codes (
        email_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        code_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
        attempts SMALLINT UNSIGNED NOT NULL DEFAULT 0,
        sent_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        KEY web_email_code_expiry (expires_at)
    ) ENGINE=InnoDB''')
    await cur.execute('''CREATE TABLE IF NOT EXISTS web_sessions (
        token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
        identity_id BIGINT UNSIGNED NOT NULL,
        created_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL,
        expires_at DATETIME NOT NULL,
        revoked_at DATETIME DEFAULT NULL,
        KEY web_session_identity (identity_id),
        KEY web_session_expiry (expires_at),
        CONSTRAINT web_session_identity_fk FOREIGN KEY (identity_id)
            REFERENCES web_identities(id) ON DELETE CASCADE
    ) ENGINE=InnoDB''')


async def save_email_code(email_hash: str, code_hash: str, *, ttl=600, cooldown=60):
    """Replace a challenge unless one was sent too recently."""
    async with _transaction() as cur:
        await cur.execute(
            'SELECT TIMESTAMPDIFF(SECOND,sent_at,UTC_TIMESTAMP()) AS age '
            'FROM web_email_codes WHERE email_hash=%s FOR UPDATE',
            (email_hash,),
        )
        found = await cur.fetchone()
        age = int(found['age']) if found and found.get('age') is not None else None
        if age is not None and age < cooldown:
            return False, max(1, cooldown - age)
        await cur.execute('''INSERT INTO web_email_codes
            (email_hash,code_hash,attempts,sent_at,expires_at)
            VALUES(%s,%s,0,UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(),INTERVAL %s SECOND))
            ON DUPLICATE KEY UPDATE code_hash=VALUES(code_hash),attempts=0,
                sent_at=VALUES(sent_at),expires_at=VALUES(expires_at)''',
            (email_hash, code_hash, ttl),
        )
        return True, cooldown


async def clear_email_code(email_hash: str, code_hash: str):
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'DELETE FROM web_email_codes WHERE email_hash=%s AND code_hash=%s',
                (email_hash, code_hash),
            )


async def consume_email_code(email: str, email_hash: str, code_hash: str):
    """Consume one challenge and return/create its isolated wallet identity."""
    failure = None
    identity = None
    async with _transaction() as cur:
        await cur.execute(
            'SELECT code_hash,attempts,expires_at>UTC_TIMESTAMP() AS active '
            'FROM web_email_codes WHERE email_hash=%s FOR UPDATE',
            (email_hash,),
        )
        challenge = await cur.fetchone()
        if not challenge or not challenge['active']:
            if challenge:
                await cur.execute('DELETE FROM web_email_codes WHERE email_hash=%s', (email_hash,))
            failure = 'Код истёк. Запросите новый.'
        elif not hmac.compare_digest(challenge['code_hash'], code_hash):
            attempts = int(challenge['attempts']) + 1
            if attempts >= 5:
                await cur.execute('DELETE FROM web_email_codes WHERE email_hash=%s', (email_hash,))
            else:
                await cur.execute(
                    'UPDATE web_email_codes SET attempts=%s WHERE email_hash=%s',
                    (attempts, email_hash),
                )
            failure = 'Неверный код. Проверьте письмо и попробуйте снова.'
        else:
            await cur.execute('DELETE FROM web_email_codes WHERE email_hash=%s', (email_hash,))
            await cur.execute(
                "SELECT * FROM web_identities WHERE provider='email' AND subject=%s FOR UPDATE",
                (email,),
            )
            identity = await cur.fetchone()
            if identity:
                await cur.execute(
                    'UPDATE web_identities SET verified_at=UTC_TIMESTAMP(),last_login_at=UTC_TIMESTAMP() '
                    'WHERE id=%s',
                    (identity['id'],),
                )
            else:
                display = email.split('@', 1)[0][:100] or 'Покупатель'
                await cur.execute('''INSERT INTO web_identities
                    (provider,subject,email,first_name,created_at,verified_at,last_login_at)
                    VALUES('email',%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP(),UTC_TIMESTAMP())''',
                    (email, email, display),
                )
                identity_id = int(cur.lastrowid)
                user_id = WEB_USER_ID_BASE + identity_id
                if user_id >= 2**63:
                    raise RuntimeError('Web identity range exhausted')
                await cur.execute(
                    'INSERT INTO users(id,balance,balance_usdt,username) VALUES(%s,0,0,NULL)',
                    (user_id,),
                )
                from database.welcome import credit_new_user
                await credit_new_user(cur, user_id)
                await cur.execute(
                    'UPDATE web_identities SET user_id=%s WHERE id=%s',
                    (user_id, identity_id),
                )
                identity = {
                    'id': identity_id,
                    'provider': 'email',
                    'subject': email,
                    'user_id': user_id,
                    'email': email,
                    'first_name': display,
                    'username': None,
                }
    # These writes are abuse controls. Raising inside _transaction would roll
    # them back and allow unlimited guesses of the same six-digit code.
    if failure:
        raise EmailCodeError(failure)
    return identity


async def telegram_identity(user):
    """Upsert verified Login Widget data; signature validation happens earlier."""
    from database import db

    await db.create_user(user['id'], user.get('username'), welcome_bonus=True)
    async with _transaction() as cur:
        await cur.execute('''INSERT INTO web_identities
            (provider,subject,user_id,first_name,username,created_at,verified_at,last_login_at)
            VALUES('telegram',%s,%s,%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP(),UTC_TIMESTAMP())
            ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),user_id=VALUES(user_id),
                first_name=VALUES(first_name),username=VALUES(username),
                verified_at=UTC_TIMESTAMP(),last_login_at=UTC_TIMESTAMP()''',
            (str(user['id']), user['id'], user.get('first_name'), user.get('username')),
        )
        identity_id = int(cur.lastrowid)
        await cur.execute('SELECT * FROM web_identities WHERE id=%s', (identity_id,))
        return await cur.fetchone()


async def create_session(identity_id: int, *, ttl=30 * 24 * 3600):
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    hashed = digest_token(token)
    async with _transaction() as cur:
        await cur.execute(
            'DELETE FROM web_sessions WHERE expires_at<=UTC_TIMESTAMP() OR revoked_at IS NOT NULL'
        )
        await cur.execute('''INSERT INTO web_sessions
            (token_hash,identity_id,created_at,last_seen_at,expires_at)
            VALUES(%s,%s,UTC_TIMESTAMP(),UTC_TIMESTAMP(),DATE_ADD(UTC_TIMESTAMP(),INTERVAL %s SECOND))''',
            (hashed, identity_id, ttl),
        )
    return token, ttl


async def session_identity(token: str):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        return None
    try:
        hashed = digest_token(token)
    except (UnicodeError, ValueError):
        return None
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('''SELECT i.*,
                s.last_seen_at<DATE_SUB(UTC_TIMESTAMP(),INTERVAL 1 HOUR) AS refresh_seen
                FROM web_sessions s JOIN web_identities i ON i.id=s.identity_id
                WHERE s.token_hash=%s AND s.revoked_at IS NULL
                  AND s.expires_at>UTC_TIMESTAMP()''', (hashed,))
            row = await cur.fetchone()
            if not row:
                return None
            if row.pop('refresh_seen', False):
                await cur.execute(
                    'UPDATE web_sessions SET last_seen_at=UTC_TIMESTAMP() WHERE token_hash=%s',
                    (hashed,),
                )
    identity = {
        'id': int(row['user_id']),
        'first_name': row.get('first_name') or 'Покупатель',
        'username': row.get('username'),
        'auth_method': row['provider'],
        'identity_id': int(row['id']),
    }
    if row['provider'] == 'email':
        identity['email'] = row['email']
    return identity


async def revoke_session(token: str):
    if not isinstance(token, str) or not 32 <= len(token) <= 128:
        return
    try:
        hashed = digest_token(token)
    except (UnicodeError, ValueError):
        return
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                'UPDATE web_sessions SET revoked_at=UTC_TIMESTAMP() '
                'WHERE token_hash=%s AND revoked_at IS NULL',
                (hashed,),
            )
