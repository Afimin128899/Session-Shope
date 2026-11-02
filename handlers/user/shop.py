from datetime import datetime
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from database.db import (
    buy_account,
    get_first_available_account_by_country,
    get_purchase_for_user,
    get_user,
    get_accounts_by_country,
    get_referrer,
    get_referral_settings,
    buy_account_with_referral,
    get_category,
    get_account,
)
from keyboards.user_kb import (
    after_purchase_menu,
    confirm_buy_menu,
    shop_menu,
)
from utils import constants as c
from utils.nav import edit_message_safe, answer_safe
from utils.emoji_map import EMOJI_CHECK, EMOJI_PHONE, EMOJI_LOCK


shop_router = Router()


@shop_router.callback_query(F.data == "buy")
async def open_shop(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    balance = float(user.get("balance", 0.0)) if user else 0.0

    kb, has_any = await shop_menu()
    if not has_any:
        text = "Нет аккаунтов в наличии"
    else:
        text = (
            f"Покупка Telegram аккаунта <tg-emoji emoji-id=\"5258134813302332906\">📦</tg-emoji>\n\n"
            f"<tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> <b>Баланс:</b> <code>{balance:.2f} ₽</code>\n\n"
            f"<tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji> Выберите категорию аккаунта:"
        )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@shop_router.callback_query(F.data == "back_buy")
async def back_buy(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    balance = float(user.get("balance", 0.0)) if user else 0.0

    kb, has_any = await shop_menu()
    if not has_any:
        text = "Нет аккаунтов в наличии"
    else:
        text = (
            f"Покупка Telegram аккаунта <tg-emoji emoji-id=\"5258134813302332906\">📦</tg-emoji>\n\n"
            f"<tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> <b>Баланс:</b> <code>{balance:.2f} ₽</code>\n\n"
            f"<tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji> Выберите категорию аккаунта:"
        )
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


def mask_phone(phone: str) -> str:
    """Маскирует телефонный номер до покупки.
    Пример: +77172727266266 -> +771***6266
    """
    if not phone:
        return ""
    clean = str(phone).strip()
    if len(clean) <= 6:
        return clean
    if clean.startswith("+"):
        prefix = clean[:4]
        suffix = clean[-4:]
        return f"{prefix}***{suffix}"
    else:
        prefix = clean[:3]
        suffix = clean[-4:]
        return f"{prefix}***{suffix}"


@shop_router.callback_query(F.data.startswith("buy_") & ~F.data.startswith("buy_curr:") & ~F.data.startswith("buy_acc:"))
async def select_product(call: CallbackQuery):
    sku = call.data[4:]  # убираем "buy_"
    if not sku:
        await answer_safe(call, "Товар не найден.", show_alert=True)
        return

    cat = await get_category(sku)
    if not cat:
        await answer_safe(call, "Категория не найдена.", show_alert=True)
        return

    display_country = cat.get("name") or sku

    accounts_list = await get_accounts_by_country(sku)
    if not accounts_list:
        await answer_safe(call, "Нет аккаунтов в наличии.", show_alert=True)
        return

    referrer_id = await get_referrer(call.from_user.id)
    if referrer_id:
        settings = await get_referral_settings()
    else:
        settings = None

    cat_emoji = cat.get("emoji")
    if cat_emoji and cat_emoji.isdigit():
        cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
    elif cat_emoji:
        cat_emoji_html = f" {cat_emoji}"
    else:
        cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

    text = (
        f"Покупка Telegram аккаунта <tg-emoji emoji-id=\"5258134813302332906\">📦</tg-emoji>\n\n"
        f"Категория: <b>{display_country}</b>{cat_emoji_html}\n"
        f"<tg-emoji emoji-id=\"5258134813302332906\">📦</tg-emoji> В наличии: <b>{len(accounts_list)}</b> шт.\n\n"
        f"Выберите необходимый номер из списка ниже 👇"
    )

    rows = []
    for acc in accounts_list:
        acc_price = float(acc["price"])
        if referrer_id and settings:
            acc_display_price = round(acc_price * (1 - settings["discount_pct"] / 100), 2)
        else:
            acc_display_price = acc_price

        price_str = f"{acc_display_price:.2f} ₽"
        btn_text = f"{mask_phone(acc['number'])} — {price_str}"
        rows.append([
            InlineKeyboardButton(
                text=btn_text,
                callback_data=f"buy_acc:{acc['id']}"
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="back_buy",
        )
    ])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@shop_router.callback_query(F.data.startswith("buy_acc:"))
async def select_specific_account(call: CallbackQuery):
    acc_id = int(call.data.split(":")[1])
    account = await get_account(acc_id)
    if not account or account.get("status") != "available":
        await answer_safe(call, "К сожалению, этот аккаунт уже недоступен.", show_alert=True)
        return

    sku = account["country"]
    cat = await get_category(sku)
    display_country = cat.get("name") if cat else sku

    price = float(account["price"])
    referrer_id = await get_referrer(call.from_user.id)
    if referrer_id:
        settings = await get_referral_settings()
        display_price = round(price * (1 - settings["discount_pct"] / 100), 2)
    else:
        display_price = price

    price_str = f"{display_price:.2f} ₽"

    cat_emoji = cat.get("emoji") if cat else None
    if cat_emoji and cat_emoji.isdigit():
        cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
    elif cat_emoji:
        cat_emoji_html = f" {cat_emoji}"
    else:
        cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

    text = (
        "<b>Подтверждение покупки:</b>\n\n"
        f"Категория: <b>{display_country}</b>{cat_emoji_html}\n"
        f"📱 Номер: <code>{mask_phone(account['number'])}</code>\n"
        f"<tg-emoji emoji-id=\"5406841020769936275\">💵</tg-emoji> Цена: <b>{price_str}</b>\n\n"
        "<blockquote>"
        f"<tg-emoji emoji-id=\"5258474669769497337\">❗️</tg-emoji> <b>Важно:</b> после покупки вам будет выдан номер, после ввода придет код.\n\n"
        f"<tg-emoji emoji-id=\"5258474669769497337\">❗️</tg-emoji> Если есть сессия — удалить через 24ч.\n\n"
        f"<tg-emoji emoji-id=\"5258474669769497337\">❗️</tg-emoji> Поставьте облачный пароль и почту."
        "</blockquote>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"Купить за {price_str}",
                    callback_data=f"confirm_buy_acc:{acc_id}",
                    icon_custom_emoji_id="5406841020769936275",
                )
            ],
            [
                InlineKeyboardButton(
                    text="Назад",
                    callback_data=f"buy_{sku}",
                )
            ]
        ]
    )

    await edit_message_safe(call, text, reply_markup=kb)
    await answer_safe(call)


