"""Owner-scoped order pages and explicit confirmation before session removal."""
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database import bot_store
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
    lines, rows = [], []
    for order in orders:
        label = str(order.get('name') or order['country'] or 'Аккаунт')[:40]
        lines.append(f"<b>#{order['id']} · {escape(label)}</b>\n{escape(order_status(order))} · {escape(str(order['date'])[:32])}")
        rows.append(button(f"#{order['id']} · {label}", f"open_purchase:{order['id']}", 'orders'))
    rows += pagination(page, total, bot_store.PAGE_SIZE, 'orders_page')
    rows.append(button('В главное меню', 'back_main', 'back'))
    text = '<b>Мои покупки</b>\n\n' + ('\n\n'.join(lines) if lines else 'Покупок пока нет. Выберите аккаунт в каталоге.')
    if not orders:
        rows.insert(0, button('Открыть каталог', 'buy', 'catalog'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def render_order(call, purchase_id):
    order = await get_purchase_for_user(purchase_id, call.from_user.id)
    if not order:
        await answer_safe(call, 'Покупка не найдена.', show_alert=True)
        return
    rows = [button('Есть проблема', f'purchase_help:{purchase_id}', 'support'),
            button('Оставить / изменить отзыв', f'quality_review:{purchase_id}', 'reviews')]
    if order['status'] == 'refunded':
        from database.refunds import get_refund
        refund = await get_refund(purchase_id, call.from_user.id)
        details = (f"Возвращено: {refund['amount']} {escape(refund['currency'])}\nПричина: {escape(refund['reason'])}"
                   if refund else 'Средства возвращены на баланс бота.')
        text = f'<b>Заказ #{purchase_id} возвращён</b>\n\n{details}'
    else:
        cat = await get_category(order['country'])
        name = cat['name'] if cat else order['country']
        assurance = warranty(order)
        paid = 'Сумма не сохранена' if order['paid_amount'] is None else f"{order['paid_amount']} {escape(order.get('currency') or '')}"
        text = (
            f'<b>Детали покупки #{purchase_id}</b>\n\n'
            f"Категория: <b>{escape(name)}</b>\nСтатус: <b>{escape(order_status(order))}</b>\n"
            f"Товар: <code>SBA-{order['account_id']:06d}</code>\n"
            f"Telegram ID: <code>{order.get('telegram_user_id') or 'Не сохранён'}</code>\n"
            f"Номер: <code>{escape(order['number'])}</code>\n"
            f"Пароль 2FA: <code>{escape(order.get('password') or 'Не установлен')}</code>\n"
            f"Оплачено: {paid}\nДата: {escape(str(order['date']))}\n"
            f"Гарантия: <b>{escape(assurance['label'])}</b>"
        )
        if assurance['active']:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            until = datetime.fromisoformat(assurance['until']).astimezone(ZoneInfo('Europe/Moscow'))
            text += f"\nДо {until:%d.%m.%Y %H:%M} МСК.\n{escape(assurance['policy'])}"
            rows.insert(0, button('Обратиться по гарантии', f'quality_warranty:{purchase_id}', 'warranty'))
        if order['status'] == 'completed' or order.get('data') == bot_store.DELETED_SESSION:
            text += '\n\nДанные сессии удалены из рабочей базы. Получить код через магазин больше нельзя.'
        else:
            text += '\n\nВведите номер в Telegram, затем нажмите «Получить код». После входа смените пароль и привяжите свою почту.'
            rows += [button('Получить код', f'get_code:{purchase_id}', 'code'),
                     button('Завершить покупку', f'complete_purchase:{purchase_id}', 'confirm')]
    rows.append(button('Мои покупки', 'my_purchases', 'back'))
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


@purchases_router.callback_query(F.data.startswith('open_purchase:'))
async def open_purchase(call: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, 'Некорректный заказ.', show_alert=True)
        return
    await render_order(call, purchase_id)


@purchases_router.callback_query(F.data.startswith('complete_purchase:'))
async def complete_purchase(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
    except (ValueError, IndexError):
        await answer_safe(call, 'Некорректный заказ.', show_alert=True)
        return
    order = await get_purchase_for_user(purchase_id, call.from_user.id)
    if not order or order['status'] != 'issued':
        await answer_safe(call, 'Заказ уже завершён или недоступен.', show_alert=True)
        return
    await edit_message_safe(call,
        f'<b>Завершить покупку #{purchase_id}?</b>\n\n'
        'Продолжайте, только если уже вошли в аккаунт. Сессия будет удалена из рабочей базы, '
        'и получить код через магазин больше не получится. Данные могут оставаться в резервных копиях до окончания срока их хранения.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            button('Я вошёл, удалить сессию', f'complete_confirm:{purchase_id}', 'confirm'),
            button('Отмена', f'open_purchase:{purchase_id}', 'cancel'),
        ]))
    await answer_safe(call)


@purchases_router.callback_query(F.data.startswith('complete_confirm:'))
async def confirm_completion(call: CallbackQuery):
    try:
        purchase_id = positive_id(call.data.split(':')[1])
        await bot_store.complete_order(call.from_user.id, purchase_id)
    except (ValueError, IndexError) as exc:
        await answer_safe(call, str(exc) or 'Некорректный заказ.', show_alert=True)
        return
    await render_order(call, purchase_id)
