"""Validate promos without losing the input form on a typo."""
from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import coupons
from keyboards.user_kb import promo_cancel, back_to_profile
from utils.actions import single_action
from utils.nav import answer_safe, edit_main, edit_message_safe, ensure_user

promo_router = Router()


class PromoState(StatesGroup):
    waiting_for_promo = State()


@promo_router.callback_query(F.data == 'promo')
async def ask_promo(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await ensure_user(call.from_user.id)
    await state.set_state(PromoState.waiting_for_promo)
    await edit_message_safe(call, '<b>Промокод</b>\n\nВведите код. Отмена: /cancel.', reply_markup=promo_cancel())
    await answer_safe(call)


@promo_router.callback_query(F.data == 'promo_cancel')
async def cancel_promo(call: CallbackQuery, state: FSMContext):
    await state.clear()
    from handlers.user.profile import my_profile
    await my_profile(call, state)
    await answer_safe(call)


@promo_router.message(PromoState.waiting_for_promo, F.text)
async def process_promo(message: Message, state: FSMContext):
    async with single_action(message.from_user.id, 'promo') as acquired:
        if not acquired:
            await message.answer('Промокод уже проверяется.')
            return
        try:
            preview = await coupons.preview(message.from_user.id, message.text)
            if preview['kind'] == 'discount':
                await message.answer(f"Это промокод на скидку {preview['value']}%. Введите его в подтверждении покупки или при оплате корзины Mini App. Сейчас он не расходуется.", reply_markup=back_to_profile())
                await state.clear()
                return
            value = await coupons.redeem_balance(message.from_user.id, preview['code'])
        except ValueError as exc:
            await message.answer(str(exc) + '\nПроверьте код и введите его ещё раз. Отмена: /cancel.', reply_markup=promo_cancel())
            return
        await state.clear()
        await message.answer(f'✅ <b>Промокод активирован!</b>\n\nЗачислено: <b>{value:.2f} ₽</b>.', reply_markup=back_to_profile())