@shop_router.callback_query(F.data.startswith("confirm_buy:") | F.data.startswith("confirm_buy_acc:"))
async def confirm_purchase(call: CallbackQuery):
    if call.data.startswith("confirm_buy_acc:"):
        acc_id = int(call.data.split(":")[1])
        account = await get_account(acc_id)
        if not account or account.get("status") != "available":
            await answer_safe(call, "❌ Извините, этот аккаунт уже куплен.", show_alert=True)
            return
        sku = account["country"]
    else:
        parts = call.data.split(":")
        sku = parts[1]
        account = await get_first_available_account_by_country(sku)
        if not account:
            await answer_safe(call, "Нет аккаунтов в наличии.", show_alert=True)
            return

    cat = await get_category(sku)
    display_country = cat.get("name") if cat else sku

    user = await get_user(call.from_user.id)
    price_rub = float(account["price"])

    referrer_id = await get_referrer(call.from_user.id)
    if referrer_id:
        settings = await get_referral_settings()
        effective_price_rub = round(price_rub * (1 - settings["discount_pct"] / 100), 2)
    else:
        settings = None
        effective_price_rub = price_rub

    user_balance = float(user.get("balance", 0.0)) if user else 0.0

    if user_balance < effective_price_rub:
        price_fmt = f"{effective_price_rub:.2f} ₽"
        await answer_safe(call, f"❌ Недостаточно средств на рублёвом балансе. Требуется {price_fmt}.", show_alert=True)
        return

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if referrer_id and settings:
        purchase_id = await buy_account_with_referral(
            call.from_user.id, account["id"], price_rub, date_str,
            settings["discount_pct"], settings["bonus_pct"],
            referrer_id=referrer_id, currency="RUB"
        )
    else:
        purchase_id = await buy_account(
            call.from_user.id, account["id"], price_rub, date_str, currency="RUB"
        )

    if not purchase_id:
        await answer_safe(call, "Ошибка транзакции. Попробуйте снова.", show_alert=True)
        return

    # Отправка уведомления администраторам о покупке
    from config import ADMIN_IDS
    import logging

    buyer_info = f"@{call.from_user.username}" if call.from_user.username else f"<a href='tg://user?id={call.from_user.id}'>{call.from_user.first_name}</a>"
    price_str = f"{effective_price_rub:.2f} ₽"

    admin_text = (
        f'<tg-emoji emoji-id="5224268678345794470">🛍</tg-emoji> <b>Уведомление о продаже аккаунта!</b>\n\n'
        f'<tg-emoji emoji-id="5341569745642595696">💻</tg-emoji> <b>Номер:</b> <code>{account["number"]}</code>\n'
        f'<tg-emoji emoji-id="5778661935927004845">📍</tg-emoji> <b>Категория:</b> <b>{display_country}</b>\n'
        f'<tg-emoji emoji-id="5987880246865565644">💰</tg-emoji> <b>Цена:</b> <code>{price_str}</code>\n'
        f'<tg-emoji emoji-id="5886412370347036129">👤</tg-emoji> <b>Покупатель:</b> {buyer_info} (ID: <code>{call.from_user.id}</code>)'
    )

    for admin_id in ADMIN_IDS:
        try:
            await call.bot.send_message(chat_id=admin_id, text=admin_text)
        except Exception as admin_err:
            logging.error(f"[shop] Не удалось отправить уведомление админу {admin_id}: {admin_err}")

    remaining_balance = user_balance - effective_price_rub
    display_spent = f"{effective_price_rub:.2f} ₽"
    display_balance = f"<tg-emoji emoji-id='5406841020769936275'>☺️</tg-emoji> Баланс: <b>{remaining_balance:.2f} ₽</b>"

    cat_emoji = cat.get("emoji") if cat else None
    if cat_emoji and cat_emoji.isdigit():
        cat_emoji_html = f" <tg-emoji emoji-id=\"{cat_emoji}\">☺️</tg-emoji>"
    elif cat_emoji:
        cat_emoji_html = f" {cat_emoji}"
    else:
        cat_emoji_html = " <tg-emoji emoji-id=\"5258509201306557640\">📍</tg-emoji>"

    text = (
        f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> <b>Покупка оформлена!</b>\n\n"
        f"Категория: <b>{display_country}</b>{cat_emoji_html}\n"
        f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> Номер: <code>{account['number']}</code>\n"
        f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> Пароль: <code>{account.get('password') or '-'}</code>\n"
        f"{c.MSG_EMOJI_MONEY} Списано: <b>{display_spent}</b>\n"
        f"{display_balance}\n\n"
        f"<i>Нажмите кнопку ниже для получения кода входа.</i>"
    )

    await edit_message_safe(call, text, reply_markup=await after_purchase_menu(purchase_id))
    await answer_safe(call, "Успешно!", show_alert=False)


