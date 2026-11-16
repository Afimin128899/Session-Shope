"""Partner chooses a wallet, NEVER an authentication key. All WebApp signatures use main token."""
import json
from aiohttp import web
from database import partners
from database.advertising import AccessDenied
from utils.partner_context import CURRENT,CONTENT


@web.middleware
async def partner_scope(request,handler):
    identity=request.headers.get('X-Partner-ID','') if request.path.startswith('/api/') else ''
    if not identity:return await handler(request)
    if not identity.isascii() or not identity.isdigit() or len(identity)>16 or int(identity)<=0:raise ValueError('Некорректный магазин.')
    p=await partners.get(int(identity))
    if not p or p['status']!='enabled':raise AccessDenied('Партнёрский бот отключён.')
    a=CURRENT.set(p);b=CONTENT.set(json.loads(p['content_json']))
    try:return await handler(request)
    finally:CONTENT.reset(b);CURRENT.reset(a)
