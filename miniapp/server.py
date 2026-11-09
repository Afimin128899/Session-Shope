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
from database import db, commerce, quality, coupons, tickets, welcome
from services import payments
from services.demo import STORE
from miniapp.auth import AuthError, validate_init_data
from miniapp import storage
from utils.order_status import order_status
from utils.version import BOT_VERSION
from utils.i18n import LANGUAGE, language, tr
from database.shop_control import public_status

STATIC = Path(__file__).parent / 'static'
TOKEN = web.AppKey('token', str)
BOT = web.AppKey('bot', object)
BOT_USERNAME = web.AppKey('bot_username', str)
LIMITS = web.AppKey('limits', OrderedDict)
logger = logging.getLogger(__name__)


@web.middleware
async def locale_context(request, handler):
    token = LANGUAGE.set('ru')
    try:
        result = await handler(request)
        result.headers['Content-Language'] = LANGUAGE.get()
        return result
    finally:
        LANGUAGE.reset(token)


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
    except (ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        if request.path.startswith('/api/admin/'):
            result = response({'error': str(exc) or tr('Проверьте поля формы.'), 'code': 'invalid_request'}, 400)
        else:
            result = response({'error': tr('Проверьте параметры запроса.'), 'code': 'invalid_request'}, 400)
    except web.HTTPException as exc:
        result = response({'error': tr('Запрос недоступен.'), 'code': 'http_error'}, exc.status)
    except Exception as exc:
        logger.error('Mini App request failed: %s [%s]', request.path, type(exc).__name__)
        result = response({'error': tr('Сервис временно недоступен. Попробуйте позже.'), 'code': 'unavailable'}, 503)
    result.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer', 'Cache-Control': 'no-store', 'Content-Security-Policy': "default-src 'self'; script-src 'self' https://telegram.org; style-src 'self'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors https://web.telegram.org https://*.telegram.org"})
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
    if request.path.startswith('/api/demo/'):
        if user['id'] not in config.ADMIN_IDS:
            return response({'error': tr('Тестовый режим доступен только администратору.'), 'code': 'forbidden'}, 403)
        if limited(request.app, user['id'], False):
            return response({'error': tr('Подождите перед повтором.'), 'code': 'rate_limited'}, 429)
        return await handler(request)
    profile = await db.get_user(user['id'])
    LANGUAGE.set(language(profile.get('language') if profile else 'ru'))
    request['language'] = LANGUAGE.get()
    if user['id'] not in config.ADMIN_IDS:
        STORE.exit(user['id'])
    if STORE.active(user['id']) and request.method not in {'GET', 'HEAD'}:
        return response({'error': tr('Сначала завершите тестовый режим. Рабочие операции отключены.'), 'code': 'test_mode'}, 409)
    if request.path.startswith('/api/admin/') or request.path == '/api/admin':
        if user['id'] not in config.ADMIN_IDS:
            return response({'error': tr('Доступ только администратору.'), 'code': 'forbidden'}, 403)
    if limited(request.app, user['id'], request.method == 'POST' and (request.path in {'/api/purchase', '/api/cart/checkout', '/api/invoices', '/api/promo/preview', '/api/promo/redeem', '/api/reviews', '/api/rewards/claim', '/api/support'} or request.path.endswith('/warranty-claim') or (request.path.startswith('/api/support/') and request.method=='POST'))):
        return response({'error': tr('Слишком много запросов. Подождите минуту.'), 'code': 'rate_limited'}, 429)
    settings = await storage.access_settings()
    request['shop_status'] = public_status(settings)
    admin = user['id'] in config.ADMIN_IDS
    if not admin and settings.get('maintenance_mode') == '1' and (request.path not in {'/api/status', '/api/preferences/language'}):
        return response({'error': tr('🛠 Идут технические работы. Попробуйте позже.'), 'code': 'maintenance', 'shop_status': request['shop_status']}, 503)
    if not admin and settings.get('sub_channel_enabled') == '1' and (request.path not in {'/api/status', '/api/preferences/language'}):
        channel = settings.get('sub_channel_id')
        bot = request.app[BOT]
        if not channel or bot is None:
            return response({'error': tr('Проверка подписки временно недоступна.'), 'code': 'unavailable'}, 503)
        member = await bot.get_chat_member(channel, user['id'])
        if member.status not in {'creator', 'administrator', 'member'} and (not getattr(member, 'is_member', False)):
            return response({'error': tr('Сначала подпишитесь на канал в боте.'), 'code': 'subscription_required'}, 403)
    await db.create_user(user['id'], user['username'], welcome_bonus=True)
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
                     'language':language(user.get('language')), 'shop_status':request['shop_status'],
                     'welcome_bonus': str(await welcome.received(request['user']['id'])),
                     'bot_username': request.app[BOT_USERNAME], 'test_mode_active': STORE.active(request['user']['id']), 'version': BOT_VERSION, 'is_admin': request['user']['id'] in config.ADMIN_IDS})


