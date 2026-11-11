"""Buyer guidance; warranty periods and financial rules remain in shared storage."""
from utils.i18n import LANGUAGE

RU = '''<b>Правила покупки и использования</b>

Прочитайте рекомендации до оплаты и первого входа. Проверьте описание товара: страну, год регистрации, Premium и статус спамблока. Выбирайте аккаунт с подходящими характеристиками, указанными в карточке.

<b>Безопасный вход</b>
<blockquote>• Используйте качественное личное подключение. Если входите через прокси, выбирайте надёжный приватный прокси страны аккаунта; избегайте общедоступных серверов с неизвестным владельцем.
• По возможности сохраните видеозапись первого входа: она поможет поддержке разобраться, если возникнет ошибка. Не публикуйте запись с личными данными.
• Никому не сообщайте коды входа, пароль двухэтапной аутентификации и данные сессии. Не передавайте доступ посторонним.</blockquote>

<b>Рекомендации после покупки</b>
<blockquote>• Первые три дня не спешите писать в незнакомые чаты и вступать сразу во множество групп. Избегайте частой смены устройств, подключения и повторных попыток входа.
• Имя и фамилию лучше не менять сразу после авторизации. Пользуйтесь аккаунтом спокойно и соблюдайте правила Telegram.
• После успешного входа установите собственный пароль двухэтапной аутентификации и привяжите резервную почту. Убедитесь, что у вас есть доступ к ней, и следуйте подсказкам Telegram.
• Завершайте покупку в боте только после проверки входа. После завершения повторно получить код через магазин уже нельзя.</blockquote>

<b>Гарантия и поддержка</b>
<blockquote>Магазин передаёт аккаунт в соответствии с описанием. Срок и условия гарантии смотрите в карточке товара и в своём заказе: эти рекомендации не меняют и не продлевают их.
Если возникла проблема со входом, напишите в поддержку до окончания указанного срока. Укажите номер заказа, время и описание ошибки. Не отправляйте пароли, коды и файлы сессий.
Поддержка проверит ситуацию и предложит решение по условиям покупки. За последующие действия в аккаунте и соблюдение правил Telegram отвечает его пользователь.</blockquote>'''

EN = '''<b>Purchase and account usage rules</b>

Read these recommendations before paying and signing in. Check the product description: country, registration year, Premium and spam restriction status. Choose an account with the characteristics you need.

<b>Secure sign-in</b>
<blockquote>• Use a trusted personal connection. If you use a proxy, choose a reliable private proxy in the account's country and avoid public servers with an unknown owner.
• If possible, record your first sign-in to help support investigate an error. Do not publish recordings containing personal data.
• Never share login codes, your two-step verification password or session data with other people.</blockquote>

<b>After purchase</b>
<blockquote>• During the first three days, take your time before messaging unfamiliar chats or joining many groups. Avoid frequent device or connection changes and repeated login attempts.
• Avoid changing the name immediately after signing in. Use the account responsibly and follow Telegram's rules.
• After a successful sign-in, set your own two-step verification password and recovery email. Make sure you can access that email and follow Telegram's instructions.
• Complete the purchase in the bot only after verifying that you can sign in. Once completed, login codes can no longer be retrieved through the store.</blockquote>

<b>Warranty and support</b>
<blockquote>The account is supplied according to its description. Check the warranty period and terms in the product card and your order; these recommendations do not change or extend them.
If you experience a sign-in problem, contact support before the stated deadline. Include the order number, time and error description. Do not send passwords, login codes or session files.
Support will review the issue under the purchase terms. The account user is responsible for subsequent actions and compliance with Telegram's rules.</blockquote>'''


def rules_text():
    return EN if LANGUAGE.get() == 'en' else RU
