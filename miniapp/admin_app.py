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
        return response({'user': request['user'], 'is_admin': True})

    app.add_routes([
        web.get('/admin-app', index),
        web.get('/admin-app/', index),
        web.get('/api/admin/identity', identity),
        web.static('/admin-assets', STATIC, show_index=False, follow_symlinks=False),
    ])
