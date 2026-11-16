"""Main-owner lifecycle controls and narrowly scoped partner moderation/content."""
from aiohttp import web
from database import partners
from database.admin_web import rows
from database.advertising import AccessDenied
from utils.partner_context import CURRENT,bot_id


def register(app,response):
    async def management(request):
        actor=request['user']['id'];partners.owner(actor)
        if request.method=='POST':
            body=await request.json()
            if not isinstance(body,dict) or type(body.get('bot_id')) is not int:raise ValueError('Укажите бота.')
            identity=body['bot_id'];action=body.get('action')
            if action=='close':await partners.close(actor,identity)
            elif action in {'enable','pause'}:await partners.enable(actor,identity,action=='enable')
            else:raise ValueError('Недоступное действие.')
        return response({'items':await partners.listing(actor)})

    async def content(request):
        actor=request['user']['id'];p=CURRENT.get()
        if p and actor!=p['owner_id']:raise AccessDenied('Нет доступа.')
        if not p:partners.owner(actor)
        if request.method=='POST':
            body=await request.json()
            if not isinstance(body,dict) or body.get('key')=='photo':raise ValueError('Фото изменяется через бота.')
            await partners.set_content(actor,bot_id(),body.get('key'),body.get('value'))
        return response({'content':await partners.content(bot_id()),'labels':sorted(partners.LABELS)})

    async def bans(request):
        actor=request['user']['id'];p=CURRENT.get()
        if not p or actor!=p['owner_id']:raise AccessDenied('Нет доступа.')
        if request.method=='POST':
            body=await request.json()
            if not isinstance(body,dict):raise ValueError('Некорректная форма.')
            await partners.ban(actor,bot_id(),body.get('user_id'),body.get('reason'),body.get('enabled',True))
        return response({'items':await rows('SELECT user_id,reason,active,created_at FROM global_user_bans WHERE source_bot=%s ORDER BY created_at DESC LIMIT 100',(bot_id(),))})

    app.add_routes([web.get('/api/admin/partners',management),web.post('/api/admin/partners',management),web.get('/api/admin/partner-content',content),web.post('/api/admin/partner-content',content),web.get('/api/admin/partner-bans',bans),web.post('/api/admin/partner-bans',bans)])
