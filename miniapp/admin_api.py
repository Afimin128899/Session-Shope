"""Admin-only endpoints. Authentication and role checks run before these routes."""
from utils.i18n import tr
import asyncio
import io
import re
from html import escape
from aiohttp import web
from database import admin_web as store,admin_tools,db,tickets,expansion,quality,coupons,imports
from services import archive_import

TASKS=web.AppKey('admin_import_tasks',set)
UPLOADS=web.AppKey('admin_upload_count',dict)
NOTICES=web.AppKey('admin_notice_tasks',set)


def identifier(value, maximum=2147483647):
    if not isinstance(value, str) or not value.isascii() or (not value.isdigit()) or (not 0 < int(value) <= maximum):
        raise ValueError(tr('Некорректный ID.'))
    return int(value)


def batch_id(request):
    value = request.match_info['batch']
    if not re.fullmatch('[0-9a-f]{32}', value):
        raise ValueError(tr('Некорректный черновик.'))
    return value


async def read_body(request):
    if request.content_type != 'application/json':
        raise ValueError(tr('Ожидается JSON.'))
    if request.path.endswith('/commit'):
        request._client_max_size = 160 * 1024
    value = await request.json()
    if not isinstance(value, dict):
        raise ValueError(tr('Проверьте запрос.'))
    return value


async def send_notice(request,user,source,*values):
    from miniapp.server import BOT
    bot=request.app[BOT]
    if not bot: return
    async def deliver():
        try:
            from utils.notification_language import send_translated
            await asyncio.wait_for(send_translated(bot,user,source,*values,parse_mode='HTML'),timeout=12)
        except Exception: pass
    task=asyncio.create_task(deliver())
    request.app[NOTICES].add(task)
    task.add_done_callback(request.app[NOTICES].discard)