async def referral_info(request):
    from database import referrals
    result = await referrals.summary(request['user']['id'])
    result.update(await referrals.invited(request['user']['id'], page_number(request)))
    result['bot_username'] = request.app[BOT_USERNAME]
    return response(result)


async def spam_statuses(request):
    from database import spam_checks
    raw = request.query.get('ids', '')
    if len(raw) > 600:
        raise ValueError
    parts = raw.split(',')
    if not 1 <= len(parts) <= 50 or any(not v.isascii() or not v.isdigit() or not 0 < int(v) <= 2147483647 for v in parts):
        raise ValueError
    ids = [int(v) for v in parts]
    if len(set(ids)) != len(ids):
        raise ValueError
    return response({'items': await spam_checks.catalog_status(request['user']['id'], ids)})


async def shop_status(request):
    return response({'shop_status':request['shop_status'], 'language':request['language']})


async def save_language(request):
    from database.preferences import set_language
    body=await json_body(request)
    value=await set_language(request['user']['id'], body.get('language'))
    LANGUAGE.set(value)
    return response({'language':value})


async def catalog(request):
    sort = request.query.get('sort', 'new')
    category = request.query.get('category', '')
    query = request.query.get('q', '').strip()
    if sort not in {'new', 'price_asc', 'price_desc', 'discount'} or len(category) > 64 or len(query) > 100:
        raise ValueError
    bounds = []
    for key in ('min_price', 'max_price'):
        value = request.query.get(key, '')
        bound = Decimal(value) if value else None
        if bound is not None and (not bound.is_finite() or not 0 <= bound <= 100000000):
            raise ValueError
        bounds.append(bound)
    if all(v is not None for v in bounds) and bounds[0] > bounds[1]:
        raise ValueError
    premium=request.query.get('premium','')
    age=request.query.get('min_age','')
    if premium not in {'','0','1'} or (age and (not age.isascii() or not age.isdigit() or int(age)>10000)): raise ValueError
    return response(await storage.catalog(request['user']['id'], category, query, sort, page_number(request), min_price=bounds[0], max_price=bounds[1],premium=int(premium) if premium else None,min_age=int(age) if age else None))


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
    query=request.query.get('q','').strip()
    if len(query)>100: raise ValueError
    result = await storage.orders(request['user']['id'], page_number(request),query)
    for row in result['items']:
        row['status_label'] = order_status(row)
    return response(result)


async def order_detail(request):
    row = await db.get_purchase_for_user(order_id(request), request['user']['id'])
    if not row:
        return response({'error': tr('Покупка не найдена.'), 'code': 'not_found'}, 404)
    if row.get('status') == 'refunded':
        row['password'] = None
    result = {key: row.get(key) for key in ('id', 'account_id', 'telegram_user_id', 'number', 'password', 'paid_amount', 'currency', 'date', 'status', 'ticket_status')} | {'name': row.get('country', tr('Аккаунт')), 'product_id': f"#{row['account_id']:02d}" if row.get('account_id') else None, 'status_label': order_status(row)}
    result['warranty'] = quality.warranty(row)
    result['characteristics'] = json.loads(row.get('attributes_snapshot') or '{}')
    from database.spam_checks import public as spam_status
    result['characteristics']['spam_check'] = spam_status(result['characteristics'])
    result['review'] = await quality.my_review(request['user']['id'], row['id'])
    return response(result)


async def collection(request):
    return response(await storage.catalog(request['user']['id'], page=page_number(request),
                                          favorites=request.path.endswith('favorites'), cart=request.path.endswith('cart')))


async def json_body(request):
    if request.content_type != 'application/json':
        raise ValueError
    body = await request.json()
    if not isinstance(body, dict):
        raise ValueError
    return body


def account_value(body):
    value = body.get('account_id')
    if type(value) is not int or not 0 < value <= 2147483647:
        raise ValueError
    return value


async def collection_update(request):
    body = await json_body(request)
    account = account_value(body)
    try:
        if request.path.endswith('favorites'):
            if type(body.get('enabled')) is not bool:
                raise ValueError
            await commerce.favorite(request['user']['id'], account, body['enabled'])
        elif request.method == 'DELETE':
            await commerce.remove_from_cart(request['user']['id'], account)
        else:
            await commerce.add_to_cart(request['user']['id'], account)
    except ValueError as exc:
        raise storage.CheckoutError(str(exc)) from None
    return response({'ok': True})


