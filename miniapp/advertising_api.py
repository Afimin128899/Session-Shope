"""Explicit helper-only campaign endpoints; owner-only role management."""
import re
from aiohttp import web
from database import advertising as ads


def register(app,response):
    async def campaigns(request):
        user=request['user']['id']
        if request.method=='POST':
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('Проверьте поля формы.')
            result=await ads.create_campaign(user,body.get('name'))
            return response(result,201)
        from miniapp.server import BOT_USERNAME
        username=request.app[BOT_USERNAME]
        return response({'items':await ads.campaigns(user),'bot_username':username if re.fullmatch('[A-Za-z0-9_]{5,32}',username or '') else ''})

    async def users(request):
        raw=request.query.get('page','0')
        if not raw.isascii() or not raw.isdigit() or len(raw)>5:raise ValueError('Некорректная страница.')
        result=await ads.campaign_users(request['user']['id'],int(request.match_info['id']),int(raw))
        if result is None:raise web.HTTPNotFound()
        return response(result)

    async def helpers(request):
        user=request['user']['id']
        if request.method=='POST':
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('Проверьте поля формы.')
            await ads.set_helper(user,body.get('user_id'),body.get('enabled'))
        return response({'items':await ads.helpers(user)})

    app.add_routes([web.get('/api/admin/advertising',campaigns),web.post('/api/admin/advertising',campaigns),
                    web.get('/api/admin/advertising/{id:[0-9]+}/users',users),
                    web.get('/api/admin/helpers',helpers),web.post('/api/admin/helpers',helpers)])
