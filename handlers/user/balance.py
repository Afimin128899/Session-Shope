import uuid
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS, SUPPORT_USERNAME, RUB_DETAILS
from utils.nav import edit_balance, edit_message_safe, edit_main, answer_safe
from utils.emoji_map import EMOJI_WALLET, EMOJI_CHECK, EMOJI_CROSS, EMOJI_BACK, EMOJI_INFO, EMOJI_CHAT, EMOJI_COIN
from database.db import get_user, add_balance, try_mark_comment_used, is_comment_used, log_payment, get_setting
from services.exchange import get_rub_usdt_rate

balance_router = Router()


class RubDepositState(StatesGroup):
    waiting_amount = State()


@balance_router.callback_query(F.data == "balance")
async def show_balance(call: CallbackQuery, state: FSMContext):
    """Отображает текущий баланс пользователя и кнопку пополнения"""
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
    """Меню выбора платежной системы (CryptoBot USDT или Рубли по заявке)"""
    await state.clear()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="CryptoBot (USDT $)",
                    callback_data="deposit_crypto",
                    icon_custom_emoji_id="5406841020769936275"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Карта / СБП (Рубли ₽ — Заявка)",
                    callback_data="deposit_rub_req",
                    icon_custom_emoji_id="5258368777350816286"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data="balance",
                    icon_custom_emoji_id=EMOJI_BACK
                ),
            ],
        ]
    )

    text = (
        "<tg-emoji emoji-id='5258260149037965799'>💳</tg-emoji> <b>Выберите способ пополнения баланса</b>\n\n"
        "<b>Доступные методы:</b>\n"
        "• <b><tg-emoji emoji-id='5406841020769936275'>☺️</tg-emoji> CryptoBot</b> — моментальное пополнение в USDT ($)\n"
        "• <b><tg-emoji emoji-id='5258368777350816286'>🪙</tg-emoji> Карта / СБП (Заявка)</b> — переведите рубли по реквизитам, средства зачислятся на долларовый баланс в USDT ($)\n\n"
        "<i>Выберите удобный способ ниже 👇</i>"
    )

    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


# ── Пополнение в RUB через ручную заявку ──────────────────────────────

@balance_router.callback_query(F.data == "deposit_rub_req")
async def deposit_rub_req(call: CallbackQuery, state: FSMContext):
    await state.set_state(RubDepositState.waiting_amount)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Отмена", callback_data="topup_balance", icon_custom_emoji_id=EMOJI_CROSS)]
    ])
    text = (
        "<tg-emoji emoji-id='5258368777350816286'>🪙</tg-emoji> <b>Пополнение баланса в Рублях (₽)</b>\n\n"
        "Введите желаемую сумму пополнения в рублях:\n"
        "<i>Пришлите число, например: </i><code>500</code><i> или </i><code>1000</code>"
    )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@balance_router.message(RubDepositState.waiting_amount, F.text)