async def cart_checkout(request):
    body = await json_body(request)
    items = body.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise ValueError
    for item in items:
        if not isinstance(item, dict):
            raise ValueError
        account_value(item)
        if 'spam_status' in item and (not isinstance(item['spam_status'],str) or item['spam_status'] not in {'not_checked','clear','limited','permanent','unknown','error'}):
            raise ValueError
        if 'warranty_hours' in item and item['warranty_hours'] is not None and (type(item['warranty_hours']) is not int or not 0<=item['warranty_hours']<=8760):
            raise ValueError
        price = item.get('price')
        if not isinstance(price, str) or len(price) > 24:
            raise ValueError
        amount = Decimal(price)
        if not amount.is_finite() or amount < 0 or amount != storage.money(amount):
            raise ValueError
    promo = body.get('promo_code')
    if promo is not None:
        promo = coupons.code(promo)
        total = body.get('expected_total')
        if not isinstance(total,str) or len(total)>24 or not Decimal(total).is_finite() or Decimal(total)<0:
            raise ValueError
        result = await storage.checkout_cart(request['user']['id'],items,promo,Decimal(total))
    else:
        total=body.get('expected_total')
        if total is not None and (not isinstance(total,str) or len(total)>24 or not Decimal(total).is_finite()): raise ValueError
        result = await storage.checkout_cart(request['user']['id'],items,expected_total=Decimal(total)) if total else await storage.checkout_cart(request['user']['id'],items)
    return response(result,201)


async def payment_methods(request):
    return response({'items': await payments.get_methods()})


async def create_invoice(request):
    body = await json_body(request)
    if body.get('provider') == 'stars':
        from services.stars import create_invoice as stars_invoice
        if type(body.get('stars')) is not int: raise ValueError
        return response(await stars_invoice(request.app[BOT],request['user']['id'],body['stars']),201)
    if not isinstance(body.get('amount'), str) or len(body['amount']) > 24 or not isinstance(body.get('provider'), str):
        raise ValueError
    try:
        result = await payments.create_deposit(request['user']['id'], request['user']['username'], body['provider'], body['amount'])
    except ValueError as exc:
        raise storage.CheckoutError(str(exc), getattr(exc, 'code', 'invoice_unavailable')) from None
    return response(result, 201)


async def invoice_status(request):
    provider, invoice_id = (request.match_info['provider'], request.match_info['invoice'])
    if provider not in {*payments.PROVIDERS, 'stars'} or len(invoice_id) > 128:
        raise ValueError
    row = await commerce.invoice(provider, invoice_id, request['user']['id'])
    if not row:
        return response({'error': tr('Счёт не найден.'), 'code': 'not_found'}, 404)
    if provider == 'stars' and row['status'] == 'pending':
        from datetime import datetime, timezone
        if row['expires_at'] <= datetime.now(timezone.utc).replace(tzinfo=None):
            await commerce.finish_invoice(provider, invoice_id, 'expired')
            row['status'] = 'expired'
    return response({key: row[key] for key in ('status', 'amount_rub', 'credited_amount')})


async def promo_preview(request):
    body=await json_body(request)
    try:
        return response(await coupons.preview(request['user']['id'],body.get('code')))
    except ValueError as exc:
        raise storage.CheckoutError(str(exc),'invalid_promo') from None


async def promo_redeem(request):
    body=await json_body(request)
    try:
        amount=await coupons.redeem_balance(request['user']['id'],body.get('code'))
        return response({'credited':str(amount)})
    except ValueError as exc:
        raise storage.CheckoutError(str(exc),'invalid_promo') from None


async def review_list(request):
    return response(await quality.reviews(page_number(request)))


async def review_save(request):
    body=await json_body(request)
    purchase=body.get('purchase_id')
    if type(purchase) is not int or not 0<purchase<=2147483647: raise ValueError
    try:
        await quality.save_review(request['user']['id'],purchase,body.get('rating'),body.get('body'))
    except ValueError as exc:
        raise storage.CheckoutError(str(exc),'invalid_review') from None
    return response({'ok':True},201)


async def warranty_claim(request):
    body = await json_body(request)
    if not isinstance(body.get('body'), str):
        raise ValueError
    try:
        ticket = await tickets.create_ticket(request['user']['id'], order_id(request), body['body'], warranty=True)
    except ValueError as exc:
        raise storage.CheckoutError(str(exc), 'invalid_warranty') from None
    if request.app[BOT]:
        from handlers.tickets import notify
        await notify(request.app[BOT], config.ADMIN_IDS, ticket, 'Новое гарантийное обращение.')
    return response({'ticket_id': ticket}, 201)


async def departments(request):
    from database.sections import listing
    return response({'items':await listing(request['user']['id'])})


async def support_list(request):
    return response({'items':await tickets.inbox(request['user']['id'],page=page_number(request))})


