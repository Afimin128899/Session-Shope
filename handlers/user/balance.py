"""Telegram payments use the same invoice registry and settlement as Mini App."""
from utils.i18n import tr
import logging
import secrets
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
    waiting_confirmation = State()


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
    methods = [method for method in await payments.get_methods() if method['enabled']]
    rows = [button(method['name'] + (' · 1 ⭐ = 1,20 ₽' if method['id'] == 'stars' else ('' if method['id'] in {'platega','heleket'} else ' · USDT')), 'deposit_' + method['id'], 'money') for method in methods]
    rows.append(button(tr('Назад к балансу'), 'balance'))
    text = tr('<b>Пополнение баланса</b>\n\nСумма задаётся в рублях. Выберите способ оплаты.') if methods else tr('<b>Пополнение баланса</b>\n\nСервисы оплаты пока не настроены. Обратитесь в поддержку.')
    await edit_message_safe(call, text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def _start_deposit(call, state, method):
    configured = next((m for m in await payments.get_methods() if m['id'] == method and m['enabled']), None)
    if not configured:
        await answer_safe(call, tr('Этот способ оплаты пока не настроен.'), show_alert=True)
        return
    await state.clear()
    await state.set_state(LaveDepositState.waiting_amount)
    await state.update_data(payment_method=method)
    await edit_message_safe(call, tr('<b>Пополнение через {0}</b>\n\nВведите сумму от {1} до {2} ₽. Например: <code>500</code> или <code>1000,50</code>.\n\nОтмена: /cancel', configured['name'], str(configured['min']), '10 000' if method == 'platega' else '1 000 000'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[button(tr('Назад'), 'topup_balance')]))
    await answer_safe(call)


@balance_router.callback_query(F.data.in_({'deposit_lave', 'deposit_xrocket', 'deposit_crypto', 'deposit_platega', 'deposit_heleket'}))
async def deposit_entry(call: CallbackQuery, state: FSMContext):
    await _start_deposit(call, state, call.data.removeprefix('deposit_'))


@balance_router.message(LaveDepositState.waiting_amount, F.text)
async def process_lave_amount(message: Message, state: FSMContext):
    data = await state.get_data()
    method = data.get('payment_method')
    try:
        amount = payments.parse_amount(message.text, method)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    if method == 'platega':
        token = secrets.token_hex(8)
        await state.set_state(LaveDepositState.waiting_confirmation)
        await state.update_data(payment_amount=f'{amount:.2f}',payment_nonce=token)
        await answer_screen(message, sbp_confirmation(amount), section='wallet', reply_markup=sbp_buttons(amount,token))
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


@balance_router.callback_query(F.data.startswith('lave_check:') | F.data.startswith('xrocket_check:') | F.data.startswith('crypto_check:') | F.data.startswith('platega_check:') | F.data.startswith('heleket_check:'))
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


def sbp_confirmation(amount):
    return tr('<b>Пополнение баланса в рублях</b>\n\nСпособ оплаты: <b>СБП</b>\nСумма пополнения: <b>{0} ₽</b>\nДопустимая сумма: от 1 до 10 000 ₽.\n\nНажмите «Оплатить», чтобы продолжить.', f'{amount:.2f}')


def sbp_buttons(amount, token):
    return InlineKeyboardMarkup(inline_keyboard=[button(tr('Оплатить {0} ₽', f'{amount:.2f}'), 'sbp_pay:' + token, 'money'),button(tr('Изменить сумму'), 'deposit_platega','edit'),button(tr('Назад'), 'topup_balance')])


@balance_router.callback_query(F.data.startswith('sbp_pay:'))
async def confirm_sbp(call: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    token = data.get('payment_nonce')
    if data.get('payment_method') != 'platega' or not isinstance(token, str) or not secrets.compare_digest(token,call.data.partition(':')[2]):
        await answer_safe(call,tr('Кнопка устарела. Введите сумму заново.'),show_alert=True)
        return
    async with single_action(call.from_user.id,'create_invoice') as acquired:
        if not acquired:
            await answer_safe(call,tr('Счёт уже создаётся. Подождите.'))
            return
        try:
            amount = payments.parse_amount(data.get('payment_amount'),'platega')
            result = await payments.create_deposit(call.from_user.id,call.from_user.username,'platega',amount)
        except payments.PaymentUnavailable as exc:
            await edit_message_safe(call,sbp_confirmation(amount)+'\n\n'+str(exc),reply_markup=sbp_buttons(amount,token))
            await answer_safe(call,str(exc),show_alert=True)
            return
        except ValueError as exc:
            await answer_safe(call,str(exc),show_alert=True)
            return
        except Exception:
            logger.error('SBP invoice creation failed')
            await answer_safe(call,tr('Не удалось создать счёт. Попробуйте позже.'),show_alert=True)
            return
        await state.clear()
        rows=[[InlineKeyboardButton(text=tr('Оплатить {0} ₽',f'{amount:.2f}'),url=result['pay_url'],icon_custom_emoji_id=icon_for('money'))],button(tr('Проверить оплату'),'platega_check:'+result['invoice_id'],'refresh'),button(tr('Вернуться к балансу'),'balance')]
        await edit_message_safe(call,tr('<b>Оплата через СБП</b>\n\nСумма пополнения: <b>{0} ₽</b>\n\nБаланс обновится после подтверждения оплаты.',f'{amount:.2f}'),reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
        await answer_safe(call)
