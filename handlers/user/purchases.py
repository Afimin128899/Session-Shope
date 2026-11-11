"""Owner-scoped order pages and explicit confirmation before session removal."""
from utils.i18n import tr
from html import escape
import json

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import bot_store
from database import spam_checks
from database.db import get_category, get_purchase_for_user
from database.quality import warranty
from keyboards.pagination import pagination
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_message_safe
from utils.order_status import order_status
from utils.validation import page_index, positive_id

purchases_router = Router()


def button(text, callback, role=None):
    return [InlineKeyboardButton(text=text, callback_data=callback, icon_custom_emoji_id=icon_for(role))]


@purchases_router.callback_query(F.data == 'my_purchases')
@purchases_router.callback_query(F.data.startswith('orders_page:'))
async def my_purchases(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        page = page_index(call.data.split(':')[1]) if ':' in call.data else 0
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    orders, total, page = await bot_store.orders(call.from_user.id, page)
    lines, rows = ([], [])
    for order in orders:
        label = str(order.get('name') or order['country'] or tr('Аккаунт'))[:40]
        lines.append(f"<b>#{order['id']} · {escape(label)}</b>\n{escape(order_status(order))} · {escape(str(order['date'])[:32])}")
        rows.append(button(f"#{order['id']} · {label}", f"open_purchase:{order['id']}", 'orders'))
    rows += pagination(page, total, bot_store.PAGE_SIZE, 'orders_page')
    rows.append(button(tr('Мой профиль'), 'my_profile', 'back'))
    text = tr('<b>Мои покупки</b>\n\n') + ('\n\n'.join(lines) if lines else tr('Покупок пока нет. Выберите аккаунт в каталоге.'))
    if not orders:
        rows.insert(0, button(tr('Открыть каталог'), 'buy', 'catalog'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def render_order(call, purchase_id):
    order = await get_purchase_for_user(purchase_id, call.from_user.id)
    if not order:
        await answer_safe(call, tr('Покупка не найдена.'), show_alert=True)
        return
    rows = [button(tr('Есть проблема'), f'purchase_help:{purchase_id}', 'support')]
    if order['status'] == 'refunded':
        from database.refunds import get_refund
        refund = await get_refund(purchase_id, call.from_user.id)
        details = tr('Возвращено: {0} {1}\nПричина: {2}', f"{refund['amount']}", f"{escape(refund['currency'])}", f"{escape(refund['reason'])}") if refund else tr('Средства возвращены на баланс бота.')
        text = tr('<b>Заказ #{0} возвращён</b>\n\n{1}', f'{purchase_id}', f'{details}')
    else:
        cat = await get_category(order['country'])
        name = cat['name'] if cat else order['country']
        assurance = warranty(order)
        paid = tr('Сумма не сохранена') if order['paid_amount'] is None else f"{order['paid_amount']} {escape(order.get('currency') or '')}"
        try:
            snapshot = json.loads(order.get('attributes_snapshot') or '{}')
        except (ValueError, TypeError):
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        text = tr('<b>Детали покупки #{0}</b>\n\nКатегория: <b>{1}</b>\nСтатус: <b>{2}</b>\nТовар: <code>#{3}</code>\nTelegram ID: <code>{4}</code>\nНомер: <code>{5}</code>\nПароль 2FA: <code>{6}</code>\nОплачено: {7}\nДата: {8}\nСпамблок при покупке: {9}\nГарантия: <b>{10}</b>', f'{purchase_id}', f'{escape(name)}', f'{escape(order_status(order))}', f"{order['account_id']:02d}", f"{order.get('telegram_user_id') or tr('Не сохранён')}", f"{escape(order['number'])}", f"{escape(order.get('password') or tr('Не установлен'))}", f'{paid}', f"{escape(str(order['date']))}", f'{escape(spam_checks.description(snapshot))}', f"{escape(assurance['label'])}")
        if assurance['active']:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            until = datetime.fromisoformat(assurance['until']).astimezone(ZoneInfo('Europe/Moscow'))
            text += tr('\nДо {0} МСК.\n{1}', f'{until:%d.%m.%Y %H:%M}', f"{escape(assurance['policy'])}")
            rows.insert(0, button(tr('Обратиться по гарантии'), f'quality_warranty:{purchase_id}', 'warranty'))
        if order['status'] == 'completed' or order.get('data') == bot_store.DELETED_SESSION:
            text += tr('\n\nДанные сессии удалены из рабочей базы. Получить код через магазин больше нельзя.')
        else:
            text += tr('\n\nВведите номер в Telegram, затем нажмите «Получить код». После входа смените пароль и привяжите свою почту.')
            rows += [button(tr('Получить код'), f'get_code:{purchase_id}', 'code'), button(tr('Завершить покупку'), f'complete_purchase:{purchase_id}', 'confirm')]
    rows.append(button(tr('Мои покупки'), 'my_purchases', 'back'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@purchases_router.callback_query(F.data.startswith('open_purchase:'))
async def open_purchase(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный заказ.'), show_alert=True)
        return
    await render_order(call, purchase_id)


@purchases_router.callback_query(F.data.startswith('complete_purchase:'))
async def complete_purchase(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, tr('Некорректный заказ.'), show_alert=True)
        return
    order = await get_purchase_for_user(purchase_id, call.from_user.id)
    if not order or order['status'] != 'issued':
        await answer_safe(call, tr('Заказ уже завершён или недоступен.'), show_alert=True)
        return
    await edit_message_safe(call, tr('<b>Завершить покупку #{0}?</b>\n\nПродолжайте, только если уже вошли в аккаунт. Сессия будет удалена из рабочей базы, и получить код через магазин больше не получится. Данные могут оставаться в резервных копиях до окончания срока их хранения.', f'{purchase_id}'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Я вошёл, удалить сессию'), f'complete_confirm:{purchase_id}', 'confirm'), button(tr('Отмена'), f'open_purchase:{purchase_id}', 'cancel')]))
    await answer_safe(call)


@purchases_router.callback_query(F.data.startswith('complete_confirm:'))
async def confirm_completion(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
        await bot_store.complete_order(call.from_user.id, purchase_id)
    except (ValueError, IndexError) as exc:
        await answer_safe(call, str(exc) or tr('Некорректный заказ.'), show_alert=True)
        return
    await render_order(call, purchase_id)
