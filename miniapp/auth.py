"""Validate Telegram WebApp initData on the server, never trust initDataUnsafe."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import parse_qsl
from urllib.parse import urlsplit


SESSION_COOKIE = 'sband_session'
TELEGRAM_ID_LIMIT = 2**52


def photo_url(value):
    """Only Telegram-hosted HTTPS photos from the verified user payload."""
    if not isinstance(value, str) or len(value) > 2048:
        return None
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        allowed = host in {'t.me', 'telegram.org'} or host.endswith(('.t.me', '.telegram.org'))
        return value if url.scheme == 'https' and allowed and not url.username and not url.password and url.port in (None, 443) else None
    except ValueError:
        return None


class AuthError(ValueError):
    pass


def validate_init_data(raw, token, *, now=None, max_age=3600):
    if not token or not raw or len(raw) > 16384:
        raise AuthError('Откройте приложение из Telegram.')
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True, max_num_fields=30)
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError
        received = data.pop('hash')
        if len(received) != 64:
            raise ValueError
        check_string = '\n'.join(f'{key}={value}' for key, value in sorted(data.items()))
        secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError
        current = time.time() if now is None else now
        age = current - int(data['auth_date'])
        if age < -30 or age > max_age:
            raise AuthError('Сессия истекла. Закройте и откройте приложение заново.')
        user = json.loads(data['user'])
        if not isinstance(user, dict) or type(user.get('id')) is not int or not 0 < user['id'] < TELEGRAM_ID_LIMIT:
            raise ValueError
        identity = {'id': user['id'], 'first_name': str(user.get('first_name', 'Покупатель'))[:100],
                    'username': str(user['username'])[:64] if user.get('username') else None}
        if picture := photo_url(user.get('photo_url')):
            identity['photo_url'] = picture
        return identity
    except AuthError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthError('Не удалось подтвердить вход через Telegram.') from exc


def _widget_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, (str, int)) and not isinstance(value, float):
        return str(value)
    raise ValueError


def validate_login_widget(payload, token, *, now=None, max_age=3600):
    """Validate Telegram Login Widget data with the bot-token secret."""
    if not token or not isinstance(payload, dict) or len(payload) > 12:
        raise AuthError('Не удалось подтвердить вход через Telegram.')
    try:
        data = dict(payload)
        received = data.pop('hash')
        if not isinstance(received, str) or not re.fullmatch(r'[0-9a-f]{64}', received):
            raise ValueError
        allowed = {
            'id', 'first_name', 'last_name', 'username', 'photo_url',
            'auth_date', 'allows_write_to_pm',
        }
        if not {'id', 'first_name', 'auth_date'} <= data.keys() or not data.keys() <= allowed:
            raise ValueError
        check = '\n'.join(f'{key}={_widget_value(data[key])}' for key in sorted(data))
        secret = hashlib.sha256(token.encode()).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            raise ValueError
        user_id = data['id']
        auth_date = data['auth_date']
        if type(user_id) is not int or not 0 < user_id < TELEGRAM_ID_LIMIT:
            raise ValueError
        if type(auth_date) is not int:
            raise ValueError
        age = (time.time() if now is None else now) - auth_date
        if age < -30 or age > max_age:
            raise AuthError('Сессия Telegram истекла. Войдите ещё раз.')
        first_name = data['first_name']
        username = data.get('username')
        if not isinstance(first_name, str) or not first_name.strip() or len(first_name) > 100:
            raise ValueError
        if username is not None and (not isinstance(username, str) or len(username) > 64):
            raise ValueError
        identity = {
            'id': user_id,
            'first_name': first_name.strip(),
            'username': username or None,
        }
        if picture := photo_url(data.get('photo_url')):
            identity['photo_url'] = picture
        return identity
    except AuthError:
        raise
    except (KeyError, TypeError, ValueError, UnicodeError) as exc:
        raise AuthError('Не удалось подтвердить вход через Telegram.') from exc


def normalize_email(value):
    """Return a stable ASCII mailbox key; quoted and Unicode local parts are rejected."""
    if not isinstance(value, str):
        raise AuthError('Введите корректный адрес почты.')
    value = value.strip()
    if not 3 <= len(value) <= 254 or value.count('@') != 1:
        raise AuthError('Введите корректный адрес почты.')
    local, domain = value.rsplit('@', 1)
    try:
        local.encode('ascii')
        domain = domain.encode('idna').decode('ascii').lower()
    except UnicodeError as exc:
        raise AuthError('Введите корректный адрес почты.') from exc
    local = local.lower()
    if (len(local) > 64 or local.startswith('.') or local.endswith('.') or '..' in local
            or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)):
        raise AuthError('Введите корректный адрес почты.')
    labels = domain.split('.')
    if (len(domain) > 253 or len(labels) < 2
            or any(not label or len(label) > 63 or label.startswith('-') or label.endswith('-')
                   or not re.fullmatch(r'[a-z0-9-]+', label) for label in labels)):
        raise AuthError('Введите корректный адрес почты.')
    return local + '@' + domain


def email_key(email):
    return hashlib.sha256(email.encode('ascii')).hexdigest()


def email_code_digest(email, code, token):
    if not token:
        raise RuntimeError('Bot token is required for email challenge hashing')
    secret = hmac.new(token.encode(), b'sband-email-login-v1', hashlib.sha256).digest()
    return hmac.new(secret, (email + '\0' + code).encode('ascii'), hashlib.sha256).hexdigest()


async def resolve_identity(request, token, *, required=True):
    """Resolve signed Mini App data first, then an opaque browser cookie."""
    if request.get('user'):
        return request['user']
    authorization = request.headers.get('Authorization', '')
    if authorization:
        if not authorization.startswith('tma '):
            raise AuthError('Неподдерживаемый способ входа.')
        raw = authorization[4:]
        if raw:
            user = validate_init_data(raw, token)
            user['auth_method'] = 'telegram_miniapp'
            request['user'] = user
            return user
    session = request.cookies.get(SESSION_COOKIE, '')
    if session:
        from database.web_auth import session_identity
        user = await session_identity(session)
        if user:
            request['user'] = user
            request['browser_session'] = True
            return user
    if required:
        raise AuthError('Войдите через Telegram или по электронной почте.')
    return None
