from pathlib import Path
from aiohttp import web
from services.demo import STORE


def register(app,response):
    async def state(request):
        return response(STORE.enter(request['user']['id']))
    async def action(request):
        if request.content_type!='application/json':raise ValueError
        body=await request.json()
        if not isinstance(body,dict):raise ValueError
        try:return response(STORE.action(request['user']['id'],body))
        except ValueError as exc:return response({'error':str(exc),'code':'demo_error'},409)
    async def exit_demo(request):
        STORE.exit(request['user']['id']);return response({'ok':True})
    async def index(request):
        return web.Response(text=(Path(__file__).parent/'static'/'demo.html').read_text(),content_type='text/html')
    app.add_routes([web.get('/demo',index),web.get('/api/demo/state',state),web.post('/api/demo/action',action),web.post('/api/demo/exit',exit_demo)])
