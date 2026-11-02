from html import escape 
from aiogram import Router ,F 
from aiogram .types import CallbackQuery ,InlineKeyboardButton ,InlineKeyboardMarkup 


from database .db import get_purchase_for_user ,get_user_purchases ,complete_user_purchase, get_category, get_all_categories 
from keyboards .user_kb import purchases_list_menu 
from utils import constants as c 
from utils .nav import edit_message_safe, answer_safe 

purchases_router =Router ()

@purchases_router .callback_query (F .data =="my_purchases")
async def my_purchases (call :CallbackQuery ):
    """Список всех покупок пользователя"""
    rows =await get_user_purchases (call .from_user .id )
    if not rows :
        await edit_message_safe (
        call ,
        "🛍 <b>Мои покупки</b>\n\nУ вас пока нет покупок.",
        reply_markup =purchases_list_menu ([]),
        )
        await answer_safe(call)
        return 

    categories = await get_all_categories()
    cat_map = {c["slug"]: c for c in categories}

    lines =[]
    for i ,p in enumerate (rows ,1 ):
        slug = p['country']
        cat = cat_map.get(slug)
        if cat:
            cat_name = cat.get("name") or slug
            cat_emoji = cat.get("emoji")
        else:
            cat_name = slug
            cat_emoji = None

        if cat_emoji and cat_emoji.isdigit():
            cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
        elif cat_emoji:
            cat_emoji_html = f" {cat_emoji}"
        else:
            cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

        p['country_name'] = cat_name

        lines .append (
        f"<b>{i }. {cat_name}{cat_emoji_html}</b>\n"
        f"   📱 Номер: <code>{p ['number']}</code>\n"
        f"   📅 Дата: {p ['date']}\n"
        )

    text ="🛍 <b>История ваших покупок</b>\n\n"+"\n".join (lines )

    await edit_message_safe (
    call ,
    text ,
    reply_markup =purchases_list_menu (list (rows )),
    )
    await answer_safe(call)


