"""Queue official SpamBot checks without keeping Telegram sessions in FSM state."""
from utils.i18n import tr
from html import escape

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from config import ADMIN_IDS
from database import db, spam_checks
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_message_safe
from utils.validation import positive_id

spam_router = Router()
spam_router.callback_query.filter(F.message.chat.type == 'private')


def button(text, callback, role):
    return [InlineKeyboardButton(text=text, callback_data=callback, icon_custom_emoji_id=icon_for(role))]


@spam_router.callback_query(F.data.in_({'spam_all', 'spam_all_yes'}))
async def all_accounts(call):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Доступ только администратору.'), show_alert=True)
        return
    if call.data == 'spam_all':
        await edit_message_safe(call, tr('<b>Проверить весь остаток?</b>\n\nВ очередь попадут только аккаунты в продаже. Бот отправит /start официальному @SpamBot с каждого аккаунта. Проверка идёт по одному аккаунту; товары в действующем резерве будут проверены после его окончания. Проверявшиеся менее 5 минут назад и аккаунты с ограничением частоты запросов пропускаются.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Поставить в очередь'), 'spam_all_yes', 'confirm'), button(tr('Отмена'), 'admin_home', 'cancel')]))
    else:
        count = await spam_checks.enqueue(call.from_user.id)
        await edit_message_safe(call, tr('Поставлено в очередь: {0}.\nРезультат и время появятся в карточках аккаунтов. Проверка запускается только по кнопке. После загрузки аккаунт остаётся без подтверждённого результата.', f'{count}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('В админ-панель'), 'admin_home', 'back')]))
    await answer_safe(call)


@spam_router.callback_query(F.data.startswith('spam_check:') | F.data.startswith('spam_show:'))
async def one_account(call):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, tr('Доступ только администратору.'), show_alert=True)
        return
    try:
        account_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный товар.'), show_alert=True)
        return
    row = await db.get_account(account_id)
    if not row:
        await answer_safe(call, tr('Товар не найден.'), show_alert=True)
        return
    note = ''
    if call.data.startswith('spam_check:'):
        count = await spam_checks.enqueue(call.from_user.id, account_id)
        note = tr('\n\nПроверка добавлена в очередь.') if count else tr('\n\nПроверка уже идёт, повтор пока недоступен или товар уже продан.')
    await edit_message_safe(call, tr('<b>Спамблок · #{0}</b>\n\n{1}', f'{account_id:02d}', f'{escape(spam_checks.description(row))}') + note + tr('\n\nИсточник: официальный @SpamBot. Результат актуален на момент проверки; состояние может измениться.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Обновить результат'), f'spam_show:{account_id}', 'refresh'), button(tr('Проверить снова'), f'spam_check:{account_id}', 'warranty'), button(tr('К аккаунту'), f'admin_account_detail:{account_id}', 'back')]))
    await answer_safe(call)


# Explicit administrator-only maintenance; exports are sent only to its private chat.
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
import asyncio
import io
import json
import zipfile

_audit_running = False


@spam_router.message(Command('audit_sessions'), F.chat.type == 'private')
async def audit_sessions(message):
    global _audit_running
    if message.from_user.id not in ADMIN_IDS:
        return
    if _audit_running:
        await message.answer('Проверка уже выполняется.')
        return
    _audit_running = True
    from database.admin_web import rows
    from database.admin_tools import _transaction
    from services.session_audit import clean_other_sessions, session_file_bytes
    from uuid import uuid4
    from database.session_audit import PENDING, hide_failed, delete_delivered
    try:
        await message.answer('Проверяю непроданные аккаунты. Завершаю остальные сеансы, сохраняя сеанс магазина. Проблемные аккаунты будут скрыты из продажи, отправлены в ZIP и затем удалены из магазина.')
        # Process bounded batches; never load all private sessions into memory at once.
        last = 0
        while True:
            batch = await rows("SELECT id FROM accounts WHERE (status='available' OR (status='review' AND review_reason=%s)) AND id>%s ORDER BY id LIMIT 50", (PENDING,last,))
            if not batch:
                break
            report=[]; output=io.BytesIO(); failures=0; pending_exports=[]
            with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
                for item in batch:
                    identity=item['id'];last=identity;token=uuid4().hex
                    async with _transaction() as cur:
                        await cur.execute("SELECT id,data,number,telegram_user_id,registration_date,status FROM accounts WHERE id=%s AND (status='available' OR (status='review' AND review_reason=%s)) AND spam_requested=0 AND (spam_lease_until IS NULL OR spam_lease_until<=UTC_TIMESTAMP()) FOR UPDATE",(identity,PENDING))
                        account=await cur.fetchone()
                        if account:
                            await cur.execute('SELECT user_id FROM account_reservations WHERE account_id=%s AND expires_at>UTC_TIMESTAMP() FOR UPDATE',(identity,))
                            if await cur.fetchone(): account=None
                        if account:
                            await cur.execute('UPDATE accounts SET spam_token=%s,spam_lease_until=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 MINUTE) WHERE id=%s',(token,identity))
                    if not account:
                        report.append({'id':identity,'status':'skipped_busy'});continue
                    try:
                        result=({'status':'failed','reason':'export_pending'} if account['status']=='review' else await clean_other_sessions(account['data'],account['telegram_user_id']))
                        report.append({'id':identity,'registration_date':str(account['registration_date']) if account.get('registration_date') else None,'registration_date_source':'store_metadata' if account.get('registration_date') else 'unknown',**result})
                        if result['status']=='failed':
                            failures+=1
                            hidden=await hide_failed(message.from_user.id,account,token)
                            if hidden:
                                pending_exports.append(account)
                            report[-1]['hidden_from_sale']=hidden
                            try:
                                archive.writestr(f'account-{identity}.session',session_file_bytes(account['data']))
                            except Exception:
                                # Invalid SQLite export still leaves the original StringSession in JSON.
                                pass
                            # Exact registration date is not exposed by Telegram. Preserve only known metadata.
                            archive.writestr(f'account-{identity}.json',json.dumps({'id':identity,'phone':account['number'],'string_session':account['data'],'registration_date':str(account['registration_date']) if account.get('registration_date') else None,'registration_date_source':'store_metadata' if account.get('registration_date') else 'unknown',**result},ensure_ascii=False))
                    finally:
                        async with _transaction() as cur:
                            await cur.execute('UPDATE accounts SET spam_token=NULL,spam_lease_until=NULL WHERE id=%s AND spam_token=%s',(identity,token))
                archive.writestr('report.json',json.dumps(report,ensure_ascii=False,indent=2))
            await message.answer_document(BufferedInputFile(output.getvalue(),filename=f'session-audit-{last}.zip'),caption=f'Проверка до товара #{last}. Не удалось завершить проверку/лишние сеансы: {failures}. Сессии магазина сохранены.')
            deleted=0
            for account in pending_exports:
                try:
                    deleted += bool(await delete_delivered(message.from_user.id,account))
                except Exception:
                    # Keep hidden stock and its session for a later export/retry.
                    pass
            if pending_exports:
                await message.answer(f'Файл отправлен. Удалено товаров: {deleted}. Осталось скрыто для повторного удаления: {len(pending_exports)-deleted}.')
        await message.answer('Проверка завершена. Пропущенные занятые товары можно проверить повторным запуском /audit_sessions.')
    finally:
        _audit_running = False
