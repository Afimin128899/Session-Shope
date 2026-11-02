"""Validate Telegram WebApp initData on the server, never trust initDataUnsafe."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


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
        if not isinstance(user, dict) or type(user.get('id')) is not int or not 0 < user['id'] < 2**63:
            raise ValueError
        return {'id': user['id'], 'first_name': str(user.get('first_name', 'Покупатель'))[:100],
                'username': str(user['username'])[:64] if user.get('username') else None}
    except AuthError:
        raise
    except (ValueError, KeyError, TypeError) as exc:
        raise AuthError('Не удалось подтвердить вход через Telegram.') from exc
