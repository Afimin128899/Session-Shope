import logging
import uuid

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import LAVE_PAY_API_KEY
from database.db import add_deposit_with_first_bonus, try_mark_comment_used, is_comment_used, log_payment
from keyboards.user_kb import balance_menu
from services.exchange import convert_rub_to_usdt
from services.lavepay import create_invoice, get_invoice, is_paid
from utils.nav import edit_balance, edit_message_safe, edit_main, answer_safe
from utils.emoji_map import EMOJI_BACK

balance_router = Router()


class LaveDepositState(StatesGroup):
    waiting_amount = State()


@balance_router.callback_query(F.data == "balance")
async def show_balance(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_balance(call)
    await answer_safe(call)


@balance_router.callback_query(F.data == "toggle_currency")
async def toggle_currency(call: CallbackQuery, state: FSMContext):
    await edit_balance(call)
    await answer_safe(call)


@balance_router.callback_query(F.data == "main_menu")
async def back_to_main(call: CallbackQuery):
    await edit_main(call)
    await answer_safe(call)


@balance_router.callback_query(F.data == "topup_balance")
async def topup_balance_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Lave Pay", callback_data="deposit_lave")],
        [InlineKeyboardButton(text="Назад", callback_data="balance", icon_custom_emoji_id=EMOJI_BACK)],
    ])
    text = (
        "💳 <b>Пополнение баланса</b>\n\n"
        "Доступен единый способ оплаты — <b>Lave Pay</b>.\n"
        "Сумма пополнения указывается в <b>рублях ₽</b>."
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@balance_router.callback_query(F.data == "deposit_lave")
async def deposit_lave_entry(call: CallbackQuery, state: FSMContext):
    if not LAVE_PAY_API_KEY:
        await answer_safe(call, "❌ Lave Pay ещё не настроен администратором.", show_alert=True)
        return

    await state.set_state(LaveDepositState.waiting_amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="topup_balance", icon_custom_emoji_id=EMOJI_BACK)]
    ])
    text = (
        "💳 <b>Пополнение через Lave Pay</b>\n\n"
        "Введите сумму пополнения в рублях:\n"
        "<i>Например:</i> <code>500</code> <i>или</i> <code>1000</code>"
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@balance_router.message(LaveDepositState.waiting_amount, F.text)
async def process_lave_amount(message: Message, state: FSMContext):
    try:
        rub_amount = round(float(message.text.strip().replace(",", ".")), 2)
    except ValueError:
        await message.answer("❌ Введите сумму числом, например: <code>500</code>.")
        return

    if rub_amount <= 0:
        await message.answer("❌ Сумма должна быть больше нуля.")
        return
    if rub_amount < 10:
        await message.answer("❌ Минимальная сумма пополнения — 10 ₽.")
        return
    if rub_amount > 1_000_000:
        await message.answer("❌ Максимальная сумма пополнения — 1 000 000 ₽.")
        return

    amount_usd = await convert_rub_to_usdt(rub_amount)
    order_id = f"topup-{message.from_user.id}-{uuid.uuid4().hex}"
    payload = f"rub_topup:{message.from_user.id}:{rub_amount:.2f}"

    invoice = await create_invoice(
        amount_usd=amount_usd,
        description=f"Пополнение баланса на {rub_amount:.2f} ₽",
        order_id=order_id,
        payload=payload,
    )

    if not invoice or not invoice.get("pay_url") or not invoice.get("id"):
        await message.answer("❌ Не удалось создать счёт Lave Pay. Проверьте API-ключ и попробуйте позже.")
        return

    invoice_id = invoice["id"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=invoice["pay_url"])],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"lave_check:{invoice_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="topup_balance", icon_custom_emoji_id=EMOJI_BACK)],
    ])

    await message.answer(
        "💳 <b>Счёт Lave Pay создан</b>\n\n"
        f"К оплате: <b>{rub_amount:.2f} ₽</b>\n\n"
        "Нажмите «Оплатить», завершите оплату, затем нажмите «Проверить оплату».",
        reply_markup=kb,
    )
    await state.clear()


@balance_router.callback_query(F.data.startswith("lave_check:"))
async def check_lave_payment(call: CallbackQuery):
    invoice_id = call.data.split(":", 1)[1]
    invoice = await get_invoice(invoice_id)

    if not invoice:
        await answer_safe(call, "❌ Счёт не найден.", show_alert=True)
        return

    payload = str(invoice.get("payload", ""))
    prefix = f"rub_topup:{call.from_user.id}:"
    if not payload.startswith(prefix):
        await answer_safe(call, "❌ Этот счёт не принадлежит вашему аккаунту.", show_alert=True)
        return

    if not is_paid(invoice):
        await answer_safe(call, "⌛️ Оплата ещё не подтверждена.", show_alert=True)
        return

    comment_key = f"lave_{invoice_id}"
    if await is_comment_used(comment_key):
        await answer_safe(call, "ℹ️ Этот платёж уже был зачислен.", show_alert=True)
        return

    marked = await try_mark_comment_used(comment_key)
    if not marked:
        await answer_safe(call, "ℹ️ Этот платёж уже обрабатывается.", show_alert=True)
        return

    rub_amount = float(payload.split(":", 2)[2])
    credited_amount, bonus_amount = await add_deposit_with_first_bonus(call.from_user.id, rub_amount)
    await log_payment(call.from_user.id, rub_amount, "RUB", "lave_pay", str(invoice_id))

    await edit_message_safe(
        call,
        "✅ <b>Оплата получена!</b>\n\n"
        f"На баланс зачислено: <b>{credited_amount:.2f} ₽</b>"
        + (f"\n🎁 Бонус за первое пополнение: <b>+{bonus_amount:.2f} ₽</b>." if bonus_amount > 0 else ""),
        reply_markup=balance_menu(),
    )
    await answer_safe(call, "Баланс пополнен!", show_alert=True)
