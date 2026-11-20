# Вход на сайт

Сайт принимает два способа входа:

- Telegram Mini App и Telegram Login Widget. Сервер проверяет подпись бот-токеном.
- Одноразовый шестизначный код на email. Паролей в базе нет.

## Идентификаторы и кошельки

Telegram-профиль сохраняет настоящий Telegram ID. Email-профиль получает внутренний ID из отдельного диапазона, начиная с `2**62`. Оба типа используют существующие таблицы баланса, покупок и истории, но их кошельки не объединяются автоматически.

Если магазин требует подписку на Telegram-канал, email-профиль не может пройти эту проверку. Сервер предложит войти через Telegram.

Пополнение партнёрского магазина также требует Telegram ID. Основной магазин принимает доступные веб-способы оплаты у email-профиля; Telegram Stars для него скрыты.

## Telegram Login Widget

Укажите домен `sbandsub.space` для основного бота через команду `/setdomain` в BotFather. Виджет использует имя этого же бота. Сервер отклоняет подписи от другого токена и данные старше одного часа.

## Отправка кодов по email

Передайте настройки процессу приложения через переменные окружения:

```text
AUTH_SMTP_HOST=smtp.example.com
AUTH_SMTP_PORT=587
AUTH_SMTP_SECURITY=starttls
AUTH_SMTP_USERNAME=...
AUTH_SMTP_PASSWORD=...
AUTH_SMTP_FROM=SBAND ACCS <login@example.com>
AUTH_PUBLIC_ORIGIN=https://sbandsub.space
AUTH_SESSION_TTL=2592000
AUTH_COOKIE_SECURE=1
```

`AUTH_SMTP_SECURITY` принимает `ssl`, `starttls` или `none`. Не используйте `none` с SMTP-логином через открытую сеть. Оставьте `AUTH_COOKIE_SECURE=1` на рабочем домене.

## База данных

`database.db.init_db()` создаёт таблицы `web_identities`, `web_email_codes` и `web_sessions`. Сессия хранится в браузере как `Secure`, `HttpOnly`, `SameSite=Lax` cookie. База хранит только SHA-256 хеш токена.

## Проверка после развёртывания

1. Откройте сайт вне Telegram и войдите каждым способом.
2. Проверьте выход и повторный вход после перезапуска приложения.
3. Убедитесь, что запрос с чужим заголовком `Origin` получает HTTP 403.
4. Проверьте, что Telegram Stars скрыты у email-профиля.
