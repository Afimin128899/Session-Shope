"""Email-code and Telegram Login Widget endpoints for ordinary browsers."""
import asyncio
import logging
import os
import secrets
import smtplib
import ssl
import time
from collections import OrderedDict, deque
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr
from urllib.parse import urlsplit

from aiohttp import web

from database import web_auth
from miniapp.auth import (
    AuthError,
    SESSION_COOKIE,
    email_code_digest,
    email_key,
    normalize_email,
    validate_login_widget,
)


AUTH_LIMITS = web.AppKey('browser_auth_limits', OrderedDict)
PUBLIC_PATHS = {
    '/api/auth/email/start',
    '/api/auth/email/verify',
    '/api/auth/telegram',
    '/api/auth/logout',
}
logger = logging.getLogger(__name__)


class EmailUnavailable(RuntimeError):
    pass


def _integer_env(name, default, minimum, maximum):
    try:
        return min(max(int(os.getenv(name, str(default))), minimum), maximum)
    except ValueError:
        return default


def session_ttl():
    return _integer_env('AUTH_SESSION_TTL', 30 * 24 * 3600, 3600, 90 * 24 * 3600)


def secure_cookie():
    return os.getenv('AUTH_COOKIE_SECURE', '1').strip().lower() not in {'0', 'false', 'no'}


def smtp_settings():
    host = os.getenv('AUTH_SMTP_HOST', '').strip()
    sender = os.getenv('AUTH_SMTP_FROM', '').strip()
    if not host or not sender or '\n' in sender or '\r' in sender:
        raise EmailUnavailable('Email delivery is not configured')
    sender_address = parseaddr(sender)[1]
    try:
        normalize_email(sender_address)
    except AuthError:
        raise EmailUnavailable('Invalid SMTP sender') from None
    port = _integer_env('AUTH_SMTP_PORT', 587, 1, 65535)
    security = os.getenv('AUTH_SMTP_SECURITY', 'ssl' if port == 465 else 'starttls').strip().lower()
    if security not in {'ssl', 'starttls', 'none'}:
        raise EmailUnavailable('Unsupported SMTP security mode')
    username = os.getenv('AUTH_SMTP_USERNAME', '').strip()
    password = os.getenv('AUTH_SMTP_PASSWORD', '')
    if bool(username) != bool(password):
        raise EmailUnavailable('Incomplete SMTP credentials')
    return host, port, security, username, password, sender


async def send_email_code(recipient, code):
    host, port, security, username, password, sender = smtp_settings()
    message = EmailMessage()
    message['From'] = sender
    message['To'] = recipient
    message['Subject'] = 'Код входа в SBAND ACCS'
    message['Date'] = formatdate(usegmt=True)
    sender_domain = normalize_email(parseaddr(sender)[1]).rsplit('@', 1)[1]
    message['Message-ID'] = make_msgid(domain=sender_domain)
    message.set_content(
        f'Код входа: {code}\n\n'
        'Он действует 10 минут. Если вы не запрашивали вход, удалите это письмо.\n'
    )

    def deliver():
        context = ssl.create_default_context()
        cls = smtplib.SMTP_SSL if security == 'ssl' else smtplib.SMTP
        kwargs = {'context': context} if security == 'ssl' else {}
        with cls(host, port, timeout=12, **kwargs) as client:
            if security == 'starttls':
                client.ehlo()
                client.starttls(context=context)
                client.ehlo()
            if username:
                client.login(username, password)
            client.send_message(message)

    await asyncio.to_thread(deliver)


def ensure_same_origin(request):
    from database.advertising import AccessDenied
    if request.headers.get('Sec-Fetch-Site', '').lower() == 'cross-site':
        raise AccessDenied('Запрос с другого сайта отклонён.')
    origin = request.headers.get('Origin')
    if not origin:
        return
    try:
        parsed = urlsplit(origin)
        received = f'{parsed.scheme.lower()}://{parsed.netloc.lower()}'
    except ValueError as exc:
        raise AccessDenied('Некорректный источник запроса.') from exc
    allowed = {f'{request.scheme.lower()}://{request.host.lower()}'}
    configured = os.getenv('AUTH_PUBLIC_ORIGIN', 'https://sbandsub.space').strip()
    try:
        if configured:
            expected = urlsplit(configured)
            if expected.scheme in {'http', 'https'} and expected.netloc:
                allowed.add(f'{expected.scheme.lower()}://{expected.netloc.lower()}')
    except ValueError:
        pass
    if (parsed.scheme not in {'http', 'https'} or not parsed.netloc
            or parsed.path not in {'', '/'} or parsed.query or parsed.fragment
            or received not in allowed):
        raise AccessDenied('Запрос с другого сайта отклонён.')