async def process_rub_deposit_amount(message: Message, state: FSMContext):
    try:
        amount_rub = float(message.text.strip().replace(",", "."))
        if amount_rub <= 0:
            await message.answer("❌ Сумма должна быть больше нуля. Введите ещё раз:")
            return

        req_id = uuid.uuid4().hex[:8]
        support_val = await get_setting("support_username", SUPPORT_USERNAME or "—")
        rub_details = await get_setting("rub_details", RUB_DETAILS or "Реквизиты уточняйте у администратора")
        

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Я оплатил (Отправить заявку)",
                    callback_data=f"confirm_rub_paid:{req_id}:{amount_rub:.2f}:{amount_rub:.2f}",
                    icon_custom_emoji_id=EMOJI_CHECK
                )
            ],
            [
                InlineKeyboardButton(
                    text="Отмена",
                    callback_data="balance",
                    icon_custom_emoji_id=EMOJI_CROSS
                )
            ]
        ])

        text = (
            f"<tg-emoji emoji-id='5258368777350816286'>🪙</tg-emoji> <b>Заявка на пополнение №<code>{req_id}</code></b>\n\n"
            f"<blockquote>"
            f"<tg-emoji emoji-id='5258260149037965799'>💼</tg-emoji> Сумма к оплате: <b>{amount_rub:.2f} ₽</b>\n"
            f"<tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> К зачислению: <b>{amount_rub:.2f} ₽</b>\n"
            f"<tg-emoji emoji-id='5258391025281408576'>📈</tg-emoji> Курс конвертации: <b>1 USDT = {rate:.2f} ₽</b>\n"
            f"<tg-emoji emoji-id='5312110302966343332'>🏦</tg-emoji> Реквизиты: <code>{rub_details}</code>\n"
            f"<tg-emoji emoji-id='5258215846450305872'>💬</tg-emoji> Поддержка / Оператор: <b>{support_val}</b>"
            f"</blockquote>\n\n"
            f"<blockquote>"
            f"<tg-emoji emoji-id='5258474669769497337'>❗️</tg-emoji> <b>ВАЖНОЕ ПРЕДУПРЕЖДЕНИЕ:</b>\n"
            f"Переводите строго на <b>Озон Банк</b>! Если вы закинете на какой-то не тот банк, деньги попросту сгорят и вы ничего не получите.\n\n"
            f"После совершения перевода нажмите кнопку <b>«Я оплатил (Отправить заявку)»</b> ниже."
            f"</blockquote>"
        )

        await message.answer(text, reply_markup=kb)
        await state.clear()

    except ValueError:
        await message.answer("❌ Введите сумму числом, например: <code>500</code> или <code>1000</code>")


@balance_router.callback_query(F.data.startswith("confirm_rub_paid:"))
async def confirm_rub_paid(call: CallbackQuery):
    parts = call.data.split(":")
    req_id = parts[1]
    amount_rub = float(parts[2])
    

    user_id = call.from_user.id
    user_name = call.from_user.full_name or f"User {user_id}"

    # Отправляем уведомления администраторам
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=f"Подтвердить ({amount_rub:.2f} ₽)",
                callback_data=f"approve_rub:{user_id}:{amount_rub:.2f}:{req_id}",
                icon_custom_emoji_id=EMOJI_CHECK
            ),
            InlineKeyboardButton(
                text="Отклонить",
                callback_data=f"reject_rub:{user_id}:{amount_rub:.2f}:{req_id}",
                icon_custom_emoji_id=EMOJI_CROSS
            )
        ]
    ])

    admin_text = (
        f"<tg-emoji emoji-id='5258368777350816286'>📥</tg-emoji> <b>Новая заявка на пополнение!</b>\n\n"
        f"<blockquote>"
        f"<tg-emoji emoji-id='5258362837411045098'>👤</tg-emoji> Пользователь: <b>{user_name}</b> (ID: <code>{user_id}</code>)\n"
        f"<tg-emoji emoji-id='5258260149037965799'>💼</tg-emoji> Сумма оплаты: <b>{amount_rub:.2f} ₽</b>\n"
        f"<tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> К зачислению: <b>{amount_rub:.2f} ₽</b>\n"
        f"<tg-emoji emoji-id='5226513232549664618'>🔢</tg-emoji> ID Заявки: <code>{req_id}</code>"
        f"</blockquote>"
    )

    sent_count = 0
    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(admin_id, admin_text, reply_markup=admin_kb)
            sent_count += 1
        except Exception as e:
            logging.warning(f"[balance] Failed to send deposit alert to admin {admin_id}: {e}")

    await edit_message_safe(
        call,
        f"<tg-emoji emoji-id='5258419835922030550'>⏳</tg-emoji> <b>Заявка №<code>{req_id}</code> на {amount_rub:.2f} ₽ ({amount_rub:.2f} ₽) отправлена администраторам.</b>\n\n"
        f"<i>Средства будут зачислены сразу после проверки перевода оператором.</i>"
    )
    await answer_safe(call, "Заявка отправлена на проверку!", show_alert=True)