@shop_router.callback_query(F.data.startswith("get_code:"))
async def deliver_login_code(call: CallbackQuery):
    import logging
    logger = logging.getLogger("handlers.user.shop")

    purc_id = int(call.data.split(":")[1])
    user_id = call.from_user.id
    username = call.from_user.username or "Unknown"

    logger.info(f"[deliver_login_code] User {user_id} (@{username}) requested verification code for purchase ID: {purc_id}")

    row = await get_purchase_for_user(purc_id, user_id)

    if not row:
        logger.warning(f"[deliver_login_code] Purchase ID {purc_id} not found or not owned by user {user_id}")
        await answer_safe(call, "Покупка не найдена.", show_alert=True)
        return

    session_str = row.get("data") or ""
    phone_number = row.get("number") or "Unknown"
    logger.info(f"[deliver_login_code] Found purchase record. Phone: {phone_number}. Session length: {len(session_str)}")

    if session_str == '✅ Сессия удалена (Покупка завершена)':
        logger.warning(f"[deliver_login_code] Session for purchase ID {purc_id} has already been deleted.")
        await answer_safe(call, "Сессия удалена. Посмотрите код в архиве покупок.", show_alert=True)
        return

    await answer_safe(call, "🔄 Запрашиваем код...", show_alert=False)

    from services.telethon_code import try_fetch_login_code

    logger.info(f"[deliver_login_code] Initiating Telethon connection to fetch code for {phone_number}...")
    code = await try_fetch_login_code(session_str, phone_number)

    if code == "SESSION_NOT_AUTHORIZED":
        logger.error(f"[deliver_login_code] FAILED. Session for {phone_number} is no longer authorized (expired or logged out).")
        await answer_safe(
            call,
            "❌ Сессия аккаунта неактивна или устарела (аккаунт вышел из сети).\nОбратитесь в поддержку за заменой.",
            show_alert=True,
        )
    elif code:
        logger.info(f"[deliver_login_code] SUCCESS! Code received for {phone_number}: {code}")
        await edit_message_safe(
            call,
            f"<tg-emoji emoji-id='{EMOJI_CHECK}'>✅</tg-emoji> <b>Код успешно получен!</b>\n\n"
            f"<tg-emoji emoji-id='{EMOJI_PHONE}'>📞</tg-emoji> Номер: <code>{phone_number}</code>\n"
            f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> Код входа: <code>{code}</code>\n"
            f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji> Пароль (2FA): <code>{row.get('password') or '-'}</code>\n\n"
            f"<i>⚠️ Введите код. Если Telegram запросит 2FA — используйте пароль выше.</i>",
            reply_markup=await after_purchase_menu(purc_id),
        )
    else:
        logger.warning(f"[deliver_login_code] FAILED. Code did not arrive for {phone_number} within wait limit.")
        await answer_safe(
            call,
            "⏳ Код пока не пришел.\n\nУбедитесь, что вы ввели номер в приложении. Повторите через 10 сек.",
            show_alert=True,
        )