import asyncio
import hashlib
import logging
import traceback
import json
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from telethon import errors, functions
from .files import persist_zip
from .checkpoints import persist_new_session
from .cleanup import deep_clean_account
from .telegram import make_client, authorization, migrate, verify_new, UserFacingError


logger = logging.getLogger(__name__)


class Engine:
    def __init__(self, store, bot, api_id, api_hash, concurrency=2, retention_days=7):
        self.store, self.bot = store, bot
        self.api_id, self.api_hash = api_id, api_hash
        self.concurrency = concurrency
        self.retention = retention_days * 86400
        self.tasks, self.inputs = {}, {}
        self.stopping = False

    async def report(self, job, text):
        self.store.update(job['id'], stage=text)
        try:
            await self.bot.send_message(job['owner'], f"Задача {job['id']}: {text}")
        except Exception:
            pass  # Diagnostic delivery must not invalidate a durable result.

    async def ask(self, job, kind, prompt):
        future = asyncio.get_running_loop().create_future()
        key = (job['owner'], job['id'])
        self.inputs[key] = (kind, future)
        phase = ('2/4 ' if kind == 'code' else '3/4 ') if job.get('mode') == 'migrate_clean' else ''
        await self.report(job, f'{phase}Ожидание {"кода" if kind == "code" else "пароля 2FA"}. {prompt}\nОтветьте: /session_tool_input {job["id"]} значение\nСообщение будет удалено по возможности.')
        try:
            return await asyncio.wait_for(future, timeout=600)
        except asyncio.TimeoutError:
            raise UserFacingError(f'Таймаут ручного ввода {kind}') from None
        finally:
            self.inputs.pop(key, None)

    def answer(self, owner, ident, text):
        pending = self.inputs.get((owner, ident))
        if pending and not pending[1].done():
            pending[1].set_result(text)
            return True
        return False

    async def deliver(self, job):
        from aiogram.types import FSInputFile
        try:
            caption = f"Задача {job['id']}\n{job['stage']}"
            if job['state'] != 'done':
                caption += '\nСохранённая копия новой сессии; операция не завершена успешно.'
            await self.bot.send_document(job['owner'], FSInputFile(job['result'], filename=f"new-session-{job['id']}.zip"), caption=caption[:1000])
            self.store.update(job['id'], delivered=1)
        except Exception:
            self.store.update(job['id'], stage=job['stage']+'; ошибка отправки — откройте «Мои результаты»')

    async def migrate_clean(self, job, old, new, output, config, expected_id):
        phase = 2
        async def progress(text):
            nonlocal phase
            if text in {'Вход в новую авторизацию', 'Новая авторизация подтверждена'}:
                phase = 3
            await self.report(job, f'{phase}/4 {text}')
        await self.report(job, '2/4 Запрос и получение кода новой авторизации')
        await migrate(old, new, lambda kind, text: self.ask(job, kind, text),
                      progress, config)
        await verify_new(new, expected_id)
        await self.report(job, '3/4 Новый вход подтверждён. Сохраняю новую сессию')
        old_key = getattr(getattr(getattr(old, 'session', None), 'auth_key', None), 'key', None)
        new_key = getattr(getattr(getattr(new, 'session', None), 'auth_key', None), 'key', None)
        if isinstance(old_key, bytes) and isinstance(new_key, bytes) and old_key == new_key:
            raise UserFacingError('Независимая новая авторизация не создана; старая сохранена')
        safe = {key: value for key, value in config.items() if key in {
            'device_model', 'system_version', 'app_version', 'lang_code', 'system_lang_code'}}
        await new.disconnect()
        saved = persist_new_session(self.store.root, job['owner'], job['id'], 'before_cleanup', output, safe)
        self.store.update(job['id'], result=str(saved.archive), stage='3/4 Новая сессия сохранена до очистки')
        await self.report(job, '4/4 Очистка аккаунта через новую авторизацию')
        await new.connect()
        engine = self
        class Reporter:
            async def update(self, text, **kwargs):
                await engine.report(job, f'4/4 {text}')
        report = await deep_clean_account(new, Reporter())
        await verify_new(new, expected_id)
        await new.disconnect()
        saved = persist_new_session(self.store.root, job['owner'], job['id'], 'after_cleanup', output, safe)
        self.store.update(job['id'], result=str(saved.archive), stage='4/4 Результат сохранён; исходная авторизация ещё активна')
        if report.errors or report.dialogs_failed:
            raise UserFacingError(f'Очистка частичная: ошибок {len(report.errors)}, диалогов {report.dialogs_failed}. '
                                  'Новая сессия сохранена; старая авторизация не отзывалась')
        await self.report(job, '4/4 Результат сохранён. Завершаю только исходную авторизацию')
        try:
            async with asyncio.timeout(30):
                result = await old(functions.auth.LogOutRequest())
            if not result:
                raise UserFacingError('Выход из старой авторизации не подтверждён; новая сессия сохранена')
        except (errors.AuthKeyUnregisteredError, errors.SessionRevokedError, errors.SessionExpiredError):
            pass  # Source already revoked; the saved new authorization stays active.
        return str(saved.archive)

    def fail(self, ident, state, reason):
        stage = self.store.get(ident)['stage'] or ''
        prefix = stage[:4] if len(stage) >= 4 and stage[0] in '1234' and stage[1:4] == '/4 ' else ''
        self.store.update(ident, state=state, stage=prefix+reason)

    async def run_job(self, job):
        ident = job['id']
        work = self.store.root / 'work' / ident
        clients = []
        combined = job['mode'] == 'migrate_clean'
        try:
            if combined:
                await self.report(job, '1/4 Проверка исходного файла и подключение к сессии')
            work.mkdir(parents=True, exist_ok=True, mode=0o700)
            original = Path(job['source'])
            copied = work / 'source.session'
            shutil.copyfile(original, copied)
            config = json.loads(job['config'])
            old = make_client(copied, config, self.api_id, self.api_hash)
            clients.append(old)
            await self.report(job, '1/4 Подключение к исходной сессии' if combined else 'Подключение')
            await old.connect()
            status = await authorization(old)
            await self.report(job, f'1/4 Исходная авторизация: {status}' if combined else status)
            if status != 'Активна':
                raise UserFacingError(status)
            # Resolve real account ID before any operation; aliases of a session share a lock.
            me = await old.get_me()
            account = f'tg:{me.id}'
            conflict = self.store.db.execute("SELECT id FROM jobs WHERE account=? AND state='running' AND id<>?", (account, ident)).fetchone()
            if conflict:
                self.store.update(ident, state='queued', stage='Ожидание блокировки аккаунта')
                return
            self.store.db.execute('INSERT INTO aliases VALUES(?,?) ON CONFLICT(fingerprint) DO UPDATE SET account=excluded.account',
                                  (session_fingerprint(original), account))
            self.store.db.execute('UPDATE jobs SET account=? WHERE id=?', (account, ident))
            remaining = self.store.remaining(account)
            if remaining:
                self.store.update(ident, state='queued', stage=f'Ожидание FloodWait: {remaining} с')
                return
            output = copied
            mode = job['mode']
            if mode in {'migrate', 'migrate_clean'}:
                output = work / 'new.session'
                new = make_client(output, config, self.api_id, self.api_hash)
                clients.append(new)
                if combined:
                    await self.report(job, '2/4 Подготовка запроса кода новой авторизации')
                await new.connect()
                if combined:
                    result = await self.migrate_clean(job, old, new, output, config, me.id)
                else:
                    await migrate(old, new, lambda kind, text: self.ask(job, kind, text), lambda text: self.report(job, text), config)
            elif mode == 'terminate':
                await old(functions.auth.ResetAuthorizationsRequest())
                await self.report(job, 'Другие авторизации завершены; текущая сохранена')
            elif mode == 'spam':
                async with old.conversation('@SpamBot', timeout=30, exclusive=True) as conversation:
                    await conversation.send_message('/start')
                    reply = await conversation.get_response()
                    # Send privately to owner; never log server message contents.
                    await self.bot.send_message(job['owner'], 'Ответ официального @SpamBot:\n' + (reply.raw_text or '')[:3500])
            elif mode == 'clear_drafts':
                await old(functions.messages.ClearAllDraftsRequest())
                await self.report(job, 'Облачные черновики сообщений удалены')
            elif mode == 'clear_contacts':
                contacts = await old(functions.contacts.GetContactsRequest(hash=0))
                if contacts.users:
                    await old(functions.contacts.DeleteContactsRequest(id=contacts.users))
                await self.report(job, 'Контакты удалены')
            elif mode != 'check':
                raise UserFacingError('Неизвестный режим')
            # Flush SQLite and disconnect before archiving, especially the new auth key.
            for client in reversed(clients):
                await client.disconnect()
            clients.clear()
            if not combined:
                result = persist_zip(self.store.root / 'results', ident, output, config)
            stage = ('4/4 Готово: новая авторизация сохранена, очистка выполнена, старая завершена' if combined else 'Готово')
            self.store.update(ident, state='done', stage=stage, result=result)
            await self.deliver(self.store.get(ident))
        except asyncio.CancelledError:
            if self.store.get(ident)['state'] != 'done':
                self.fail(ident, 'cancelled', 'Отменена; исходный файл сохранён')
            raise
        except errors.FloodWaitError as exc:
            current_account = self.store.get(ident)['account']
            self.store.cooldown(current_account, exc.seconds)
            self.store.cooldown(job['account'], exc.seconds)
            self.fail(ident, 'blocked', f'Telegram FloodWait: {exc.seconds} с; автоматического повтора нет')
        except UserFacingError as exc:
            self.fail(ident, 'failed', str(exc))
        except (errors.PhoneCodeInvalidError, errors.PhoneCodeExpiredError):
            self.fail(ident, 'failed', 'Код неверен или истёк; исходный файл сохранён')
        except errors.PasswordHashInvalidError:
            self.fail(ident, 'failed', 'Пароль 2FA неверен; исходный файл сохранён')
        except asyncio.TimeoutError:
            self.fail(ident, 'failed', 'Таймаут подключения или ответа Telegram')
        except OSError:
            self.fail(ident, 'failed', 'Ошибка подключения или постоянного диска; исходный файл сохранён')
        except Exception as exc:
            frames = ' > '.join(f'{Path(frame.filename).name}:{frame.lineno}:{frame.name}'
                                for frame in traceback.extract_tb(exc.__traceback__)[-8:])
            logger.error('task=%s stage=%s error=%s frames=%s', ident,
                         self.store.get(ident)['stage'], type(exc).__name__, frames)
            # Only class name; exception strings may contain secrets or service text.
            self.fail(ident, 'failed', f'Ошибка {type(exc).__name__}; исходный файл сохранён')
        finally:
            for client in reversed(clients):
                try:
                    await client.disconnect()
                except Exception:
                    pass
            current = self.store.get(ident)
            if combined and not current['result'] and (work / 'new.session').exists():
                # Even cancellation during initial verification can leave a new
                # authorization. Preserve its only copy, outside normal temp GC.
                try:
                    recovery = self.store.root / 'recovery'
                    recovery.mkdir(exist_ok=True, mode=0o700)
                    work.rename(recovery / ident)
                except OSError:
                    pass  # Leave the work folder intact if moving also fails.
            else:
                shutil.rmtree(work, ignore_errors=True)
            if combined and current['state'] in {'failed', 'blocked'}:
                await self.report(job, current['stage'])
            if combined and current['result'] and current['state'] not in {'done', 'cancelled'}:
                await self.deliver(current)

    def cancel(self, owner, ident=None):
        for job in self.store.rows(owner):
            if (ident is None or ident == job['id']) and job['state'] in {'running', 'queued', 'draft'}:
                self.store.update(job['id'], cancelled=1)
                task = self.tasks.get(job['id'])
                if task:
                    def finish_cancelled(_task, ident=job['id']):
                        current = self.store.get(ident)
                        if current and current['state'] == 'running' and current['cancelled']:
                            self.store.update(ident, state='cancelled', stage='Отменена до запуска обработки')
                    task.add_done_callback(finish_cancelled)
                    task.cancel()
                else:
                    self.store.update(job['id'], state='cancelled', stage='Отменена')

    def expire(self):
        cutoff = time.time() - self.retention
        for row in self.store.db.execute("SELECT * FROM jobs WHERE created<? AND state NOT IN ('running','queued','expired')", (cutoff,)).fetchall():
            if row['mode'] == 'migrate_clean' and row['result']:
                shutil.rmtree(Path(row['source']).parent, ignore_errors=True)
                if row['config'] != '{}':
                    self.store.db.execute("UPDATE jobs SET config='{}' WHERE id=?", (row['id'],))
                continue
            if row['result']:
                Path(row['result']).unlink(missing_ok=True)
            shutil.rmtree(Path(row['source']).parent, ignore_errors=True)
            self.store.db.execute('UPDATE jobs SET config=\'{}\',result=NULL,state=\'expired\',stage=\'Срок хранения истёк\' WHERE id=?', (row['id'],))

    async def loop(self):
        while not self.stopping:
            self.tasks = {key: task for key, task in self.tasks.items() if not task.done()}
            while len(self.tasks) < self.concurrency and (job := self.store.claim()):
                self.tasks[job['id']] = asyncio.create_task(self.run_job(job))
            self.expire()
            await asyncio.sleep(1)

    async def close(self):
        self.stopping = True
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def session_fingerprint(path):
    import sqlite3
    with sqlite3.connect(f'file:{quote(str(path))}?mode=ro', uri=True) as db:
        key = db.execute('SELECT auth_key FROM sessions').fetchone()[0]
    return hashlib.sha256(key).hexdigest()
