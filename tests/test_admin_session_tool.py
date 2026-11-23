"""Private admin flow, with synthetic files and no Telegram/real DB calls."""
import asyncio
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

from test_payments import config, db  # Isolated settings; never load the real .env.
from aiogram.types import CallbackQuery, Message
from handlers.admin import session_tool as ui
from services import admin_session_runtime as runtime
from services.admin_session_workbench import engine as worker
from services.admin_session_workbench.pr1_input import normalize_phone, normalize_code
from utils.partner_context import CURRENT


class AdminSessionToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bot = NS(id=123456, token='123456:synthetic-root-token', send_message=AsyncMock(),
                      send_document=AsyncMock(), download=AsyncMock())
        self.active = runtime.Workbench(self.bot, self.root/'tool', 123, 'synthetic-hash')
        self.patches = [patch.object(config, 'ADMIN_IDS', [42, 99]),
                        patch.object(config, 'BOT_TOKEN', self.bot.token),
                        patch.object(runtime, 'current', return_value=self.active)]
        for p in self.patches:
            p.start()
        self.context = CURRENT.set(None)
        self.state = NS(get_state=AsyncMock(return_value=None), clear=AsyncMock(), set_state=AsyncMock())

    async def asyncTearDown(self):
        for _, future in self.active.engine.inputs.values():
            if not future.done():
                future.cancel()
        await self.active.close()
        CURRENT.reset(self.context)
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def message(self, owner=42, kind='private'):
        message = MagicMock(spec=Message)
        message.chat = NS(id=owner, type=kind)
        message.from_user = NS(id=owner)
        message.bot = self.bot
        message.answer = AsyncMock()
        message.delete = AsyncMock()
        return message

    def call(self, action, owner=42, kind='private'):
        call = MagicMock(spec=CallbackQuery)
        call.from_user = NS(id=owner)
        call.message = self.message(owner, kind)
        call.bot = self.bot
        call.answer = AsyncMock()
        call.data = ui.PREFIX+action
        return call

    def draft(self, owner=42):
        folder = self.active.root/'uploads'/str(owner)
        folder.mkdir(parents=True, exist_ok=True)
        source = folder/'account.session'
        source.write_bytes(b'synthetic source')
        return self.active.store.add(owner, str(owner), source, {}, 'migrate_clean', state='draft')

    async def test_admin_open_has_separate_controls_without_stock_mutation(self):
        call = self.call('open')
        with patch.object(db, '_get_pool', side_effect=AssertionError('no inventory DB access')):
            await ui.callback(call, self.state)
        text = call.message.answer.call_args.args[0]
        self.assertIn('Session PR #1', text)
        self.assertIn('не обновляет', text)
        self.assertIn('старой авторизации', text)
        self.assertEqual(self.active.store.rows(42), [])

    async def test_non_admin_group_and_partner_cannot_open_or_read_tasks(self):
        for call in (self.call('status', 777), self.call('archives', 42, 'group')):
            await ui.callback(call, self.state)
            call.message.answer.assert_not_awaited()
            self.assertTrue(call.answer.call_args.kwargs['show_alert'])
        token = CURRENT.set({'bot_id':7})
        try:
            call = self.call('archives')
            await ui.callback(call, self.state)
            call.message.answer.assert_not_awaited()
        finally:
            CURRENT.reset(token)
        call = self.call('archives')
        call.bot = NS(id=999)
        await ui.callback(call, self.state)
        call.message.answer.assert_not_awaited()

    async def test_atomic_draft_cannot_be_claimed_until_owner_confirms(self):
        ident = self.draft()
        self.assertIsNone(self.active.store.claim())
        foreign = self.call('confirm:'+ident, 99)
        await ui.callback(foreign, self.state)
        self.assertEqual(self.active.store.get(ident)['state'], 'draft')
        review = self.call('review:'+ident)
        await ui.callback(review, self.state)
        self.assertIn('30 дней', review.message.answer.call_args.args[0])
        self.assertIn('ТОЛЬКО', review.message.answer.call_args.args[0])
        await ui.callback(self.call('confirm:'+ident), self.state)
        self.assertEqual(self.active.store.claim()['id'], ident)

    async def test_resume_does_not_bypass_confirmation_and_cancel_is_owner_scoped(self):
        mine, other = self.draft(), self.draft(99)
        await ui.callback(self.call('resume'), self.state)
        self.assertIsNone(self.active.store.claim())
        await ui.callback(self.call('cancel:'+other), self.state)
        self.assertEqual(self.active.store.get(other)['state'], 'draft')
        await ui.callback(self.call('cancel:'+mine), self.state)
        self.assertEqual(self.active.store.get(mine)['state'], 'cancelled')

    async def test_archives_only_deliver_requesting_admin_results(self):
        mine, other = self.draft(), self.draft(99)
        for ident in (mine, other):
            result = self.active.root/(ident+'.zip')
            result.write_bytes(b'synthetic archive')
            self.active.store.update(ident, state='done', result=str(result))
        with patch.object(self.active.engine, 'deliver', new=AsyncMock()) as deliver:
            await ui.callback(self.call('archives'), self.state)
        self.assertEqual([c.args[0]['owner'] for c in deliver.await_args_list], [42])

    async def test_input_is_per_job_per_owner_and_uses_pr1_code_normalization(self):
        loop = asyncio.get_running_loop()
        mine, other = loop.create_future(), loop.create_future()
        self.active.engine.inputs[(42, 'own')] = ('code', mine)
        self.active.engine.inputs[(99, 'other')] = ('password', other)
        message = self.message()
        message.text = '/session_tool_input other secret-password'
        await ui.manual_input(message)
        self.assertFalse(other.done())
        message.text = '/session_tool_input own 12-3 45'
        await ui.manual_input(message)
        self.assertEqual(mine.result(), '12345')
        self.assertNotIn('12345', str(message.answer.call_args))
        self.assertNotIn('secret-password', str(message.answer.call_args_list))
        self.assertEqual(message.delete.await_count, 2)

    async def test_secret_input_is_deleted_when_no_job_is_waiting(self):
        message = self.message()
        message.text = '/session_tool_input unknown private-secret'
        await ui.manual_input(message)
        message.delete.assert_awaited_once()
        self.assertNotIn('private-secret', str(message.answer.call_args))

    async def test_upload_valid_session_creates_only_draft_and_cleans_staging(self):
        fixture = self.root/'fixture.session'
        with sqlite3.connect(fixture) as connection:
            connection.execute('CREATE TABLE sessions(dc_id,server_address,port,auth_key)')
            connection.execute('INSERT INTO sessions VALUES(2,\'fixture.invalid\',443,?)', (b'x'*256,))
        async def download(document, destination):
            shutil.copyfile(fixture, destination)
        self.bot.download.side_effect = download
        message = self.message()
        message.document = NS(file_name='fixture.session', file_size=fixture.stat().st_size)
        with patch.object(db, '_get_pool', side_effect=AssertionError('no inventory DB access')):
            await ui.upload(message, self.state)
        jobs = self.active.store.rows(42)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]['mode'], 'migrate_clean')
        self.assertEqual(jobs[0]['state'], 'draft')
        self.assertIsNone(self.active.store.claim())
        self.assertFalse(list((self.active.root/'staging').rglob('*.session')))
        self.assertIn('Подтверждаю', str(message.answer.call_args.kwargs['reply_markup']))
        self.assertTrue(Path(jobs[0]['source']).exists())

    async def test_zip_traversal_is_rejected_without_job_or_external_file(self):
        fixture = self.root/'fixture.zip'
        with zipfile.ZipFile(fixture,'w') as archive:
            archive.writestr('../outside.session', b'fixture')
        async def download(document, destination):
            shutil.copyfile(fixture, destination)
        self.bot.download.side_effect = download
        message = self.message()
        message.document = NS(file_name='fixture.zip', file_size=fixture.stat().st_size)
        await ui.upload(message, self.state)
        self.assertEqual(self.active.store.rows(42), [])
        self.assertFalse((self.active.root/'outside.session').exists())

    async def test_existing_shop_dialog_is_not_silently_discarded(self):
        self.state.get_state.return_value = 'AddAccountState:waiting_for_code'
        call = self.call('open')
        await ui.callback(call, self.state)
        self.state.clear.assert_not_awaited()
        self.assertIn('/cancel', call.message.answer.call_args.args[0])

    async def test_permission_revoked_before_claim_does_not_connect_client(self):
        ident = self.draft(777)
        self.active.store.update(ident, state='queued')
        with patch.object(worker, 'make_client') as connect:
            await self.active.engine.run_job(self.active.store.claim())
        connect.assert_not_called()
        self.assertEqual(self.active.store.get(ident)['state'], 'cancelled')

    async def test_plain_transport_ignores_root_bot_html_mode(self):
        transport = runtime.PlainTransport(self.bot)
        await transport.send_message(42, '<private>')
        self.assertIsNone(self.bot.send_message.call_args.kwargs['parse_mode'])


class RuntimeAndSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_source_pr1_validation_has_expected_inputs(self):
        self.assertEqual(normalize_phone('00 1 (555) 111-2222'), '+15551112222')
        self.assertEqual(normalize_phone('8 999 111-22-33'), '+79991112233')
        self.assertEqual(normalize_code('12 3-45'), '12345')
        self.assertIsNone(normalize_code('private'))
        self.assertIsNone(normalize_phone('invalid'))

    def test_admin_menu_has_separate_entry_and_existing_actions(self):
        from keyboards.admin_kb import get_admin_panel
        callbacks = {button.callback_data for row in get_admin_panel('inventory').inline_keyboard for button in row}
        self.assertIn('session_tool:open', callbacks)
        self.assertTrue({'add_account_session','add_account_telethon','admin_accounts_list'} <= callbacks)

    def test_railway_requires_directory_inside_volume(self):
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_ID':'fixture'}, clear=True):
            with self.assertRaises(ValueError):
                runtime.data_directory()
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_ID':'fixture', 'RAILWAY_VOLUME_MOUNT_PATH':'/data',
                                   'ADMIN_SESSION_DATA_DIR':'/outside'}, clear=True):
            with self.assertRaises(ValueError):
                runtime.data_directory()
        with patch.dict(os.environ, {'RAILWAY_ENVIRONMENT_ID':'fixture', 'RAILWAY_VOLUME_MOUNT_PATH':'/data'}, clear=True):
            self.assertEqual(runtime.data_directory(), Path('/data/admin-sessions'))

    async def test_lifecycle_starts_one_worker_without_polling_or_new_bot(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'ADMIN_SESSION_DATA_DIR':directory}, clear=True), \
             patch.object(config,'TELEGRAM_API_ID',123), patch.object(config,'TELEGRAM_API_HASH','synthetic-hash'):
            root = NS(id=123456, send_message=AsyncMock(), send_document=AsyncMock())
            try:
                started = await runtime.start(root)
                self.assertIsNotNone(started)
                self.assertEqual(started.bot_id, root.id)
                self.assertFalse(started.task.done())
            finally:
                await runtime.stop()
            self.assertIsNone(runtime._runtime)

    async def test_missing_optional_tool_config_does_not_raise_into_shop(self):
        with patch.object(config,'TELEGRAM_API_ID',0):
            self.assertIsNone(await runtime.start(NS(id=123456)))
        with self.assertRaises(RuntimeError):
            runtime.current()