async def support_create(request):
    body=await json_body(request)
    if not isinstance(body.get('body'),str):raise ValueError
    purchase_id=body.get('purchase_id')
    if purchase_id is None:
        identity=await tickets.create_general(request['user']['id'],body['body'])
    elif type(purchase_id) is int and 0<purchase_id<=2147483647:
        identity=await tickets.create_ticket(request['user']['id'],purchase_id,body['body'])
    else:raise ValueError
    if request.app[BOT]:
        from handlers.tickets import notify
        await notify(request.app[BOT],config.ADMIN_IDS,identity,'Новое обращение в поддержку.')
    return response({'ticket_id':identity},201)


async def support_detail(request):
    identity=order_id(request)
    row=await tickets.get_ticket(identity,request['user']['id'])
    if not row:raise web.HTTPNotFound()
    before=request.query.get('before','0')
    if not before.isascii() or not before.isdigit() or len(before)>19:raise ValueError
    messages=await tickets.web_history(identity,request['user']['id'],int(before))
    return response({'ticket':row,'messages':messages[:25],'has_more':len(messages)>25})


async def support_reply(request):
    body=await json_body(request)
    if not isinstance(body.get('body'),str):raise ValueError
    identity=order_id(request)
    await tickets.reply(identity,request['user']['id'],body['body'])
    if request.app[BOT]:
        from handlers.tickets import notify
        await notify(request.app[BOT],config.ADMIN_IDS,identity,'Новое сообщение в поддержку.')
    return response({'ok':True})


async def shop_info(request):
    from database.expansion import rules
    return response({'wholesale': await rules(), 'support_hours': await db.get_setting('support_hours', tr('График поддержки пока не указан')), 'response_time': await db.get_setting('support_eta', tr('Поддержка отвечает в порядке очереди; точное время не установлено.'))})


async def product(request):
    result = await storage.catalog(request['user']['id'], account_id=order_id(request))
    item = next((i for i in result['items'] if i['id'] == order_id(request)), None)
    if not item:
        return response({'error': tr('Товар недоступен.')}, 404)
    return response(item)


async def reward_status(request):
    from database.rewards import status
    return response(await status(request['user']['id']))


async def reward_claim(request):
    from database.rewards import claim
    try: return response(await claim(request['user']['id']))
    except ValueError as exc: raise storage.CheckoutError(str(exc),'reward_unavailable') from None


async def health(request):
    return response({"status": "ok", "version": BOT_VERSION})


async def index(request):
    return web.Response(text=(STATIC / 'index.html').read_text(), content_type='text/html')


def create_app(*, token=None, bot=None, bot_username=''):
    app = web.Application(middlewares=[locale_context, security, authenticate], client_max_size=8192)
    app[TOKEN] = token if token is not None else config.BOT_TOKEN
    app[BOT] = bot
    app[BOT_USERNAME] = bot_username
    app[LIMITS] = OrderedDict()
    from miniapp.public_info import about
    app.add_routes([
        web.get('/about', about),
        web.get('/', index), web.get('/api/health', health),
        web.get('/api/referrals',referral_info),web.get('/api/spam-status',spam_statuses),
        web.get('/api/status',shop_status),web.post('/api/preferences/language',save_language),
        web.get('/api/rewards',reward_status),web.post('/api/rewards/claim',reward_claim),
        web.get('/api/departments',departments),web.get('/api/support',support_list),web.post('/api/support',support_create),web.get('/api/support/{id}',support_detail),web.post('/api/support/{id}/reply',support_reply),
        web.get('/api/shop-info',shop_info),web.get('/api/products/{id}',product),web.get('/api/me', me), web.get('/api/catalog', catalog), web.post('/api/purchase', purchase),
        web.get('/api/favorites', collection), web.post('/api/favorites', collection_update),
        web.get('/api/cart', collection), web.post('/api/cart', collection_update), web.delete('/api/cart', collection_update),
        web.post('/api/cart/checkout', cart_checkout), web.get('/api/payment-methods', payment_methods),
        web.post('/api/invoices', create_invoice), web.get('/api/invoices/{provider}/{invoice}', invoice_status),
        web.post('/api/promo/preview',promo_preview),web.post('/api/promo/redeem',promo_redeem),
        web.get('/api/reviews',review_list),web.post('/api/reviews',review_save),
        web.post('/api/orders/{id}/warranty-claim',warranty_claim),
        web.get('/api/orders', orders), web.get('/api/orders/{id}', order_detail),
        web.static('/assets', STATIC, show_index=False, follow_symlinks=False),
    ])
    from miniapp.demo_api import register as register_demo
    register_demo(app,response)
    from miniapp.admin_api import register
    register(app,response,page_number)
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
