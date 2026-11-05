"""Telegram payments use the same invoice registry and settlement as Mini App."""
from utils.i18n import tr
import logging
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services import payments
from keyboards.user_kb import balance_menu
from utils.actions import single_action
from utils.button_icons import icon_for
from utils.nav import answer_safe, edit_balance, edit_main, edit_message_safe
from utils.section_banners import answer_screen

balance_router = Router()
logger = logging.getLogger(__name__)


class LaveDepositState(StatesGroup):
    waiting_amount = State()


def button(text, data, role='back'):
    return [InlineKeyboardButton(text=text, callback_data=data, icon_custom_emoji_id=icon_for(role))]


@balance_router.callback_query(F.data.in_({'balance', 'toggle_currency'}))
async def show_balance(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_balance(call)
    await answer_safe(call)


toggle_currency = show_balance


@balance_router.callback_query(F.data == 'main_menu')
async def back_to_main(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await edit_main(call)
    await answer_safe(call)


@balance_router.callback_query(F.data == 'topup_balance')
async def topup_balance_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    methods = [method for method in payments.methods() if method['enabled']]
    rows = [button(method['name'] + (' · 1 ⭐ = 1,20 ₽' if method['id'] == 'stars' else ' · USDT'), 'deposit_' + method['id'], 'money') for method in methods]
    rows.append(button(tr('Назад к балансу'), 'balance'))
    text = tr('<b>Пополнение баланса</b>\n\nСумма задаётся в рублях. Выберите способ оплаты.') if methods else tr('<b>Пополнение баланса</b>\n\nСервисы оплаты пока не настроены. Обратитесь в поддержку.')
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def _start_deposit(call, state, method):
    configured = next((m for m in payments.methods() if m['id'] == method and m['enabled']), None)
    if not configured:
        await answer_safe(call, tr('Этот способ оплаты пока не настроен.'), show_alert=True)
        return
    await state.clear()
    await state.set_state(LaveDepositState.waiting_amount)
    await state.update_data(payment_method=method)
    await edit_message_safe(call, tr('<b>Пополнение через {0}</b>\n\nВведите сумму от 10 до 1 000 000 ₽. Например: <code>500</code> или <code>1000,50</code>.\n\nОтмена: /cancel', f"{configured['name']}"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Назад'), 'topup_balance')]))
    await answer_safe(call)


@balance_router.callback_query(F.data.in_({'deposit_lave', 'deposit_xrocket', 'deposit_crypto'}))
async def deposit_entry(call: CallbackQuery, state: FSMContext):
    await _start_deposit(call, state, call.data.removeprefix('deposit_'))


@balance_router.message(LaveDepositState.waiting_amount, F.text)
async def process_lave_amount(message: Message, state: FSMContext):
    try:
        amount = payments.parse_amount(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    async with single_action(message.from_user.id, 'create_invoice') as acquired:
        if not acquired:
            await message.answer(tr('Счёт уже создаётся. Подождите.'))
            return
        data = await state.get_data()
        method = data.get('payment_method')
        try:
            result = await payments.create_deposit(message.from_user.id, message.from_user.username, method, amount)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        except Exception:
            logger.error('Invoice creation failed')
            await message.answer(tr('Не удалось создать счёт. Попробуйте позже. Если счёт уже появился в платёжном сервисе, обратитесь в поддержку.'))
            return
        rows = [[InlineKeyboardButton(text=tr('Оплатить'), url=result['pay_url'], icon_custom_emoji_id=icon_for('money'))], button(tr('Проверить оплату'), f"{method}_check:{result['invoice_id']}", 'refresh'), button(tr('Вернуться к балансу'), 'balance')]
        await state.clear()
        await answer_screen(message, tr('<b>Счёт создан</b>\n\nСумма: <b>{0} ₽</b>\nНомер: <code>{1}</code>\n\nБаланс пополнится автоматически после подтверждения сервисом. Кнопка проверки доступна как запасной вариант.', f'{amount:.2f}', f"{escape(result['invoice_id'])}"), section='wallet', reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@balance_router.callback_query(F.data.startswith('lave_check:') | F.data.startswith('xrocket_check:') | F.data.startswith('crypto_check:'))
async def check_payment(call: CallbackQuery):
    provider, invoice_id = call.data.split(':', 1)
    provider = provider.removesuffix('_check')
    async with single_action(call.from_user.id, 'check_invoice') as acquired:
        if not acquired:
            await answer_safe(call, tr('Платёж уже проверяется. Подождите.'))
            return
        try:
            result = await payments.check_invoice(call.from_user.id, provider, invoice_id)
        except ValueError as exc:
            await answer_safe(call, str(exc), show_alert=True)
            return
        if result['credited']:
            amount, bonus = result['credited']
            text = tr('<b>Оплата получена!</b>\n\nНа баланс зачислено: <b>{0} ₽</b>.', f'{amount:.2f}')
            if bonus:
                text += tr('\nБонус первого пополнения: {0} ₽.', f'{bonus:.2f}')
            await edit_message_safe(call, text, reply_markup=balance_menu())
            await answer_safe(call, tr('Баланс пополнен!'))
        else:
            text = {'credited': tr('Этот платёж уже зачислен. Откройте баланс.'), 'expired': tr('Срок счёта истёк. Создайте новый счёт.')}.get(result['status'], tr('Оплата ещё не подтверждена. Проверка продолжится автоматически.'))
            await answer_safe(call, text, show_alert=True)


check_lave_payment = check_xrocket_payment = check_crypto_payment = check_payment
