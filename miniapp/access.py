"""Suspend apps independently without removing their source or stored settings."""
from aiohttp import web

CUSTOMER_ENABLED = web.AppKey('customer_miniapp_enabled', bool)
ADMIN_ENABLED = web.AppKey('admin_miniapp_enabled', bool)
ADMIN_ONLY = web.AppKey('customer_miniapp_admin_only', bool)


@web.middleware
async def app_access(request, handler):
    path = request.path
    if path in {'/about', '/api/health', '/assets/style.css', '/assets/design.css'}:
        return await handler(request)
    admin = path == '/admin-app' or path.startswith(('/admin-app/', '/admin-assets/', '/api/admin/')) or path == '/api/admin'
    enabled = request.app[ADMIN_ENABLED if admin else CUSTOMER_ENABLED]
    if not admin and not enabled and request.app[ADMIN_ONLY]:
        if path.startswith('/api/'):
            from miniapp.auth import validate_init_data
            from miniapp.server import TOKEN
            from config import ADMIN_IDS
            authorization = request.headers.get('Authorization', '')
            user = validate_init_data(authorization[4:] if authorization.startswith('tma ') else '', request.app[TOKEN])
            if user['id'] not in ADMIN_IDS:
                from miniapp.storefront_api import public_access
                if not await public_access():
                    return web.json_response({'error': 'Mini App доступен только администратору.', 'code': 'forbidden'}, status=403)
        # Static bootstrap contains no user data. All data and actions require
        # signed Telegram initData and the current access policy, including old links.
        enabled = True
    if not enabled:
        return web.json_response({'error': 'Mini App временно отключён.', 'code': 'app_disabled'}, status=404 if admin else 503)
    return await handler(request)


@web.middleware
async def retired_support(request, handler):
    # Run after authentication so the usual role and signature checks still apply.
    path = request.path
    if path == '/api/support' or path.startswith(('/api/support/', '/api/admin/tickets')) or path.endswith('/warranty-claim'):
        return web.json_response({'error': 'Напишите в поддержку в боте.', 'code': 'direct_support'}, status=410)
    return await handler(request)
