"""Authenticated storefront selection, server-priced bulk checkout and owned exports."""
import asyncio
import io
import json
import secrets
import time
import zipfile
from collections import OrderedDict
from decimal import Decimal
from aiohttp import web
from database import db, shop_navigation, expansion
from miniapp import storage
from utils.actions import single_action
from utils.partner_context import bot_id

QUOTES = web.AppKey('configurator_quotes', OrderedDict)


def selection(body):
    country = body.get('country', 'us')
    age = body.get('age', 7)
    if not isinstance(country, str) or country not in shop_navigation.COUNTRIES:
        raise ValueError('Выберите страну.')
    if type(age) is not int or age not in {0, 7, 30, 180, 365}:
        raise ValueError('Выберите возраст аккаунта.')
    for key in ('premium', 'two_fa', 'clear'):
        if type(body.get(key, key == 'clear')) is not bool:
            raise ValueError('Проверьте параметры безопасности.')
    return ('premium' if body.get('premium', False) else 'auto',
            country + ('~clear' if body.get('clear', True) else ''),
            {'min_age': age, 'two_fa': body.get('two_fa', False)})


def totals(items, rules):
    subtotal = sum((Decimal(str(item['price'])) for item in items), Decimal(0))
    rate = Decimal(rules['percent']) if subtotal >= Decimal(rules['minimum']) else Decimal(0)
    if not rate.is_finite() or not 0 <= rate <= 50:
        raise ValueError('Оптовые условия временно недоступны.')
    total = sum((storage.money(Decimal(str(item['price'])) * (1-rate/100)) for item in items), Decimal(0))
    return str(total), str(rate)


def archive_bytes(order):
    from services.session_audit import session_file_bytes
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('account.session', session_file_bytes(order['data']))
        archive.writestr('account.json', json.dumps({key: order.get(key) for key in
            ('id', 'account_id', 'number', 'telegram_user_id', 'date', 'registration_date')}, ensure_ascii=False, default=str))
        if order.get('password') and order['password'] != '-':
            archive.writestr('2fa.txt', order['password'])
    return buffer.getvalue()


def register(app, response):
    from miniapp.server import json_body, order_id, limited
    app[QUOTES] = OrderedDict()

    async def preview(request):
        body = await json_body(request)
        mode, nation, filters = selection(body)
        items, count, _ = await shop_navigation.products(request['user']['id'], mode, nation, quantity=20, **filters)
        rules = await expansion.rules()
        quantities = []
        for size in range(1, len(items)+1):
            total, rate = totals(items[:size], rules)
            quantities.append({'quantity': size, 'total': total, 'rate': rate})
        return response({'count': count, 'unit_price': str(items[0]['price']) if items else None,
                         'quantities': quantities, 'wholesale': rules,
                         'warranty_hours': sorted({item['warranty_hours'] or 0 for item in items})})

    async def quote(request):
        user = request['user']['id']
        if limited(app, user, True):
            return response({'error': 'Подождите перед повторным резервом.'}, 429)
        body = await json_body(request)
        mode, nation, filters = selection(body)
        qty = body.get('quantity')
        if type(qty) is not int or not 1 <= qty <= 20:
            raise ValueError('Количество: от 1 до 20.')
        async with single_action(user, 'purchase') as acquired:
            if not acquired:
                return response({'error': 'Покупка уже обрабатывается.'}, 409)
            saved = await shop_navigation.reserve_bulk(user, mode, nation, qty, **filters)
            token = secrets.token_urlsafe(24)
            now = time.time()
            cache = app[QUOTES]
            for key, entry in list(cache.items()):
                if entry['expires'] <= now:
                    cache.pop(key, None)
            cache[token] = dict(saved, user=user, wallet_bot_id=bot_id(), expires=now+300)
            while len(cache) > 1000:
                cache.popitem(last=False)
            return response({'token': token, 'quantity': qty, 'total': saved['total'],
                             'rate': saved['rate'], 'expires_at': now+300,
                             'warranty_hours': sorted({item['warranty_hours'] or 0 for item in saved['items']})})

    async def buy(request):
        body = await json_body(request)
        token = body.get('token')
        if not isinstance(token, str) or len(token) > 64:
            raise ValueError('Обновите предложение.')
        user = request['user']['id']
        async with single_action(user, 'purchase') as acquired:
            if not acquired:
                return response({'error': 'Покупка уже обрабатывается.'}, 409)
            saved = app[QUOTES].get(token)
            if not saved or saved['user'] != user or saved['wallet_bot_id'] != bot_id() or saved['expires'] <= time.time():
                return response({'error': 'Резерв истёк или недоступен. Подберите аккаунты заново.'}, 409)
            result = await storage.checkout_cart(user, saved['items'], expected_total=Decimal(saved['total']))
            app[QUOTES].pop(token, None)
            return response(result, 201)

    async def archive(request):
        user, identity = request['user']['id'], order_id(request)
        async with single_action(user, f'archive:{identity}') as acquired:
            if not acquired:
                return response({'error': 'Архив уже создаётся.'}, 409)
            order = await db.get_purchase_for_user(identity, user)
            if not order:
                return response({'error': 'Покупка не найдена.'}, 404)
            if order['status'] != 'issued' or order.get('access_revoked_at') or not order.get('data') or order['data'].startswith('✅'):
                return response({'error': 'Доступ к сессии этого заказа закрыт.'}, 409)
            try:
                data = await asyncio.wait_for(asyncio.to_thread(archive_bytes, order), 15)
            except Exception:
                return response({'error': 'Не удалось создать архив. Обратитесь в поддержку.'}, 409)
            current = await db.get_purchase_for_user(identity, user)
            if not current or current['status'] != 'issued' or current.get('data') != order['data'] or current.get('access_revoked_at'):
                return response({'error': 'Доступ к заказу изменился.'}, 409)
            return web.Response(body=data, content_type='application/zip', headers={
                'Content-Disposition': f'attachment; filename="tg-order-{identity}.zip"', 'Cache-Control': 'no-store'})

    app.add_routes([web.post('/api/configurator/preview', preview), web.post('/api/configurator/quote', quote),
                    web.post('/api/configurator/buy', buy), web.get('/api/orders/{id}/archive', archive)])
