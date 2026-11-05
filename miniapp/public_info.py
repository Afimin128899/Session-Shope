"""Public review page: documents, live category prices and a direct support contact."""
from html import escape
import re
from decimal import Decimal

from aiohttp import web
import config
from database import db
from database.admin_web import rows
from utils.legal import PRIVACY_URL, AGREEMENT_URL, VERIFICATION_WORD
from utils.commerce_policy import category_allowed


def rub(value):
    return f'{Decimal(str(value)):,.2f}'.replace(',', '\u00a0').replace('.', ',')


async def about(request):
    from miniapp.server import BOT_USERNAME
    support = await db.get_setting('support_username', config.SUPPORT_USERNAME)
    support = str(support or '').strip()
    link = re.fullmatch(r'(?:https?://)?(?:t|telegram)\.me/(@?[A-Za-z0-9_]{5,32})/?', support)
    if link:
        support = link.group(1)
    username = request.app[BOT_USERNAME]
    contact = ''
    if re.fullmatch(r'@?[A-Za-z0-9_]{5,32}', support or ''):
        contact = f'<a class="secondary-button" href="https://t.me/{escape(support.lstrip("@"))}">Написать в поддержку · {escape(support)}</a>'
    bot_link = 'https://t.me/' + username if re.fullmatch(r'[A-Za-z0-9_]{5,32}', username or '') else None
    if bot_link:
        contact += f'<p>По заказу: откройте «Мой профиль → Мои покупки → Есть проблема» в <a href="{bot_link}">боте магазина</a>. Обращение и ответ поддержки сохраняются в боте.</p>'
    if not contact:
        contact = '<p>По заказу: «Мой профиль → Мои покупки → Есть проблема» в боте магазина.</p>'
    prices = await rows("SELECT c.slug,c.name,COUNT(a.id) AS quantity,MIN(a.price) AS minimum,MAX(a.price) AS maximum FROM categories c JOIN accounts a ON a.country=c.slug WHERE c.is_active=1 AND a.status='available' AND a.price>0 AND a.price<=10000 GROUP BY c.slug,c.name ORDER BY c.sort_order,c.name")
    def price(item):
        low, high = rub(item['minimum']), rub(item['maximum'])
        return low if low == high else low + '–' + high
    cards = ''.join(f'<div class="info"><span>{escape(item["name"])} · {item["quantity"]} шт.</span><b>{price(item)} ₽</b></div>' for item in prices if category_allowed(item['slug'], item['name']))
    if not cards:
        cards = '<p>Доступных товаров сейчас нет. Актуальные товары и их окончательная цена появляются в каталоге перед подтверждением покупки.</p>'
    html = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SBAND ACCS · Документы, цены и поддержка</title><link rel="stylesheet" href="/assets/style.css"></head>
<body class="public-info"><main class="public-card"><a href="/">SBAND <b>ACCS</b></a><h1>Информация</h1><p>Магазин Telegram-аккаунтов. Характеристики, цена и срок гарантии указаны в карточке каждого товара. Данные заказа доступны в покупках после оплаты.</p>
<h2>Документы</h2><div class="public-links"><a class="secondary-button" href="{PRIVACY_URL}" target="_blank" rel="noopener noreferrer">Политика конфиденциальности</a><a class="secondary-button" href="{AGREEMENT_URL}" target="_blank" rel="noopener noreferrer">Пользовательское соглашение</a></div>
<h2>Поддержка</h2>{contact}<h2>Актуальные цены</h2>{cards}<p>Цены в рублях за один аккаунт. Цена с доступными скидками и состав заказа показываются перед подтверждением покупки. Максимальная стоимость товара и одной покупки корзины — 10 000 ₽.</p>
<h2>Пополнение баланса</h2><p>Пополнение через настроенные платёжные сервисы: от 10 до 10 000 ₽ за операцию. Зачисленная сумма и условия оплаты показываются при создании счёта. Баланс используется для оплаты товаров магазина.</p><p>Telegram Stars: 1 ⭐ = 1,20 ₽. От 1 до 8 333 ⭐ за операцию (максимум 9 999,60 ₽). Подтверждение оплаты проверяется на сервере.</p><p>Для Platega используется постоянный числовой Telegram ID покупателя в формате ID@telegram.org. Это технический идентификатор, а не адрес почты покупателя. Настоящую почту для этой оплаты не запрашиваем.</p>
<p class="muted">Код проверки магазина: <code>{VERIFICATION_WORD}</code></p></main></body></html>'''
    return web.Response(text=html, content_type='text/html')
