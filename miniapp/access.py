"""Suspend apps independently without removing their source or stored settings."""
from aiohttp import web

CUSTOMER_ENABLED = web.AppKey('customer_miniapp_enabled', bool)
ADMIN_ENABLED = web.AppKey('admin_miniapp_enabled', bool)
ADMIN_ONLY = web.AppKey('customer_miniapp_admin_only', bool)


@web.middleware
async def app_access(request, handler):
    path = request.path
    from miniapp.browser_auth import PUBLIC_PATHS as AUTH_PATHS
    from miniapp.discovery import PUBLIC_PATHS as DISCOVERY_PATHS
    if path in ({'/about', '/api/health', '/assets/style.css', '/assets/design.css'} | DISCOVERY_PATHS):
        return await handler(request)
    if path == '/api/app-info' or path in AUTH_PATHS:
        if request.app[CUSTOMER_ENABLED] or request.app[ADMIN_ONLY]:
            return await handler(request)
    admin = path == '/admin-app' or path.startswith(('/admin-app/', '/admin-assets/', '/api/admin/')) or path == '/api/admin'
    enabled = request.app[ADMIN_ENABLED if admin else CUSTOMER_ENABLED]
    if not admin and not enabled and request.app[ADMIN_ONLY]:
        if path.startswith('/api/'):
            from miniapp.auth import resolve_identity
            from miniapp.server import TOKEN
            from config import ADMIN_IDS
            user = await resolve_identity(request, request.app[TOKEN])
            if user['id'] not in ADMIN_IDS:
                from miniapp.storefront_api import public_access
                if not await public_access():
                    return web.json_response({'error': 'Mini App доступен только администратору.', 'code': 'forbidden'}, status=403)
        # Static bootstrap contains no user data. APIs still require a verified
        # Telegram identity or an opaque browser session plus the access policy.
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
