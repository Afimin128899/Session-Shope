from utils.i18n import tr
from html import escape
from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import create_user_with_referrer, is_new_user, get_setting, update_user_username

from keyboards.user_kb import main_menu, information_menu
from utils import constants as c
from utils.nav import edit_message_safe, answer_safe
from utils.section_banners import answer_screen

start_router = Router()


@start_router.message(CommandStart())
async def cmd_start(message: Message, command, state=None):
    from utils.referral_link import pending
    saved_referrer = await pending(state)
    if state is not None:
        await state.clear()
    args = command.args
    referrer_id = saved_referrer
    if args and args.startswith('ref_'):
        try:
            referrer_id = int(args[4:])
            if referrer_id == message.from_user.id:
                referrer_id = None
        except ValueError:
            referrer_id = None
    is_new = await is_new_user(message.from_user.id)
    await create_user_with_referrer(message.from_user.id, referrer_id if is_new else None, message.from_user.username)
    await update_user_username(message.from_user.id, message.from_user.username)
    if args and args.startswith('product_'):
        from utils.miniapp import miniapp_url
        from aiogram.types import WebAppInfo
        value = args[8:]
        url = miniapp_url()
        if url and value.isascii() and value.isdigit() and (0 < int(value) <= 2147483647):
            await message.answer(tr('Откройте карточку аккаунта. Наличие и цена проверяются в магазине.'), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Открыть товар'), web_app=WebAppInfo(url=url + ('&' if '?' in url else '?') + 'product=' + value))]]))
            return
    if args and args.startswith('order_'):
        from database.db import get_purchase_for_user
        from keyboards.user_kb import after_purchase_menu
        value = args.removeprefix('order_')
        if value.isascii() and value.isdigit() and (len(value) <= 10):
            order = await get_purchase_for_user(int(value), message.from_user.id)
            if order:
                if order.get('status') == 'refunded':
                    await message.answer(tr('Заказ #{0} возвращён на баланс.', f"{order['id']}"), reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=tr('Открыть заказ'), callback_data=f"open_purchase:{order['id']}")]]))
                    return
                await message.answer(tr('🛍 <b>Заказ #{0}</b>\n\nАккаунт уже в ваших покупках. Получите код входа или откройте обращение в поддержку.', f"{order['id']}"), reply_markup=await after_purchase_menu(order['id']))
                return
        await message.answer(tr('Покупка не найдена. Откройте раздел «Мои покупки».'))
    user_name = escape(message.from_user.first_name or tr('Гость'))
    caption_text = c.start_text(user_name)
    await answer_screen(message, caption_text, section='home', reply_markup=await main_menu(message.from_user.id))


@start_router.callback_query(F.data == "back_main")
async def callback_back_main(call: CallbackQuery, state=None):
    if state is not None:
        from utils.referral_link import complete
        await complete(call.from_user, state)
        await state.clear()
    await update_user_username(call.from_user.id, call.from_user.username)
    user_name = escape(call.from_user.first_name or tr('Гость'))
    caption_text = c.start_text(user_name)
    await edit_message_safe(call, caption_text, reply_markup=await main_menu(call.from_user.id))
    await answer_safe(call)


@start_router.callback_query(F.data == "info_menu")
async def show_info(call: CallbackQuery):
    info_text = c.info_text()
    await edit_message_safe(call, info_text, reply_markup=information_menu())
    await answer_safe(call)


@start_router.callback_query(F.data == "check_sub_status")
async def check_sub_status_callback(call: CallbackQuery, state=None):
    from utils.sub_check import is_user_subscribed
    from utils.nav import edit_main
    subscribed = await is_user_subscribed(call.bot, call.from_user.id)
    if subscribed:
        from utils.referral_link import complete
        await complete(call.from_user, state)
        await answer_safe(call, tr('✅ Подписка подтверждена! Добро пожаловать.'), show_alert=True)
        await edit_main(call)
    else:
        await answer_safe(call, tr('❌ Вы ещё не подписались на наш канал! Подпишитесь и нажмите «Я подписался».'), show_alert=True)
