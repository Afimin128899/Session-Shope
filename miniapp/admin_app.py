"""Independent admin shell; all data comes from authenticated admin-only APIs.

The release gate in miniapp.access blocks this shell, its assets and APIs by
default. Customer files and settings are intentionally not shared or changed.
"""
from pathlib import Path
from aiohttp import web

STATIC = Path(__file__).parent / 'admin_static'


def register(app, response):
    async def index(request):
        return web.Response(text=(STATIC / 'index.html').read_text(), content_type='text/html')

    async def identity(request):
        from config import ADMIN_IDS
        if request.get('is_partner_owner'):return response({'user':request['user'],'is_admin':False,'is_helper':False,'is_partner_owner':True})
        return response({'user': request['user'], 'is_admin': request['user']['id'] in ADMIN_IDS, 'is_helper': request.get('is_helper',False)})

    app.add_routes([
        web.get('/admin-app', index),
        web.get('/admin-app/', index),
        web.get('/api/admin/identity', identity),
        web.static('/admin-assets', STATIC, show_index=False, follow_symlinks=False),
    ])
