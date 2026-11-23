"""Optional in-process workbench. Reuses the root bot and its admin allowlist."""
import asyncio
import logging
import os
import shutil
from pathlib import Path

from services.admin_session_workbench.engine import Engine
from services.admin_session_workbench.storage import Store

logger = logging.getLogger(__name__)
_runtime = None
_startup_error = None


class PlainTransport:
    """Workbench status strings never inherit the shop's HTML parse mode."""
    def __init__(self, bot):
        self.bot = bot

    async def send_message(self, chat_id, text, **kwargs):
        kwargs['parse_mode'] = None
        return await self.bot.send_message(chat_id, text, **kwargs)

    async def send_document(self, chat_id, document, **kwargs):
        kwargs['parse_mode'] = None
        return await self.bot.send_document(chat_id, document, **kwargs)


class AdminEngine(Engine):
    async def run_job(self, job):
        import config
        if job['mode'] != 'migrate_clean':
            self.store.update(job['id'], state='cancelled', stage='Режим не поддерживается отдельным админским инструментом')
            return
        if job['owner'] not in config.ADMIN_IDS:
            self.store.update(job['id'], state='cancelled', stage='Административный доступ отозван')
            return
        await super().run_job(job)


def data_directory():
    mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH', '').strip()
    configured = os.getenv('ADMIN_SESSION_DATA_DIR', '').strip()
    base = Path(mount or os.getenv('DATA_DIR') or 'runtime')
    root = Path(configured) if configured else base / 'admin-sessions'
    root = root.resolve()
    if os.getenv('RAILWAY_ENVIRONMENT_ID'):
        if not mount or not root.is_relative_to(Path(mount).resolve()):
            raise ValueError('В Railway подключите Volume и разместите ADMIN_SESSION_DATA_DIR внутри него.')
    return root


class Workbench:
    def __init__(self, bot, root, api_id, api_hash, concurrency=1, retention=7):
        self.bot_id = bot.id
        self.root = Path(root)
        self.store = Store(self.root)
        shutil.rmtree(self.root / 'staging', ignore_errors=True)
        for work in (self.root / 'work').glob('*'):
            job = self.store.get(work.name)
            if job and (work / 'new.session').exists():
                continue  # May be the only new authorization after a crash.
            shutil.rmtree(work, ignore_errors=True)
        self.engine = AdminEngine(self.store, PlainTransport(bot), api_id, api_hash, concurrency, retention)
        self.task = None
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def start(self):
        self.task = asyncio.create_task(self.engine.loop(), name='admin-session-workbench')
        return self

    def healthy(self):
        return self.task is None or not self.task.done()

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await self.engine.close()
        self.store.db.close()


async def start(bot):
    global _runtime, _startup_error
    import config
    try:
        if config.TELEGRAM_API_ID <= 0 or not config.TELEGRAM_API_HASH:
            raise ValueError('Для инструмента нужны TELEGRAM_API_ID и TELEGRAM_API_HASH сервиса.')
        concurrency = int(os.getenv('ADMIN_SESSION_CONCURRENCY', '1'))
        retention = int(os.getenv('ADMIN_SESSION_RETENTION_DAYS', '7'))
        if not 1 <= concurrency <= 8 or not 1 <= retention <= 365:
            raise ValueError('ADMIN_SESSION_CONCURRENCY: 1–8; ADMIN_SESSION_RETENTION_DAYS: 1–365.')
        _runtime = Workbench(bot, data_directory(), config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH,
                             concurrency, retention).start()
        _startup_error = None
        logger.info('Admin session workbench started; no extra polling process')
    except Exception as exc:
        _startup_error = ('Подключите постоянный каталог и проверьте TELEGRAM_API_ID, TELEGRAM_API_HASH, '
                          'ADMIN_SESSION_DATA_DIR. В Railway нужен Volume.')
        logger.error('Admin session workbench unavailable [%s]', type(exc).__name__)
        _runtime = None
    return _runtime


def current():
    if _runtime is None or not _runtime.healthy():
        raise RuntimeError(_startup_error or 'Инструмент недоступен; проверьте его настройки и перезапустите сервис.')
    return _runtime


async def stop():
    global _runtime
    if _runtime:
        await _runtime.close()
        _runtime = None
