"""Explicitly confirmed full refunds to the original bot balance."""
import logging
from decimal import Decimal
from html import escape

from aiogram import F, Router
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.admin_tools import find_order
from database.expansion import request_refund as refund_order
from handlers.admin.admin_panel import is_admin
from utils.nav import answer_safe, edit_message_safe

refund_router = Router()
refund_router.message.filter(F.chat.type == "private")
refund_router.callback_query.filter(F.message.chat.type == "private")
logger = logging.getLogger(__name__)


class RefundInput(StatesGroup):
    reason = State()
    confirm = State()


def back_to_order(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='К заказу', callback_data=f'adm_order:{order_id}'),
    ]])


@refund_router.callback_query(F.data.startswith('adm_refund:'))
async def start_refund(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    value = call.data.split(':', 1)[1]
    if not value.isascii() or not value.isdigit() or len(value) > 10:
        await answer_safe(call, 'Некорректный номер заказа.', show_alert=True)
        return
    order = await find_order(int(value))
    if not order or order['status'] not in {'issued', 'completed'} or order.get('paid_amount') is None:
        await answer_safe(call, 'Заказ не найден, уже возвращён или его сумма неизвестна.', show_alert=True)
        return
    await state.clear()
    await state.update_data(refund_order_id=order['id'])
    await state.set_state(RefundInput.reason)
    await edit_message_safe(call, f"Возврат по заказу #{order['id']}.\n\nВведите причину (3–500 символов). Сумма будет возвращена на баланс бота, а товар снят с продажи.", reply_markup=back_to_order(order['id']))
    await answer_safe(call)


@refund_router.message(RefundInput.reason)
async def refund_reason(message, state):
    if not is_admin(message.from_user.id):
        return
    reason = (message.text or '').strip()
    if not 3 <= len(reason) <= 500:
        await message.answer('Укажите причину от 3 до 500 символов.')
        return
    data = await state.get_data()
    order = await find_order(data.get('refund_order_id', 0))
    if not order or order['status'] not in {'issued', 'completed'} or order.get('paid_amount') is None:
        await state.clear()
        await message.answer('Заказ уже возвращён или недоступен.')
        return
    warning = ''
    if order.get('referral_bonus') is None:
        warning = '\n\nУ старого заказа нет истории бонуса: реферальный бонус автоматически не отменяется.'
    elif Decimal(str(order['referral_bonus'])) > 0:
        warning = f"\n\nРеферальный бонус {order['referral_bonus']} {order['currency']} будет отменён. Если его уже потратили, баланс пригласившего станет отрицательным."
    await state.update_data(refund_reason=reason)
    await state.set_state(RefundInput.confirm)
    await message.answer(
        f"<b>Подтвердите возврат #{order['id']}</b>\n"
        f"Покупатель: <code>{order['user_id']}</code>\n"
        f"На баланс бота: <b>{order['paid_amount']} {escape(order['currency'])}</b>\n"
        f"Причина: {escape(reason)}{warning}\n\nЭто не перевод на внешний кошелёк. Повторное зачисление этого заказа запрещено.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='Подтвердить возврат', callback_data=f"adm_refund_confirm:{order['id']}")],
            [InlineKeyboardButton(text='Отмена', callback_data=f"adm_order:{order['id']}")],
        ]),
    )


@refund_router.callback_query(F.data.startswith('adm_refund_confirm:'))
async def confirm_refund(call, state):
    if not is_admin(call.from_user.id):
        await answer_safe(call, 'Доступ запрещён.', show_alert=True)
        return
    data = await state.get_data()
    value = call.data.split(':', 1)[1]
    if (await state.get_state() != RefundInput.confirm.state or not value.isascii() or not value.isdigit()
            or len(value) > 10 or int(value) != data.get('refund_order_id') or not data.get('refund_reason')):
        await answer_safe(call, 'Начните оформление возврата заново из карточки заказа.', show_alert=True)
        return
    try:
        result = await refund_order(call.from_user.id, int(value), data['refund_reason'])
    except ValueError as exc:
        await answer_safe(call, str(exc), show_alert=True)
        return
    except Exception:
        logger.error('Refund failed for order %s', value)
        await answer_safe(call, 'Не удалось сохранить возврат. Повторите проверку позже.', show_alert=True)
        return
    await state.clear()
    if result and result.get('pending'):
        from config import ADMIN_IDS
        for admin in set(ADMIN_IDS)-{call.from_user.id}:
            try:
                await call.bot.send_message(admin,f"Требуется согласование возврата #{value}: {result['amount']} {escape(result['currency'])} на баланс бота. Реферальный бонус будет отменён согласно записи заказа. Причина: {escape(data['refund_reason'])}",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Согласовать возврат',callback_data=f'refund_approve:{value}')]]))
            except Exception: pass
        await answer_safe(call,'Заявка сохранена. Нужен второй администратор.',show_alert=True)
        return
    if result is None:
        await answer_safe(call, 'Этот заказ уже возвращён.', show_alert=True)
        return
    await edit_message_safe(call, f"✅ По заказу #{result['id']} возвращено {result['amount']} {result['currency']} на баланс покупателя.", reply_markup=back_to_order(result['id']))
    await answer_safe(call, 'Возврат выполнен.')
    try:
        await call.bot.send_message(result['user_id'], f"По заказу #{result['id']} оформлен возврат: {result['amount']} {result['currency']} зачислено на баланс бота.")
    except Exception:
        logger.warning('Refund notification could not be delivered for order %s', result['id'])