# ── Обработка заявок Администратором ─────────────────────────────────

@balance_router.callback_query(F.data.startswith("approve_rub:"))
async def approve_rub_deposit(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, "❌ У вас нет прав для этого действия.", show_alert=True)
        return

    parts = call.data.split(":")
    user_id = int(parts[1])
    usdt_amount = float(parts[2])
    req_id = parts[3]

    comment_key = f"rub_req_{req_id}"

    if await is_comment_used(comment_key):
        await answer_safe(call, "❌ Заявка уже была обработана ранее!", show_alert=True)
        return

    marked = await try_mark_comment_used(comment_key)
    if not marked:
        await answer_safe(call, "❌ Заявка уже была обработана ранее!", show_alert=True)
        return

    # Зачисляем баланс USDT
    await add_balance(user_id, amount_rub)
    await log_payment(user_id, amount_rub, "RUB", "manual_rub_request", req_id)

    # Уведомляем пользователя
    try:
        await call.bot.send_message(
            user_id,
            f"<tg-emoji emoji-id='5260726538302660868'>✅</tg-emoji> <b>Ваша заявка №<code>{req_id}</code> успешно подтверждена!</b>\n\n"
            f"<blockquote>"
            f"<tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> На ваш баланс зачислено: <b>{amount_rub:.2f} ₽</b>"
            f"</blockquote>"
        )
    except Exception as e:
        logging.warning(f"[balance] Failed to notify user {user_id} about deposit approval: {e}")

    await edit_message_safe(
        call,
        f"<tg-emoji emoji-id='5260726538302660868'>✅</tg-emoji> <b>Заявка №<code>{req_id}</code> ПОДТВЕРЖДЕНА!</b>\n\n"
        f"<blockquote>"
        f"<tg-emoji emoji-id='5258362837411045098'>👤</tg-emoji> Пользователь: <code>{user_id}</code>\n"
        f"<tg-emoji emoji-id='5406841020769936275'>💵</tg-emoji> Зачислено: <b>{amount_rub:.2f} ₽</b>\n"
        f"<tg-emoji emoji-id='5258450450448915742'>👨‍🎨</tg-emoji> Админ: <b>{call.from_user.full_name}</b>"
        f"</blockquote>"
    )
    await answer_safe(call, "Пополнение подтверждено!", show_alert=True)


@balance_router.callback_query(F.data.startswith("reject_rub:"))
async def reject_rub_deposit(call: CallbackQuery):
    if call.from_user.id not in ADMIN_IDS:
        await answer_safe(call, "❌ У вас нет прав для этого действия.", show_alert=True)
        return

    parts = call.data.split(":")
    user_id = int(parts[1])
    usdt_amount = float(parts[2])
    req_id = parts[3]

    comment_key = f"rub_req_{req_id}"

    if await is_comment_used(comment_key):
        await answer_safe(call, "❌ Заявка уже была обработана ранее!", show_alert=True)
        return

    await try_mark_comment_used(comment_key)

    # Уведомляем пользователя
    try:
        await call.bot.send_message(
            user_id,
            f"<tg-emoji emoji-id='5258453452631056344'>❌</tg-emoji> <b>Ваша заявка №<code>{req_id}</code> была отклонена администратором.</b>"
        )
    except Exception as e:
        logging.warning(f"[balance] Failed to notify user {user_id} about deposit rejection: {e}")

    await edit_message_safe(
        call,
        f"<tg-emoji emoji-id='5258453452631056344'>❌</tg-emoji> <b>Заявка №<code>{req_id}</code> ОТКЛОНЕНА.</b>\n\n"
        f"<blockquote>"
        f"<tg-emoji emoji-id='5258362837411045098'>👤</tg-emoji> Пользователь: <code>{user_id}</code>\n"
        f"<tg-emoji emoji-id='5258450450448915742'>👨‍🎨</tg-emoji> Админ: <b>{call.from_user.full_name}</b>"
        f"</blockquote>"
    )
    await answer_safe(call, "Заявка отклонена.", show_alert=True)
