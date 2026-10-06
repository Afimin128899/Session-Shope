import logging
import uuid

from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import LAVE_PAY_API_KEY, XROCKET_API_KEY, CRYPTO_PAY_TOKEN
from database.db import add_deposit_with_first_bonus, try_mark_comment_used, is_comment_used, log_payment
from keyboards.user_kb import balance_menu
from services.exchange import convert_rub_to_usdt
from services.lavepay import create_invoice, get_invoice, is_paid
from services.xrocket import create_invoice as xrocket_create_invoice, get_invoice as xrocket_get_invoice, is_paid as xrocket_is_paid
from services.cryptopay import create_invoice as crypto_create_invoice, get_invoice as crypto_get_invoice, is_paid as crypto_is_paid
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
        [InlineKeyboardButton(text="🚀 xRocket Pay", callback_data="deposit_xrocket")],
        [InlineKeyboardButton(text="💎 Crypto Pay", callback_data="deposit_crypto")],
        [InlineKeyboardButton(text="Назад", callback_data="balance", icon_custom_emoji_id=EMOJI_BACK)],
    ])
    text = (
        "💳 <b>Пополнение баланса</b>\n\n"
        "Выберите способ оплаты. Сумма пополнения указывается в <b>рублях ₽</b>."
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


async def _start_deposit(call: CallbackQuery, state: FSMContext, method: str, title: str):
    configured = {
        "lave": LAVE_PAY_API_KEY,
        "xrocket": XROCKET_API_KEY,
        "crypto": CRYPTO_PAY_TOKEN,
    }[method]
    if not configured:
        await answer_safe(call, f"❌ {title} ещё не настроен администратором.", show_alert=True)
        return

    await state.set_state(LaveDepositState.waiting_amount)
    await state.update_data(payment_method=method)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Назад", callback_data="topup_balance", icon_custom_emoji_id=EMOJI_BACK)]
    ])
    text = (
        f"💳 <b>Пополнение через {title}</b>\n\n"
        "Введите сумму пополнения в рублях:\n"
        "<i>Например:</i> <code>500</code> <i>или</i> <code>1000</code>"
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@balance_router.callback_query(F.data == "deposit_lave")
async def deposit_lave_entry(call: CallbackQuery, state: FSMContext):
    await _start_deposit(call, state, "lave", "Lave Pay")


@balance_router.callback_query(F.data == "deposit_xrocket")
async def deposit_xrocket_entry(call: CallbackQuery, state: FSMContext):
    await _start_deposit(call, state, "xrocket", "xRocket Pay")


@balance_router.callback_query(F.data == "deposit_crypto")
async def deposit_crypto_entry(call: CallbackQuery, state: FSMContext):
    await _start_deposit(call, state, "crypto", "Crypto Pay")


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

    data = await state.get_data()
    payment_method = data.get("payment_method", "lave")
    payload = f"rub_topup:{message.from_user.id}:{rub_amount:.2f}"
    invoice_id = None
    pay_url = None
    order_id = f"topup-{message.from_user.id}-{uuid.uuid4().hex}"

    if payment_method == "xrocket":
        amount_usdt = await convert_rub_to_usdt(rub_amount)
        invoice = await xrocket_create_invoice(
            amount_usdt=amount_usdt,
            description=f"Пополнение баланса на {rub_amount:.2f} ₽",
            client_invoice_id=order_id,
            payload=payload,
            telegram_id=message.from_user.id,
            telegram_username=message.from_user.username,
        )
        invoice_id = str(invoice.get("id")) if invoice and invoice.get("id") else None
        pay_url = (invoice.get("links") or {}).get("telegramBotLink") if invoice else None
    elif payment_method == "crypto":
        invoice = await crypto_create_invoice(
            amount_rub=rub_amount,
            description=f"Пополнение баланса на {rub_amount:.2f} ₽",
            payload=payload,
        )
        invoice_id = str(invoice.get("invoice_id")) if invoice and invoice.get("invoice_id") else None
        pay_url = invoice.get("bot_invoice_url") if invoice else None
    else:
        amount_usd = await convert_rub_to_usdt(rub_amount)
        invoice = await create_invoice(
            amount_usd=amount_usd,
            description=f"Пополнение баланса на {rub_amount:.2f} ₽",
            order_id=order_id,
            payload=payload,
        )
        invoice_id = str(invoice.get("id")) if invoice and invoice.get("id") else None
        pay_url = invoice.get("pay_url") if invoice else None

    if not invoice_id or not pay_url:
        await message.answer("❌ Не удалось создать счёт. Проверьте настройки платёжного сервиса и попробуйте позже.")
        return

    prefix = {"lave": "lave", "xrocket": "xrocket", "crypto": "crypto"}[payment_method]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
        [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"{prefix}_check:{invoice_id}")],
        [InlineKeyboardButton(text="Назад", callback_data="topup_balance", icon_custom_emoji_id=EMOJI_BACK)],
    ])

    await message.answer(
        f"💳 <b>Счёт {('Lave Pay' if payment_method == 'lave' else 'xRocket Pay' if payment_method == 'xrocket' else 'Crypto Pay')} создан</b>\n\n"
        f"К оплате: <b>{rub_amount:.2f} ₽</b>\n\n"
        "Нажмите «Оплатить», завершите оплату, затем нажмите «Проверить оплату».",
        reply_markup=kb,
    )
    await state.clear()


