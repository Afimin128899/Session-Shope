import os
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import create_user_with_referrer, is_new_user, get_setting, update_user_username

from keyboards.user_kb import main_menu, back_to_main_menu
from utils import constants as c
from utils.nav import edit_message_safe, answer_safe

start_router = Router()


@start_router.message(CommandStart())
async def cmd_start(message: Message, command, state=None):
    if state is not None:
        await state.clear()
    args = command.args
    referrer_id = None
    if args and args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
            if referrer_id == message.from_user.id:
                referrer_id = None
        except ValueError:
            referrer_id = None

    is_new = await is_new_user(message.from_user.id)
    await create_user_with_referrer(message.from_user.id, referrer_id if is_new else None, message.from_user.username)
    await update_user_username(message.from_user.id, message.from_user.username)

    if args and args.startswith("order_"):
        from database.db import get_purchase_for_user
        from keyboards.user_kb import after_purchase_menu
        value = args.removeprefix("order_")
        if value.isascii() and value.isdigit() and len(value) <= 10:
            order = await get_purchase_for_user(int(value), message.from_user.id)
            if order:
                if order.get('status') == 'refunded':
                    await message.answer(
                        f"Заказ #{order['id']} возвращён на баланс.",
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text="Открыть заказ", callback_data=f"open_purchase:{order['id']}"),
                        ]]),
                    )
                    return
                await message.answer(
                    f"🛍 <b>Заказ #{order['id']}</b>\n\n"
                    "Аккаунт уже в ваших покупках. Получите код входа или откройте обращение в поддержку.",
                    reply_markup=await after_purchase_menu(order['id']),
                )
                return
        await message.answer("Покупка не найдена. Откройте раздел «Мои покупки».")

    user_name = message.from_user.first_name or "Гость"
    caption_text = c.START_TEXT.replace("{name}", user_name)

    if os.path.isfile("assets/welcome.png"):
        photo = FSInputFile("assets/welcome.png")
        await message.answer_photo(photo, caption=caption_text, reply_markup=await main_menu(message.from_user.id))
    else:
        await message.answer(caption_text, reply_markup=await main_menu(message.from_user.id))


@start_router.callback_query(F.data == "back_main")
async def callback_back_main(call: CallbackQuery, state=None):
    if state is not None:
        await state.clear()
    await update_user_username(call.from_user.id, call.from_user.username)
    user_name = call.from_user.first_name or "Гость"
    caption_text = c.START_TEXT.replace("{name}", user_name)
    await edit_message_safe(call, caption_text, reply_markup=await main_menu(call.from_user.id))
    await answer_safe(call)


@start_router.callback_query(F.data == "info_menu")
async def show_info(call: CallbackQuery):
    info_text = c.INFO_TEXT
    await edit_message_safe(call, info_text, reply_markup=back_to_main_menu())
    await answer_safe(call)


@start_router.callback_query(F.data == "check_sub_status")
async def check_sub_status_callback(call: CallbackQuery):
    from utils.sub_check import is_user_subscribed
    from utils.nav import edit_main
    subscribed = await is_user_subscribed(call.bot, call.from_user.id)
    if subscribed:
        await answer_safe(call, "✅ Подписка подтверждена! Добро пожаловать.", show_alert=True)
        await edit_main(call)
    else:
        await answer_safe(call, "❌ Вы ещё не подписались на наш канал! Подпишитесь и нажмите «Я подписался».", show_alert=True)
