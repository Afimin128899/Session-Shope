"""Disposable HTTP fixture: only the isolated demo routes need no MySQL."""
import asyncio,sys
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
from test_payments import config
from test_miniapp import TEST_TOKEN
from aiohttp import web
from miniapp.server import create_app

async def main():
    config.ADMIN_IDS=[42,43]
    runner=web.AppRunner(create_app(customer_enabled=True,admin_enabled=True,token=TEST_TOKEN),access_log=None)
    await runner.setup();await web.TCPSite(runner,'127.0.0.1',8087).start()
    print('Demo fixture ready',flush=True)
    try:await asyncio.Event().wait()
    finally:await runner.cleanup()

if __name__=='__main__':asyncio.run(main())