if __name__ == '__main__':
    unittest.main()


class WorkbenchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_keeps_unindexed_new_session_and_never_replays_interrupted_task(self):
        from services.admin_session_workbench.storage import Store
        from services.admin_session_workbench.checkpoints import persist_new_session
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root)
            source = root/'source.session'
            source.write_bytes(b'synthetic new session')
            ident = store.add(42,'fixture',source,{},'migrate_clean')
            store.claim()
            saved = persist_new_session(root,42,ident,'before_cleanup',source,{})
            store.db.close()
            recovered = Store(root)
            try:
                self.assertEqual(recovered.get(ident)['state'],'interrupted')
                self.assertEqual(recovered.get(ident)['result'],str(saved.archive))
                self.assertIsNone(recovered.claim())
                self.assertTrue(saved.session.exists())
                self.assertIsNone(recovered.get(ident,99))
            finally:
                recovered.db.close()

    async def test_limited_admin_engine_cannot_run_other_modes(self):
        with tempfile.TemporaryDirectory() as directory:
            active = runtime.Workbench(NS(id=123456),directory,123,'synthetic-hash')
            ident = active.store.add(42,'fixture','/unused',{},'terminate')
            try:
                with patch.object(config,'ADMIN_IDS',[42]),patch.object(worker,'make_client') as create:
                    await active.engine.run_job(active.store.claim())
                create.assert_not_called()
                self.assertEqual(active.store.get(ident)['state'],'cancelled')
            finally:
                await active.close()

    def test_bot_lifecycle_registers_tool_before_admin_and_stops_worker(self):
        import ast
        source = (Path(__file__).resolve().parents[1]/'bot.py').read_text()
        tree = ast.parse(source)
        main = next(node for node in tree.body if isinstance(node,ast.AsyncFunctionDef) and node.name=='main')
        calls = [node for node in ast.walk(main) if isinstance(node,ast.Call)]
        include = next(node for node in calls if isinstance(node.func,ast.Attribute) and node.func.attr=='include_routers')
        names = [node.id for node in include.args if isinstance(node,ast.Name)]
        self.assertLess(names.index('session_tool_router'),names.index('admin_router'))
        self.assertIn('await admin_session_runtime.start(bot)',source)
        self.assertIn('await admin_session_runtime.stop()',source)


class EarlyCancellationAndPathTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_before_task_entry_releases_persistent_account_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            active = runtime.Workbench(NS(id=123456),directory,123,'synthetic-hash')
            ident = active.store.add(42,'fixture','/unused',{},'migrate_clean')
            task = asyncio.create_task(active.engine.run_job(active.store.claim()))
            active.engine.tasks[ident] = task
            try:
                with patch.object(config,'ADMIN_IDS',[42]),patch.object(worker,'make_client') as connect:
                    active.engine.cancel(42,ident)
                    await asyncio.gather(task,return_exceptions=True)
                    await asyncio.sleep(0)
                connect.assert_not_called()
                self.assertEqual(active.store.get(ident)['state'],'cancelled')
                self.assertFalse(active.store.db.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone())
            finally:
                await active.close()

    def test_zip_sqlite_filename_cannot_become_uri_query(self):
        from services.admin_session_workbench.files import ingest
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root/'source.session'
            with sqlite3.connect(source) as connection:
                connection.execute('CREATE TABLE sessions(dc_id,server_address,port,auth_key)')
                connection.execute('INSERT INTO sessions VALUES(2,\'fixture.invalid\',443,?)',(b'x'*256,))
            archive = root/'input.zip'
            with zipfile.ZipFile(archive,'w') as bundle:
                bundle.write(source,'a?b.session')
                bundle.writestr('a?b.json','{}')
            results = ingest(archive,root/'unpacked',100000)
            self.assertEqual(len(results),1)
            self.assertFalse((root/'unpacked'/'a').exists())


class UploadMessageTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = AdminSessionToolTests.asyncSetUp
    asyncTearDown = AdminSessionToolTests.asyncTearDown
    message = AdminSessionToolTests.message

    async def test_missing_zip_json_is_reported_as_actionable_format_error(self):
        fixture = self.root/'fixture.session'
        with sqlite3.connect(fixture) as connection:
            connection.execute('CREATE TABLE sessions(dc_id,server_address,port,auth_key)')
            connection.execute('INSERT INTO sessions VALUES(2,\'fixture.invalid\',443,?)',(b'x'*256,))
        archive = self.root/'input.zip'
        with zipfile.ZipFile(archive,'w') as bundle:
            bundle.write(fixture,'fixture.session')
        async def download(document,destination):
            shutil.copyfile(archive,destination)
        self.bot.download.side_effect = download
        message = self.message()
        message.document = NS(file_name='fixture.zip',file_size=archive.stat().st_size)
        await ui.upload(message,self.state)
        self.assertIn('Нет парного JSON',message.answer.call_args.args[0])
        self.assertEqual(self.active.store.rows(42),[])

    async def test_unknown_value_error_message_is_not_echoed(self):
        message = self.message()
        message.document = NS(file_name='fixture.session',file_size=10)
        with patch.object(ui,'ingest',side_effect=ValueError('private-password-hash')):
            await ui.upload(message,self.state)
        self.assertNotIn('private-password-hash',str(message.answer.call_args))
        self.assertIn('ValueError',message.answer.call_args.args[0])