def register(app, response, page_number):
    app[TASKS] = set()
    app[NOTICES] = set()
    app[UPLOADS] = {'active': 0}

    async def overview(request):
        return response(await store.overview())

    async def stock(request):
        q = request.query.get('q', '').strip()
        status = request.query.get('status', 'available')
        if len(q) > 100 or status not in {'', 'available', 'review', 'sold', 'refunded', 'replaced'}:
            raise ValueError
        return response(await store.stock(q, status, page_number(request)))

    async def categories(request):
        return response({'items': await store.categories()})

    async def category_save(request):
        await store.save_category(request['user']['id'], await read_body(request))
        return response({'ok': True})

    async def stock_edit(request):
        await store.edit_stock(request['user']['id'], identifier(request.match_info['id']), await read_body(request))
        return response({'ok': True})

    async def stock_bulk(request):
        body = await read_body(request)
        await expansion.bulk_edit(request['user']['id'], body.get('ids'), body.get('field'), body.get('value'))
        return response({'ok': True})

    async def stock_review(request):
        from database.shop_control import set_review
        body = await read_body(request)
        status = await set_review(request['user']['id'], identifier(request.match_info['id']), body.get('enabled'), body.get('reason'))
        return response({'status': status})

    async def spam_all(request):
        from database.spam_checks import enqueue
        return response({'queued': await enqueue(request['user']['id'])})

    async def spam_one(request):
        from database.spam_checks import enqueue
        return response({'queued': await enqueue(request['user']['id'], identifier(request.match_info['id']))})

    async def stock_delete(request):
        account = identifier(request.match_info['id'])
        row = await db.get_account(account)
        if not row or row['status'] != 'available':
            raise ValueError(tr('Удалять можно только свободный товар.'))
        async with admin_tools._transaction() as cur:
            await cur.execute("SELECT id FROM accounts WHERE id=%s AND status='available' FOR UPDATE", (account,))
            if not await cur.fetchone():
                raise ValueError(tr('Товар уже недоступен.'))
            await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE', (account,))
            if await cur.fetchone():
                raise ValueError(tr('Товар находится в резерве покупателя.'))
            await cur.execute('SELECT id FROM purchases WHERE account_id=%s', (account,))
            if await cur.fetchone():
                raise ValueError(tr('История заказа должна сохраниться.'))
            await cur.execute('DELETE FROM accounts WHERE id=%s', (account,))
            await admin_tools._record(cur, request['user']['id'], 'web_stock_delete', 'account', account, {})
        return response({'ok': True})

    async def orders(request):
        query = request.query.get('q', '').strip()
        if len(query) > 100:
            raise ValueError
        return response(await store.orders(query, page_number(request)))

    async def order(request):
        row = await admin_tools.find_order(identifier(request.match_info['id']))
        if not row:
            raise ValueError(tr('Заказ не найден.'))
        approval = await store.rows('SELECT requester,approver,reason,amount,currency FROM refund_approvals WHERE purchase_id=%s', (row['id'],))
        row['refund_approval'] = approval[0] if approval else None
        return response(row)

    async def refund(request):
        body = await read_body(request)
        reason = body.get('reason', '')
        if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
            raise ValueError(tr('Причина: 3–500 символов.'))
        result = await expansion.request_refund(request['user']['id'], identifier(request.match_info['id']), reason.strip())
        if result and result.get('pending') and result.get('new_request'):
            import config
            for admin in set(config.ADMIN_IDS) - {request['user']['id']}:
                await send_notice(request, admin, 'Требуется согласование возврата #{0}: {1} {2}. Причина: {3}. Проверьте раздел «Возвраты» Mini App или /refund_queue.', f"{result['id']}", f"{escape(result['amount'])}", f"{escape(result['currency'])}", f'{escape(reason.strip())}')
        elif result and (not result.get('pending')):
            await send_notice(request, result['user_id'], 'По заказу #{0} возвращено {1} {2} на баланс бота.', f"{result['id']}", f"{escape(result['amount'])}", f"{escape(result['currency'])}")
        return response({'result': result})

    async def approvals(request):
        return response({'items': await store.rows("SELECT r.purchase_id,r.requester,r.approver,r.reason,r.amount,r.currency,r.created_at FROM refund_approvals r JOIN purchases p ON p.id=r.purchase_id WHERE p.status<>'refunded' ORDER BY r.created_at LIMIT 100")})

    async def approve(request):
        result = await expansion.approve_refund(request['user']['id'], identifier(request.match_info['id']))
        if result:
            await send_notice(request, result['user_id'], 'По заказу #{0} возвращено {1} {2} на баланс бота.', f"{result['id']}", f"{escape(result['amount'])}", f"{escape(result['currency'])}")
        return response({'result': result})

    async def replace(request):
        body = await read_body(request)
        new = body.get('account_id')
        reason = body.get('reason')
        if type(new) is not int or new <= 0 or (not isinstance(reason, str)):
            raise ValueError
        user = await expansion.replace(request['user']['id'], identifier(request.match_info['id']), new, reason)
        await send_notice(request, user, 'По заказу #{0} выдана гарантийная замена. Новые данные доступны в деталях заказа.', f"{identifier(request.match_info['id'])}")
        return response({'ok': True, 'user_id': user})

    async def inbox(request):
        status = request.query.get('status', 'open')
        if status not in {'open', 'closed'}:
            raise ValueError
        return response({'items': await tickets.inbox(closed=status == 'closed', page=page_number(request))})

    async def ticket(request):
        identity = identifier(request.match_info['id'])
        before = request.query.get('before', '0')
        before = identifier(before) if before != '0' else 0
        row = await tickets.get_ticket(identity)
        if not row:
            raise ValueError(tr('Обращение не найдено.'))
        messages = await store.rows('SELECT id,author_role,body,created_at,(photo_id IS NOT NULL) AS has_photo FROM support_messages WHERE ticket_id=%s' + (' AND id<%s' if before else '') + ' ORDER BY id DESC LIMIT 26', (identity, before) if before else (identity,))
        return response({'ticket': row, 'messages': messages[:25], 'has_more': len(messages) > 25})

    async def reply(request):
        body = await read_body(request)
        if not isinstance(body.get('body'), str):
            raise ValueError
        user = await tickets.reply(identifier(request.match_info['id']), request['user']['id'], body['body'], admin=True)
        from miniapp.server import BOT
        bot = request.app[BOT]
        if bot:
            await send_notice(request, user, 'Поддержка ответила на ваше обращение. Переписка доступна в боте.')
        return response({'ok': True})

    async def close(request):
        await tickets.close_ticket(identifier(request.match_info['id']), request['user']['id'])
        return response({'ok': True})

    async def photo(request):
        identity = identifier(request.match_info['id'])
        message = identifier(request.match_info['message'])
        row = await store.rows('SELECT photo_id FROM support_messages WHERE id=%s AND ticket_id=%s', (message, identity))
        if not row or not row[0]['photo_id']:
            raise ValueError(tr('Фото недоступно.'))
        from miniapp.server import BOT
        bot = request.app[BOT]
        if not bot:
            raise ValueError(tr('Бот недоступен.'))
        file = await asyncio.wait_for(bot.get_file(row[0]['photo_id']), timeout=5)
        if not file.file_size or file.file_size > 10 * 1024 * 1024:
            raise ValueError(tr('Фото слишком большое.'))
        destination = io.BytesIO()
        await bot.download_file(file.file_path, destination=destination, timeout=15)
        return web.Response(body=destination.getvalue(), content_type='image/jpeg')

    async def user(request):
        query = request.query.get('q', '')
        result = await admin_tools.find_user(query)
        return response({'user': result})

    async def balance(request):
        body = await read_body(request)
        key = body.get('operation_id')
        if not isinstance(key, str) or not re.fullmatch('[0-9a-f]{32}', key):
            raise ValueError(tr('Обновите форму операции.'))
        await admin_tools.change_balance(request['user']['id'], identifier(request.match_info['id'], 9223372036854775807), body.get('amount'), body.get('currency'), body.get('mode'), request_key=key)
        return response({'ok': True})

    async def settings(request):
        return response(await store.settings())

    async def referral_block_list(request):
        from database import referrals
        return response(await referrals.blocks(page_number(request)))

    async def referral_block_save(request):
        from database import referrals
        body = await read_body(request)
        await referrals.set_block(request['user']['id'], body.get('user_id'), body.get('blocked'), body.get('reason', ''))
        return response({'ok': True})

    async def user_referrals(request):
        from database import referrals
        owner = identifier(request.match_info['id'], 9223372036854775807)
        result = await referrals.summary(owner)
        result.update(await referrals.invited(owner, page_number(request)))
        result['user_id'] = owner
        return response(result)

    async def settings_save(request):
        await store.save_settings(request['user']['id'], await read_body(request))
        return response({'ok': True})

    async def audit(request):
        before = request.query.get('before', '0')
        return response({'items': await admin_tools.audit_entries(identifier(before) if before != '0' else 0)})

    async def promos(request):
        return response({'items': await store.rows('SELECT code,value,uses,max_uses,kind FROM promocodes ORDER BY code LIMIT 200')})

    async def promo_create(request):
        body = await read_body(request)
        if body.get('kind', 'discount') == 'discount':
            await coupons.create_discount(request['user']['id'], body.get('code'), body.get('percent'), body.get('limit'))
        elif body.get('kind') == 'balance':
            await store.create_balance_promo(request['user']['id'], body.get('code'), body.get('percent'), body.get('limit'))
        else:
            raise ValueError(tr('Неизвестный тип промокода.'))
        return response({'ok': True})

    async def promo_disable(request):
        body = await read_body(request)
        await store.disable_promo(request['user']['id'], body.get('code'))
        return response({'ok': True})

    async def perform_upload(request):
        if request.content_type != 'application/zip':
            raise ValueError(tr('Выберите ZIP архив.'))
        if request.content_length and request.content_length > archive_import.MAX_UPLOAD:
            raise ValueError(tr('Максимум 8 МБ.'))
        content = bytearray()
        async for chunk in request.content.iter_chunked(65536):
            content.extend(chunk)
            if len(content) > archive_import.MAX_UPLOAD:
                raise ValueError(tr('Максимум 8 МБ.'))
        files = await asyncio.to_thread(archive_import.inspect_archive, bytes(content))
        batch = await imports.create(request['user']['id'])
        task = asyncio.create_task(archive_import.process(request['user']['id'], batch, files))
        app[TASKS].add(task)
        task.add_done_callback(lambda completed: (app[TASKS].discard(completed), completed.exception() if not completed.cancelled() else None))
        return response({'batch_id': batch}, 202)

    async def upload(request):
        if len(app[TASKS]) + app[UPLOADS]['active'] >= 2:
            raise ValueError(tr('Сейчас проверяются два архива. Дождитесь завершения.'))
        app[UPLOADS]['active'] += 1
        try:
            return await perform_upload(request)
        finally:
            app[UPLOADS]['active'] -= 1

    async def preview(request):
        return response(await imports.preview(request['user']['id'], batch_id(request)))

    async def commit(request):
        body = await read_body(request)
        return response({'account_ids': await imports.commit(request['user']['id'], batch_id(request), body.get('items'))}, 201)

    async def discard(request):
        await imports.discard(request['user']['id'], batch_id(request))
        return response({'ok': True})

    async def jobs(request):
        return response({'items': await store.rows('SELECT id,status,created_at,expires_at FROM import_batches WHERE admin_id=%s ORDER BY created_at DESC LIMIT 20', (request['user']['id'],))})
    app.add_routes([web.get('/api/admin/referrals/blocks',referral_block_list),web.post('/api/admin/referrals/blocks',referral_block_save),web.get('/api/admin/users/{id}/referrals',user_referrals),web.post('/api/admin/spam-checks', spam_all), web.post('/api/admin/stock/{id}/spam-check', spam_one), web.post('/api/admin/stock/{id}/review', stock_review), web.get('/api/admin/overview', overview), web.get('/api/admin/stock', stock), web.post('/api/admin/stock/bulk', stock_bulk), web.patch('/api/admin/stock/{id}', stock_edit), web.delete('/api/admin/stock/{id}', stock_delete), web.get('/api/admin/categories', categories), web.post('/api/admin/categories', category_save), web.get('/api/admin/orders', orders), web.get('/api/admin/orders/{id}', order), web.post('/api/admin/orders/{id}/refund', refund), web.post('/api/admin/orders/{id}/replace', replace), web.get('/api/admin/approvals', approvals), web.post('/api/admin/approvals/{id}', approve), web.get('/api/admin/tickets', inbox), web.get('/api/admin/tickets/{id}', ticket), web.post('/api/admin/tickets/{id}/reply', reply), web.post('/api/admin/tickets/{id}/close', close), web.get('/api/admin/tickets/{id}/photos/{message}', photo), web.get('/api/admin/users', user), web.post('/api/admin/users/{id}/balance', balance), web.get('/api/admin/settings', settings), web.post('/api/admin/settings', settings_save), web.get('/api/admin/audit', audit), web.get('/api/admin/promos', promos), web.post('/api/admin/promos', promo_create), web.post('/api/admin/promos/disable', promo_disable), web.get('/api/admin/imports', jobs), web.post('/api/admin/imports', upload), web.get('/api/admin/imports/{batch}', preview), web.post('/api/admin/imports/{batch}/commit', commit), web.delete('/api/admin/imports/{batch}', discard)])

    async def lifecycle(application):
        housekeeping = asyncio.create_task(archive_import.housekeeping())
        yield
        housekeeping.cancel()
        tasks = list(application[TASKS]) + list(application[NOTICES])
        for task in tasks:
            task.cancel()
        await asyncio.gather(housekeeping, *tasks, return_exceptions=True)
    app.cleanup_ctx.append(lifecycle)