async def _credit_paid(call: CallbackQuery, invoice_id: str, invoice: dict, provider: str):
    payload = str(invoice.get("payload", ""))
    prefix = f"rub_topup:{call.from_user.id}:"
    if not payload.startswith(prefix):
        await answer_safe(call, "❌ Этот счёт не принадлежит вашему аккаунту.", show_alert=True)
        return

    if not (xrocket_is_paid(invoice) if provider == "xrocket" else crypto_is_paid(invoice) if provider == "crypto" else is_paid(invoice)):
        await answer_safe(call, "⌛️ Оплата ещё не подтверждена.", show_alert=True)
        return

    comment_key = f"{provider}_{invoice_id}"
    if await is_comment_used(comment_key):
        await answer_safe(call, "ℹ️ Этот платёж уже был зачислен.", show_alert=True)
        return

    marked = await try_mark_comment_used(comment_key)
    if not marked:
        await answer_safe(call, "ℹ️ Этот платёж уже обрабатывается.", show_alert=True)
        return

    try:
        rub_amount = float(payload.split(":", 2)[2])
        credited_amount, bonus_amount = await add_deposit_with_first_bonus(call.from_user.id, rub_amount)
        await log_payment(call.from_user.id, rub_amount, "RUB", provider + ("_pay" if provider != "crypto" else "_pay"), str(invoice_id))
    except Exception:
        logging.exception("Failed to credit %s payment %s", provider, invoice_id)
        await answer_safe(call, "❌ Не удалось зачислить платёж. Обратитесь в поддержку.", show_alert=True)
        return

    await edit_message_safe(
        call,
        "✅ <b>Оплата получена!</b>\n\n"
        f"На баланс зачислено: <b>{credited_amount:.2f} ₽</b>"
        + (f"\n🎁 Бонус за первое пополнение: <b>+{bonus_amount:.2f} ₽</b>." if bonus_amount > 0 else ""),
        reply_markup=balance_menu(),
    )
    await answer_safe(call, "Баланс пополнен!", show_alert=True)


@balance_router.callback_query(F.data.startswith("lave_check:"))
async def check_lave_payment(call: CallbackQuery):
    invoice_id = call.data.split(":", 1)[1]
    invoice = await get_invoice(invoice_id)
    if not invoice:
        await answer_safe(call, "❌ Счёт не найден.", show_alert=True)
        return
    await _credit_paid(call, invoice_id, invoice, "lave")


@balance_router.callback_query(F.data.startswith("xrocket_check:"))
async def check_xrocket_payment(call: CallbackQuery):
    invoice_id = call.data.split(":", 1)[1]
    invoice = await xrocket_get_invoice(invoice_id)
    if not invoice:
        await answer_safe(call, "❌ Счёт xRocket не найден.", show_alert=True)
        return
    await _credit_paid(call, invoice_id, invoice, "xrocket")


@balance_router.callback_query(F.data.startswith("crypto_check:"))
async def check_crypto_payment(call: CallbackQuery):
    invoice_id = call.data.split(":", 1)[1]
    invoice = await crypto_get_invoice(invoice_id)
    if not invoice:
        await answer_safe(call, "❌ Счёт Crypto Pay не найден.", show_alert=True)
        return
    await _credit_paid(call, invoice_id, invoice, "crypto")
