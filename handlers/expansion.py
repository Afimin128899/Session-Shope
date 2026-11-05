"""Admin workflows with reviewable confirmation and buyer help."""
from utils.notification_language import send_translated
from utils.i18n import tr
from html import escape
from decimal import Decimal
from aiogram import Router,F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from config import ADMIN_IDS
from database import expansion
from database.admin_tools import _transaction,_record
from utils.nav import edit_message_safe

router=Router()
router.message.filter(F.chat.type=='private')
router.callback_query.filter(F.message.chat.type=='private')


@router.message(Command('shop_tools'))
async def help_admin(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(tr('Управление магазином:\n<code>/bulk_edit 12,13 price 100</code>\nПоля: price, warranty_hours, features_note. Только свободные товары, до 100 ID.\n<code>/replace 123 456 Причина замены</code>\nЗаказ, ID нового аккаунта той же категории, причина.\n<code>/shop_rules 500 15 600 3</code>\nМинимальная сумма ₽, % опта, порог согласования возврата ₽ (0 = выключено), низкий остаток. Изменения требуют подтверждения.'))


@router.message(Command('bulk_edit','replace','shop_rules','support_schedule'))
async def prepare(message, state):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        command, rest = message.text.split(maxsplit=1)
        action = command.split('@')[0][1:]
        if action == 'bulk_edit':
            raw, field, value = rest.split(maxsplit=2)
            data = {'ids': [int(i) for i in raw.split(',')], 'field': field, 'value': value}
            if len(data['ids']) > 100:
                raise ValueError
        elif action == 'replace':
            order, account, reason = rest.split(maxsplit=2)
            data = {'purchase': int(order), 'new_account': int(account), 'reason': reason}
        elif action == 'support_schedule':
            hours, eta = rest.split('|', 1)
            if not 1 <= len(hours.strip()) <= 200 or not 1 <= len(eta.strip()) <= 200:
                raise ValueError
            data = {'hours': hours.strip(), 'eta': eta.strip()}
        else:
            quantity, pct, threshold, low = rest.split()
            quantity = int(quantity)
            pct = Decimal(pct)
            threshold = Decimal(threshold)
            low = int(low)
            if not pct.is_finite() or not threshold.is_finite() or (not 1 <= quantity <= 10000) or (not 0 <= pct <= 50) or (pct != pct.quantize(Decimal('.01'))) or (threshold != threshold.quantize(Decimal('.01'))) or (not 0 <= threshold <= 10000) or (not 0 <= low <= 10000):
                raise ValueError
            data = {'quantity': quantity, 'pct': str(pct), 'threshold': str(threshold), 'low': low}
        import secrets
        token = secrets.token_hex(8)
        await state.update_data(expansion_action=action, expansion_data=data, expansion_token=token)
        await message.answer(tr('Подтвердите операцию:\n<code>') + escape(rest) + tr('</code>\nДля замены прежний аккаунт будет снят с продажи, доступ к нему закрыт. Деньги повторно не списываются.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Подтвердить'), callback_data='expand_confirm:' + token)]]))
    except (ValueError, ArithmeticError):
        await message.answer(tr('Проверьте формат. Инструкция: /shop_tools'))


@router.callback_query(F.data.startswith('expand_confirm:'))
async def confirm(call, state):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(tr('Нет доступа'))
        return
    saved = await state.get_data()
    if saved.get('expansion_token') != call.data.split(':')[1]:
        await call.answer(tr('Подтверждение устарело'))
        return
    data = saved['expansion_data']
    action = saved['expansion_action']
    try:
        if action == 'bulk_edit':
            await expansion.bulk_edit(call.from_user.id, **data)
        elif action == 'replace':
            user = await expansion.replace(call.from_user.id, **data)
            try:
                await send_translated(call.bot, user, 'По заказу #{0} выдана гарантийная замена. Новые данные — в деталях этого заказа.', f"{data['purchase']}")
            except Exception:
                pass
        elif action == 'support_schedule':
            async with _transaction() as cur:
                for key, value in [('support_hours', data['hours']), ('support_eta', data['eta'])]:
                    await cur.execute('INSERT INTO settings(`key`,`value`) VALUES(%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)', (key, value))
                await _record(cur, call.from_user.id, 'support_schedule', 'settings', 'support', data)
        else:
            async with _transaction() as cur:
                for key, value in [('wholesale_min_total', data['quantity']), ('wholesale_pct', data['pct']), ('refund_approval_threshold', data['threshold']), ('low_stock_limit', data['low'])]:
                    await cur.execute('INSERT INTO settings(`key`,`value`) VALUES(%s,%s) ON DUPLICATE KEY UPDATE `value`=VALUES(`value`)', (key, str(value)))
                await _record(cur, call.from_user.id, 'shop_rules', 'settings', 'commerce', data)
        await state.clear()
        await call.message.edit_reply_markup(reply_markup=None)
        await call.message.answer(tr('✅ Выполнено. Операция сохранена в журнале.'))
        await call.answer()
    except (ValueError, ArithmeticError) as exc:
        await call.answer(str(exc)[:180], show_alert=True)


@router.callback_query(F.data.startswith('refund_approve:'))
async def approve(call):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(tr('Нет доступа'))
        return
    try:
        result = await expansion.approve_refund(call.from_user.id, int(call.data.split(':')[1]))
        await call.answer(tr('Возврат выполнен') if result else tr('Уже возвращён'), show_alert=True)
        if result:
            try:
                await send_translated(call.bot, result['user_id'], 'Возврат #{0}: {1} {2} на баланс.', f"{result['id']}", f"{result['amount']}", f"{result['currency']}")
            except Exception:
                pass
    except ValueError as exc:
        await call.answer(str(exc), show_alert=True)
    except Exception:
        await call.answer(tr('Не удалось завершить возврат. Повторите эту кнопку позже.'), show_alert=True)


@router.callback_query(F.data=='expand_tools')
async def tools_menu(call):
    if call.from_user.id not in ADMIN_IDS:
        await call.answer(tr('Нет доступа'))
        return
    await edit_message_safe(call, tr('Инструменты магазина: /shop_tools\nГрафик и ориентир ответа:\n<code>/support_schedule Ежедневно 10–22 МСК | Обычно до 24 часов</code>\nПубликуйте только действительный график. Нужен второй администратор в ADMIN_IDS для крупных возвратов.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('В админ-панель'), callback_data='admin_home')]]))
    await call.answer()


@router.message(Command('refund_queue'))
async def refund_queue(message):
    if message.from_user.id not in ADMIN_IDS:
        return
    from database.db import _get_pool
    import aiomysql
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT r.* FROM refund_approvals r JOIN purchases p ON p.id=r.purchase_id WHERE p.status<>'refunded' ORDER BY r.created_at LIMIT 20")
            rows = await cur.fetchall()
    if not rows:
        await message.answer(tr('Ожидающих согласований нет.'))
        return
    for row in rows:
        await message.answer(tr('Возврат #{0}: {1} {2}\nИнициатор: {3}\nПричина: {4}\nПри возврате отменяется записанный реферальный бонус.', f"{row['purchase_id']}", f"{row['amount']}", f"{escape(row['currency'])}", f"{row['requester']}", f"{escape(row['reason'])}"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Согласовать возврат'), callback_data=f"refund_approve:{row['purchase_id']}")]]))