@purchases_router .callback_query (F .data .startswith ("open_purchase:"))
async def open_purchase (call :CallbackQuery ):
    """Детальный просмотр конкретной покупки"""
    purc_id =int (call .data .split (":")[1 ])
    p =await get_purchase_for_user (purc_id ,call .from_user .id )

    if not p :
        await answer_safe(call, "Запись не найдена.",show_alert =True )
        return 

    price =float (p .get ('price',0 ))
    currency = p.get('currency') or 'TON'

    if currency.upper() == 'USDT':
        currency_suffix = "USDT <tg-emoji emoji-id=\"5406841020769936275\">☺️</tg-emoji>"
    else:
        currency_suffix = "TON <tg-emoji emoji-id=\"5406976471153545018\">☺️</tg-emoji>"

    formatted_price = int(price) if price.is_integer() else price

    is_completed =p .get ('data')=='✅ Сессия удалена (Покупка завершена)'


    cat = await get_category(p['country'])
    if cat:
        cat_name = cat.get("name") or p['country']
        cat_emoji = cat.get("emoji")
    else:
        cat_name = p['country']
        cat_emoji = None

    if cat_emoji and cat_emoji.isdigit():
        cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
    elif cat_emoji:
        cat_emoji_html = f" {cat_emoji}"
    else:
        cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

    text = (
        f'<tg-emoji emoji-id="5408830295002593386">📤</tg-emoji> <b>Детали покупки #{p ["id"]}</b>\n'
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
        f"Категория: <b>{cat_name}</b>{cat_emoji_html}\n"
        f'<tg-emoji emoji-id="5407025283456835913">📱</tg-emoji> Номер: <code>{p ["number"]}</code>\n'
        f'<tg-emoji emoji-id="5350491749926058609">🔐</tg-emoji> Пароль (2FA): <code>{p .get ("password")or "Нет"}</code>\n'
        f'<tg-emoji emoji-id="5312057711091813718">💳</tg-emoji> Цена: {formatted_price} {currency_suffix}\n'
        f'<tg-emoji emoji-id="5028418466000930064">📆</tg-emoji> Дата: {p ["date"]}\n'
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"
    )

    if is_completed :
        text +=f"\n✅ <b>Данные сессии надежно удалены из базы.</b>"
        kb =InlineKeyboardMarkup (
        inline_keyboard =[
        [InlineKeyboardButton (text ="« Назад",callback_data ="my_purchases")]
        ]
        )
    else :
        text +=(
        f'<tg-emoji emoji-id="5409257566939134596">🔗</tg-emoji> <b>Инструкция:</b>\n'
        f'1. Введите номер в приложении Telegram\n'
        f'2. Нажмите кнопку «Получить код» ниже\n'
        f'3. Если аккаунт спросит пароль — введите его из поля выше\n\n'
        f'<tg-emoji emoji-id="5408943604829794451">⚠️</tg-emoji> <b>Важно:</b>\n'
        f'После входа обязательно поставьте свою почту и смените пароль. '
        f'Затем нажмите «Завершение покупки», чтобы мы удалили данные сессии.'
        )

        kb =InlineKeyboardMarkup (
        inline_keyboard =[
        [
        InlineKeyboardButton (
        text ="Получить код",
        callback_data =f"get_code:{purc_id }"
        ),
        ],
        [
        InlineKeyboardButton (
        text ="Завершение покупки",
        callback_data =f"complete_purchase:{purc_id }",
        ),
        ],
        [
        InlineKeyboardButton (
        text ="« Назад",
        callback_data ="my_purchases"
        ),
        ],
        ]
        )

    kb.inline_keyboard.insert(0, [InlineKeyboardButton(
        text="Есть проблема", callback_data=f"purchase_help:{purc_id}",
    )])

    await edit_message_safe (call ,text ,reply_markup =kb )
    await answer_safe(call)


@purchases_router .callback_query (F .data .startswith ("complete_purchase:"))
async def complete_purchase (call :CallbackQuery ):
    """Завершение покупки и очистка сессии в БД"""
    purc_id =int (call .data .split (":")[1 ])
    p =await get_purchase_for_user (purc_id ,call .from_user .id )

    if not p :
        await answer_safe(call, "Запись не найдена.",show_alert =True )
        return 


    await complete_user_purchase (p ['account_id'])

    await answer_safe(call, 
    "✅ Покупка завершена!\n\n"
    "Данные сессии навсегда удалены из нашей базы.",
    show_alert =True 
    )


    await open_purchase (call )

@purchases_router.callback_query(F.data.startswith("purchase_help:"))
async def purchase_help(call: CallbackQuery):
    from config import SUPPORT_USERNAME
    from database.db import get_setting
    from utils.support import purchase_support_url

    try:
        purchase_id = int(call.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await answer_safe(call, "Покупка не найдена.", show_alert=True)
        return
    purchase = await get_purchase_for_user(purchase_id, call.from_user.id)
    if not purchase:
        await answer_safe(call, "Покупка не найдена.", show_alert=True)
        return
    contact = await get_setting("support_username", SUPPORT_USERNAME)
    url = purchase_support_url(contact, purchase_id)
    if not url:
        await answer_safe(call, "Контакт поддержки пока не настроен. Попробуйте позже.", show_alert=True)
        return
    await edit_message_safe(
        call,
        f"🛟 <b>Помощь по заказу #{purchase_id}</b>\n\n"
        "Нажмите кнопку, опишите проблему и отправьте сообщение в поддержку. "
        "Номер заказа уже добавлен в черновик. Не сообщайте пароли и коды входа.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Написать в поддержку", url=url)],
            [InlineKeyboardButton(text="Назад к заказу", callback_data=f"open_purchase:{purchase_id}")],
        ]),
    )
    await answer_safe(call)
