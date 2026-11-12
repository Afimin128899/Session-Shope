"""Category purchases, direct chat and an audited public-access switch."""
import secrets
import time
from collections import OrderedDict
from decimal import Decimal
from html import escape
from aiohttp import web
import config
from database import db,direct_chat,shop_navigation
from database.admin_tools import _transaction,_record
from utils.actions import single_action

QUOTES=web.AppKey('category_purchase_quotes',OrderedDict)


async def public_access():
    return await db.get_setting('miniapp_public_access','0') == '1'


def register(app,response):
    from miniapp.server import json_body,BOT,limited
    app[QUOTES]=OrderedDict()

    async def market(request):
        mode=request.query.get('mode','auto')
        rows=await shop_navigation.countries(request['user']['id'],mode,request.query.get('q','').strip())
        return response({'items':rows})

    async def quote(request):
        body=await json_body(request);mode=body.get('mode','auto');nation=body.get('nation')
        if not isinstance(mode,str): raise ValueError('Некорректный раздел каталога.')
        shop_navigation.validate(mode,nation)
        if limited(app,request['user']['id'],True): return response({'error':'Подождите перед повтором.'},429)
        rows,_,_=await shop_navigation.products(request['user']['id'],mode,nation,quantity=1)
        if not rows: raise ValueError('В этой категории пока нет свободных товаров.')
        key=secrets.token_urlsafe(18);now=time.time();item=rows[0]
        cache=app[QUOTES]
        for old,value in list(cache.items()):
            if value['expires']<now: cache.pop(old,None)
        cache[key]={'user':request['user']['id'],'item':item,'expires':now+300}
        while len(cache)>4096: cache.popitem(last=False)
        return response({'token':key,'name':shop_navigation.country_name(nation),'price':str(item['price']),'warranty_hours':item['warranty_hours']})

    async def buy(request):
        from miniapp import storage
        body=await json_body(request);key=body.get('token')
        if not isinstance(key,str) or not 1<=len(key)<=64: raise ValueError('Обновите предложение.')
        user=request['user']['id']
        async with single_action(user,'purchase') as acquired:
            if not acquired: return response({'error':'Покупка уже обрабатывается.'},409)
            saved=app[QUOTES].get(key)
            if not saved or saved['user']!=user or saved['expires']<time.time():
                return response({'error':'Предложение истекло. Выберите категорию заново.'},409)
            item=saved['item']
            result=await storage.checkout(user,item['id'],Decimal(str(item['price'])),warranty_hours=item['warranty_hours'],spam_status=item['spam_status'])
            app[QUOTES].pop(key,None)
            return response(result,201)

    def before(request):
        value=request.query.get('before','0')
        if not value.isascii() or not value.isdigit() or len(value)>19 or not 0<=int(value)<2**63: raise ValueError('Некорректная страница сообщений.')
        return int(value)

    async def chat(request):
        if request.method=='GET': return response(await direct_chat.history(request['user']['id'],before(request)))
        request._client_max_size=32768
        if limited(app,request['user']['id'],True): return response({'error':'Подождите перед отправкой следующего сообщения.'},429)
        body=(await json_body(request)).get('body')
        identity=await direct_chat.append(request['user']['id'],'user',body)
        bot=request.app[BOT]
        if bot:
            from handlers.direct_support import reply_keyboard
            for admin in set(config.ADMIN_IDS):
                try:
                    await bot.send_message(admin,f'<b>Сообщение из Mini App</b>\nID: <code>{request["user"]["id"]}</code>\n\n{escape(body.strip())}',parse_mode='HTML',reply_markup=reply_keyboard(request['user']['id']))
                except Exception: pass
        return response({'id':identity},201)

    async def access(request):
        if request.method=='POST':
            enabled=(await json_body(request)).get('enabled')
            if type(enabled) is not bool: raise ValueError('Укажите состояние доступа.')
            async with _transaction() as cur:
                await cur.execute("INSERT INTO settings(`key`,`value`) VALUES('miniapp_public_access',%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)",('1' if enabled else '0',))
                await _record(cur,request['user']['id'],'miniapp_public_access','settings','miniapp_public_access',{'enabled':enabled})
        return response({'enabled':await public_access()})

    async def admin_chat(request):
        if 'user' not in request.match_info: return response(await direct_chat.inbox())
        raw=request.match_info['user']
        if not raw.isascii() or not raw.isdigit() or not 0<int(raw)<2**52: raise ValueError('Некорректный пользователь.')
        user=int(raw)
        if request.method=='GET': return response(await direct_chat.history(user,before(request)))
        request._client_max_size=32768
        body=(await json_body(request)).get('body')
        identity=await direct_chat.append(user,'admin',body)
        bot=request.app[BOT]
        if bot:
            try: await bot.send_message(user,'<b>Ответ поддержки</b>\n\n'+escape(body.strip()),parse_mode='HTML')
            except Exception: pass
        return response({'id':identity},201)

    app.add_routes([web.get('/api/category-market',market),web.post('/api/category-quote',quote),web.post('/api/category-buy',buy),
        web.get('/api/chat',chat),web.post('/api/chat',chat),web.get('/api/admin/app-access',access),web.post('/api/admin/app-access',access),
        web.get('/api/admin/conversations',admin_chat),web.get('/api/admin/conversations/{user}',admin_chat),web.post('/api/admin/conversations/{user}',admin_chat)])
