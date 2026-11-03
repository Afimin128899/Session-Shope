"""Native checkout, payment service messages and Stars amount input."""
import logging
import asyncio
from decimal import Decimal
from aiogram import Router,F
from aiogram.filters import Command
from aiogram.fsm.state import State,StatesGroup
from aiogram.types import InlineKeyboardButton,InlineKeyboardMarkup
from database import stars as ledger
from services import stars
from utils.actions import single_action
from utils.nav import answer_safe,edit_message_safe
from utils.button_icons import icon_for

stars_router=Router()
logger=logging.getLogger(__name__)
class StarsInput(StatesGroup):
    count=State()


@stars_router.pre_checkout_query()
async def pre_checkout(query):
    from services.demo import STORE
    if STORE.active(query.from_user.id):
        await query.answer(ok=False,error_message="Выйдите из тестового режима, чтобы оплатить рабочий счёт.");return
    try: await asyncio.wait_for(ledger.check_precheckout(query.from_user.id,query.invoice_payload,query.currency,query.total_amount), timeout=7)
    except ValueError as exc:
        await query.answer(ok=False,error_message=str(exc)[:200]);return
    except Exception:
        await query.answer(ok=False,error_message='Проверка оплаты временно недоступна. Попробуйте позже.');return
    await query.answer(ok=True)


@stars_router.message(F.successful_payment)
@stars_router.message(F.refunded_payment)
async def receipt(message):
    paid=message.successful_payment;payment=paid or message.refunded_payment
    try:
        if payment.currency!='XTR' or message.chat.type!='private': return
        event={'kind':'paid' if paid else 'refunded','invoice_id':ledger.invoice_id(payment.invoice_payload),'stars':ledger.parse_count(payment.total_amount),'charge_id':payment.telegram_payment_charge_id,'user_id':message.chat.id}
        if paid and message.from_user.id!=message.chat.id: return
    except (ValueError,AttributeError):
        logger.warning('Unrecognized Stars receipt');return
    try: amount=await stars.accept(event)
    except Exception:
        logger.warning('Stars receipt deferred')
        await message.answer('Telegram подтвердил операцию. Зачисление или возврат будет проверен автоматически. Помощь: /paysupport.');return
    if amount is not None:
        await message.answer(f'⭐ Зачислено: {amount:.2f} ₽. Курс: 1 ⭐ = 1,20 ₽.' if paid else f'Возврат звёзд учтён: баланс уменьшен на {amount:.2f} ₽.')


@stars_router.callback_query(F.data=='deposit_stars')
async def entry(call,state):
    await state.clear();await state.set_state(StarsInput.count)
    rows=[[InlineKeyboardButton(text=f'{n} ⭐ → {Decimal(n)*ledger.STARS_RATE:.2f} ₽',callback_data=f'stars_buy:{n}',icon_custom_emoji_id=icon_for('reviews'))] for n in (100,250,500,1000)]
    rows.append([InlineKeyboardButton(text='Назад',callback_data='topup_balance',icon_custom_emoji_id=icon_for('back'))])
    await edit_message_safe(call,'<b>Пополнение звёздами</b>\n\n1 ⭐ = 1,20 ₽ на баланс. Выберите вариант или введите целое количество от 1 до 10 000 ⭐. Отмена: /cancel.',reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await answer_safe(call)


async def native(bot,user_id,count,state):
    async with single_action(user_id,'stars_invoice') as acquired:
        if not acquired: return False
        await stars.send_invoice(bot,user_id,count);await state.clear();return True


@stars_router.callback_query(F.data.startswith('stars_buy:'))
async def preset(call,state):
    try: sent=await native(call.bot,call.from_user.id,ledger.parse_count(call.data.split(':',1)[1]),state)
    except ValueError as exc:
        await answer_safe(call,str(exc),show_alert=True);return
    await answer_safe(call,'Счёт отправлен в чат.' if sent else 'Счёт уже создаётся.')


@stars_router.message(StarsInput.count,F.text & ~F.text.startswith('/'))
async def count(message,state):
    try: await native(message.bot,message.from_user.id,ledger.parse_count(message.text.strip()),state)
    except ValueError as exc: await message.answer(str(exc))


@stars_router.message(Command('paysupport'))
async def support(message):
    await message.answer('По вопросам оплаты откройте «Поддержка» в главном меню /menu. Укажите сумму и дату, сохраните квитанцию Telegram. Не отправляйте пароли и коды входа.')
