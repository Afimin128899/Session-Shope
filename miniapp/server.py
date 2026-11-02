"""aiohttp API and static Mini App, served from one origin."""
import asyncio
import json
import logging
import os
import time
from collections import OrderedDict, deque
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiohttp import web

import config
from database import db
from miniapp.auth import AuthError, validate_init_data
from miniapp import storage
from utils.order_status import order_status
from utils.version import BOT_VERSION

STATIC = Path(__file__).parent / 'static'
TOKEN = web.AppKey('token', str)
BOT = web.AppKey('bot', object)
BOT_USERNAME = web.AppKey('bot_username', str)
LIMITS = web.AppKey('limits', OrderedDict)
logger = logging.getLogger(__name__)


def response(value, status=200):
    return web.Response(text=json.dumps(value, default=str, ensure_ascii=False, allow_nan=False),
                        content_type='application/json', status=status)


@web.middleware
async def security(request, handler):
    try:
        result = await handler(request)
    except AuthError as exc:
        result = response({'error': str(exc), 'code': 'unauthorized'}, 401)
    except storage.CheckoutError as exc:
        result = response({'error': str(exc), 'code': exc.code}, 409)
    except (ValueError, InvalidOperation, json.JSONDecodeError):
        result = response({'error': 'Проверьте параметры запроса.', 'code': 'invalid_request'}, 400)
    except web.HTTPException as exc:
        result = response({'error': 'Запрос недоступен.', 'code': 'http_error'}, exc.status)
    except Exception as exc:
        logger.error('Mini App request failed: %s [%s]', request.path, type(exc).__name__)
        result = response({'error': 'Сервис временно недоступен. Попробуйте позже.', 'code': 'unavailable'}, 503)
    result.headers.update({
        'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
        'Cache-Control': 'no-store',
        'Content-Security-Policy': "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org",
    })
    return result


def limited(app, user_id, purchase=False):
    limits = app[LIMITS]
    key = (user_id, purchase)
    now = time.monotonic()
    history = limits.setdefault(key, deque())
    limits.move_to_end(key)
    while history and now - history[0] >= 60:
        history.popleft()
    if len(history) >= (10 if purchase else 120):
        return True
    history.append(now)
    while len(limits) > 4096:
        limits.popitem(last=False)
    return False


@web.middleware
async def authenticate(request, handler):
    if not request.path.startswith('/api/') or request.path == '/api/health':
        return await handler(request)
    authorization = request.headers.get('Authorization', '')
    raw = authorization[4:] if authorization.startswith('tma ') else ''
    user = validate_init_data(raw, request.app[TOKEN])
    request['user'] = user
    if limited(request.app, user['id'], request.method == 'POST' and request.path == '/api/purchase'):
        return response({'error': 'Слишком много запросов. Подождите минуту.', 'code': 'rate_limited'}, 429)
    settings = await storage.access_settings()
    admin = user['id'] in config.ADMIN_IDS
    if not admin and settings.get('maintenance_mode') == '1':
        return response({'error': 'Идут технические работы. Попробуйте позже.', 'code': 'maintenance'}, 503)
    if not admin and settings.get('sub_channel_enabled') == '1':
        channel = settings.get('sub_channel_id')
        bot = request.app[BOT]
        if not channel or bot is None:
            return response({'error': 'Проверка подписки временно недоступна.', 'code': 'unavailable'}, 503)
        member = await bot.get_chat_member(channel, user['id'])
        if member.status not in {'creator', 'administrator', 'member'} and not getattr(member, 'is_member', False):
            return response({'error': 'Сначала подпишитесь на канал в боте.', 'code': 'subscription_required'}, 403)
    await db.create_user(user['id'], user['username'])
    return await handler(request)


def page_number(request):
    value = request.query.get('page', '0')
    if not value.isascii() or not value.isdigit() or len(value) > 4 or int(value) > 1000:
        raise ValueError
    return int(value)