def _limited(app, key, *, maximum, window):
    limits = app[AUTH_LIMITS]
    now = time.monotonic()
    history = limits.setdefault(key, deque())
    limits.move_to_end(key)
    while history and now - history[0] >= window:
        history.popleft()
    if len(history) >= maximum:
        return True
    history.append(now)
    while len(limits) > 4096:
        limits.popitem(last=False)
    return False


def _client_bucket(request):
    # The service normally listens on loopback behind Caddy. Caddy replaces this
    # header, while direct deployments still fall back to the socket peer.
    forwarded = request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
    value = forwarded or request.remote or 'unknown'
    return value[:64]


def _set_session_cookie(result, token, ttl):
    result.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=ttl,
        httponly=True,
        secure=secure_cookie(),
        samesite='Lax',
        path='/',
    )


def register(app, response):
    from miniapp.server import TOKEN, json_body

    app[AUTH_LIMITS] = OrderedDict()

    async def email_start(request):
        ensure_same_origin(request)
        smtp_settings()
        body = await json_body(request)
        email = normalize_email(body.get('email'))
        key = email_key(email)
        if (_limited(app, ('email', key), maximum=5, window=3600)
                or _limited(app, ('email-ip', _client_bucket(request)), maximum=30, window=3600)):
            return response({'error': 'Слишком много запросов. Попробуйте позже.', 'code': 'rate_limited'}, 429)
        code = f'{secrets.randbelow(1_000_000):06d}'
        digest = email_code_digest(email, code, app[TOKEN])
        created, retry = await web_auth.save_email_code(key, digest)
        if created:
            try:
                await send_email_code(email, code)
            except Exception as exc:
                await web_auth.clear_email_code(key, digest)
                logger.warning('Email login delivery failed [%s]', type(exc).__name__)
                raise EmailUnavailable('Email delivery failed') from None
        return response({
            'ok': True,
            'message': 'Если адрес доступен, письмо с кодом уже отправлено.',
            'expires_in': 600,
            'retry_after': retry,
        }, 202)

    async def email_verify(request):
        ensure_same_origin(request)
        body = await json_body(request)
        email = normalize_email(body.get('email'))
        code = body.get('code')
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise AuthError('Введите шестизначный код из письма.')
        if _limited(app, ('verify', email_key(email)), maximum=8, window=600):
            return response({'error': 'Слишком много попыток. Запросите новый код.', 'code': 'rate_limited'}, 429)
        identity = await web_auth.consume_email_code(
            email,
            email_key(email),
            email_code_digest(email, code, app[TOKEN]),
        )
        token, ttl = await web_auth.create_session(int(identity['id']), ttl=session_ttl())
        result = response({'ok': True, 'auth_method': 'email'})
        _set_session_cookie(result, token, ttl)
        return result

    async def telegram(request):
        ensure_same_origin(request)
        if _limited(app, ('telegram', _client_bucket(request)), maximum=20, window=600):
            return response({'error': 'Слишком много попыток входа. Попробуйте позже.', 'code': 'rate_limited'}, 429)
        user = validate_login_widget(await json_body(request), app[TOKEN])
        identity = await web_auth.telegram_identity(user)
        token, ttl = await web_auth.create_session(int(identity['id']), ttl=session_ttl())
        result = response({'ok': True, 'auth_method': 'telegram'})
        _set_session_cookie(result, token, ttl)
        return result

    async def logout(request):
        ensure_same_origin(request)
        if token := request.cookies.get(SESSION_COOKIE):
            await web_auth.revoke_session(token)
        result = response({'ok': True})
        # aiohttp's del_cookie API does not preserve all security attributes
        # across supported versions, so expire the exact cookie explicitly.
        result.set_cookie(
            SESSION_COOKIE,
            '',
            max_age=0,
            expires='Thu, 01 Jan 1970 00:00:00 GMT',
            path='/',
            secure=secure_cookie(),
            httponly=True,
            samesite='Lax',
        )
        return result

    app.add_routes([
        web.post('/api/auth/email/start', email_start),
        web.post('/api/auth/email/verify', email_verify),
        web.post('/api/auth/telegram', telegram),
        web.post('/api/auth/logout', logout),
    ])
