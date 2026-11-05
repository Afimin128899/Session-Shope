
from utils.emoji_map import EMOJI_MEGA, EMOJI_PACKAGE, EMOJI_COIN, EMOJI_PIN, EMOJI_EXCLAMATION, EMOJI_INFO, EMOJI_PAGE, EMOJI_CHAT, EMOJI_STAR, EMOJI_LOCK

MSG_EMOJI_MAIL =f'<tg-emoji emoji-id="{EMOJI_MEGA}">📣</tg-emoji>'
MSG_EMOJI_CART =f'<tg-emoji emoji-id="{EMOJI_PACKAGE}">📦</tg-emoji>'
MSG_EMOJI_MONEY =f'<tg-emoji emoji-id="{EMOJI_COIN}">🪙</tg-emoji>'
MSG_EMOJI_FLYING_MONEY =f'<tg-emoji emoji-id="{EMOJI_COIN}">🪙</tg-emoji>'
MSG_EMOJI_GLOBE =f'<tg-emoji emoji-id="{EMOJI_PIN}">📍</tg-emoji>'
MSG_EMOJI_EARTH =f'<tg-emoji emoji-id="{EMOJI_PIN}">📍</tg-emoji>'
MSG_EMOJI_WARN =f'<tg-emoji emoji-id="{EMOJI_EXCLAMATION}">❗️</tg-emoji>'


START_TEXT =f"""<blockquote>
Привет, <b>{{name}}</b>! Добро пожаловать в магазин телеграмм аккаунтов {MSG_EMOJI_MAIL } 
</blockquote>
<blockquote>
Здесь вы можете приобрести телеграм аккаунты . <tg-emoji emoji-id="{EMOJI_INFO}">ℹ️</tg-emoji>
</blockquote>"""

BALANCE_TEXT =(
f"{MSG_EMOJI_MONEY } <b>Ваш баланс:</b> {{balance:.2f}} ₽ {MSG_EMOJI_FLYING_MONEY }\n\n"
f"Выберите способ пополнения:"
)

BALANCE_TEXT_USDT =(
f"{MSG_EMOJI_MONEY } <b>Ваш баланс:</b> {{balance:.2f}} ₽ {MSG_EMOJI_FLYING_MONEY }\n\n"
f"Выберите способ пополнения:"
)

SHOP_TEXT =f"""Покупка Telegram аккаунта {MSG_EMOJI_CART }

{MSG_EMOJI_MONEY } <b>Ваш баланс:</b> {{balance:.2f}} ₽ {MSG_EMOJI_FLYING_MONEY }

{MSG_EMOJI_EARTH } Выберите категорию аккаунта:"""

CONFIRM_BUY_TEXT =(
"<b>Подтверждение покупки:</b>\n\n"
f"{MSG_EMOJI_GLOBE } Категория: <b>{{country}}</b>\n"
f"<tg-emoji emoji-id='{EMOJI_PACKAGE}'>📦</tg-emoji> В наличии: <b>{{count}}</b> шт.\n"
f"{MSG_EMOJI_MONEY } Цена: <b>{{price:.2f}}</b> ₽ {MSG_EMOJI_FLYING_MONEY }\n\n"
"<blockquote>"
f"{MSG_EMOJI_WARN } <b>Важно:</b> после покупки вам будет выдан номер, после ввода придет код.\n\n"
f"{MSG_EMOJI_WARN } Если есть сессия — удалить через 24ч.\n\n"
f"{MSG_EMOJI_WARN } Поставьте облачный пароль и почту."
"</blockquote>"
)

CATALOG :dict [str ,tuple [str ,str ,float ]]={}

from utils.emoji_map import (
    EMOJI_SHOP, EMOJI_SUPPORT, EMOJI_REVIEWS, EMOJI_WALLET,
    EMOJI_COIN, EMOJI_BACK, EMOJI_BUY, EMOJI_CANCEL,
    EMOJI_PIN,
)

BTN_ICON_SHOP = EMOJI_SHOP
BTN_ICON_SUPPORT = EMOJI_SUPPORT
BTN_ICON_REVIEWS = EMOJI_REVIEWS
BTN_ICON_WALLET = EMOJI_WALLET
BTN_ICON_COIN = EMOJI_COIN
BTN_ICON_BACK_SMILE = EMOJI_BACK
BTN_ICON_BUY = EMOJI_BUY
BTN_ICON_CANCEL = EMOJI_CANCEL

FLAG_US = EMOJI_PIN
FLAG_RU = EMOJI_PIN
FLAG_UA = EMOJI_PIN
FLAG_CA = EMOJI_PIN
FLAG_IN = EMOJI_PIN
FLAG_GB = EMOJI_PIN
FLAG_BD = EMOJI_PIN
FLAG_ES = EMOJI_PIN


INFO_EMOJI_DOC =f"<tg-emoji emoji-id='{EMOJI_PAGE}'>📄</tg-emoji>"
INFO_EMOJI_SUPPORT =f"<tg-emoji emoji-id='{EMOJI_CHAT}'>💬</tg-emoji>"
INFO_EMOJI_STAR =f"<tg-emoji emoji-id='{EMOJI_STAR}'>⭐️</tg-emoji>"
INFO_EMOJI_SHIELD =f"<tg-emoji emoji-id='{EMOJI_LOCK}'>🔒</tg-emoji>"

INFO_TEXT =(
f"{INFO_EMOJI_STAR } <b>Информация о сервисе</b>\n\n"
f"{INFO_EMOJI_SUPPORT } <b>Поддержка:</b>\n"
f"Если у вас возникли проблемы с покупкой или есть вопросы, обращайтесь в нашу поддержку.\n\n"
f"{INFO_EMOJI_SHIELD } <b>Документация:</b>\n"
f"Используя нашего бота, вы соглашаетесь со следующими документами:\n"
f"• <a href='https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10'>Пользовательское соглашение</a>\n"
f"• <a href='https://telegra.ph/Politika-konfidencialnosti-08-15-17'>Политика конфиденциальности</a>"
)


# Resolve text at request time, after the customer's persisted language is known.
def start_text(name):
    from utils.i18n import LANGUAGE
    if LANGUAGE.get() == 'en':
        return f'<blockquote>Hello, <b>{name}</b>! Welcome to SBAND ACCS 🛍</blockquote>\n\nBrowse Telegram accounts, manage purchases and contact support below.'
    return START_TEXT.replace('{name}', name)


def info_text():
    from utils.i18n import LANGUAGE
    if LANGUAGE.get() == 'en':
        return ("ℹ️ <b>About the store</b>\n\n💬 Contact support if you have a question or a problem with a purchase.\n\n"
                "📄 <b>Documents</b>\nBy using this bot, you agree to the following documents:\n"
                "• <a href='https://telegra.ph/Polzovatelskoe-soglashenie-08-15-10'>User agreement</a>\n"
                "• <a href='https://telegra.ph/Politika-konfidencialnosti-08-15-17'>Privacy policy</a>")
    return INFO_TEXT