def order_id(request):
    value = request.match_info['id']
    if not value.isascii() or not value.isdigit() or len(value) > 10 or not 0 < int(value) <= 2147483647:
        raise ValueError
    return int(value)


async def me(request):
    user = await db.get_user(request['user']['id'])
    return response({'user': request['user'], 'balance': str(user['balance']), 'balance_usdt': str(user['balance_usdt']),
                     'bot_username': request.app[BOT_USERNAME], 'version': BOT_VERSION})


async def catalog(request):
    sort = request.query.get('sort', 'new')
    category = request.query.get('category', '')
    query = request.query.get('q', '').strip()
    if sort not in {'new', 'price_asc', 'price_desc'} or len(category) > 64 or len(query) > 100:
        raise ValueError
    return response(await storage.catalog(request['user']['id'], category, query, sort, page_number(request)))


async def purchase(request):
    if request.content_type != 'application/json':
        raise ValueError
    body = await request.json()
    if not isinstance(body, dict) or type(body.get('account_id')) is not int or not 0 < body['account_id'] <= 2147483647:
        raise ValueError
    if not isinstance(body.get('price'), str) or len(body['price']) > 24:
        raise ValueError
    quoted = Decimal(body['price'])
    if not quoted.is_finite() or quoted < 0 or quoted != storage.money(quoted):
        raise ValueError
    result = await storage.checkout(request['user']['id'], body['account_id'], quoted)
    return response(result, 201)


async def orders(request):
    result = await storage.orders(request['user']['id'], page_number(request))
    for row in result['items']:
        row['status_label'] = order_status(row)
    return response(result)


async def order_detail(request):
    row = await db.get_purchase_for_user(order_id(request), request['user']['id'])
    if not row:
        return response({'error': 'Покупка не найдена.', 'code': 'not_found'}, 404)
    if row.get('status') == 'refunded':
        row['password'] = None
    return response({key: row.get(key) for key in ('id', 'number', 'password', 'paid_amount', 'currency', 'date', 'status', 'ticket_status')} |
                    {'name': row.get('country', 'Аккаунт'), 'status_label': order_status(row)})


async def health(request):
    return response({"status": "ok", "version": BOT_VERSION})


async def index(request):
    return web.Response(text=(STATIC / 'index.html').read_text(), content_type='text/html')


def create_app(*, token=None, bot=None, bot_username=''):
    app = web.Application(middlewares=[security, authenticate], client_max_size=8192)
    app[TOKEN] = token if token is not None else config.BOT_TOKEN
    app[BOT] = bot
    app[BOT_USERNAME] = bot_username
    app[LIMITS] = OrderedDict()
    app.add_routes([
        web.get('/', index), web.get('/api/health', health),
        web.get('/api/me', me), web.get('/api/catalog', catalog), web.post('/api/purchase', purchase),
        web.get('/api/orders', orders), web.get('/api/orders/{id}', order_detail),
        web.static('/assets', STATIC, show_index=False, follow_symlinks=False),
    ])
    return app


async def start_server(bot, *, host=None, port=None):
    username = os.getenv('BOT_USERNAME', '').lstrip('@')
    if not username:
        username = (await bot.get_me()).username or ''
    runner = web.AppRunner(create_app(bot=bot, bot_username=username), access_log=None)
    await runner.setup()
    try:
        await web.TCPSite(runner, host or os.getenv('MINIAPP_HOST', '127.0.0.1'),
                          port if port is not None else int(os.getenv('MINIAPP_PORT', '8080'))).start()
    except BaseException:
        await runner.cleanup()
        raise
    return runner


async def standalone():
    from aiogram import Bot
    await db.init_db()
    async with Bot(config.BOT_TOKEN) as bot:
        runner = await start_server(bot)
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()
            db.pool.close()
            await db.pool.wait_closed()


if __name__ == '__main__':
    asyncio.run(standalone())
