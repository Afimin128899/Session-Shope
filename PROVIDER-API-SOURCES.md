# Источники контрактов платёжных API

Ссылки пользователя:

- https://docs.xrocket.exchange/api/pay/pay-api-overview
- https://laveshka.io/docs/lave-pay
- https://help.cr.bot/en/articles/10279948-crypto-pay-api

Во время разработки эти три сайта возвращали `403` на CONNECT через разрешённый прокси облачной среды. Их текущий текст напрямую проверить не удалось. Рабочие платёжные ключи, создание реальных счетов и проверка реальных оплат при разработке не использовались.

## xRocket

Выбор контракта явный, через серверную переменную `XROCKET_API_MODE`:

- `exchange` — значение по умолчанию; сохраняет ранее использовавшийся контракт `https://pay.api.xrocket.exchange/api/v1`, `Authorization: Bearer`, `POST /invoices`, `GET /invoice?invoiceId=...`, поля `priceAmount`, `priceCurrency`, `callback.payload.orderId`, ссылка `links.telegramBotLink`. Текущая документация этого варианта в облачной среде недоступна; формат не подменяется догадкой или другим API.
- `tg` — контракт опубликованного SDK организации `xrocket-tg`: `https://pay.xrocket.tg`, заголовок `Rocket-Pay-Key`, `POST /tg-invoices`, `GET /tg-invoices/{id}`. Создание: `amount`, `currency: USDT`, `numPayments: 1`, `payload`, `expiredIn: 3600`. Ответ `{success: true, data: {id, link, payload, status, ...}}`.

Источник `tg`: [xrocket-tg/xrocket-pay-ts-sdk](https://github.com/xrocket-tg/xrocket-pay-ts-sdk), версия исходников `8014b1d` от 26.06.2025; [client.ts](https://github.com/xrocket-tg/xrocket-pay-ts-sdk/blob/8014b1d/src/client.ts), [invoice.ts](https://github.com/xrocket-tg/xrocket-pay-ts-sdk/blob/8014b1d/src/types/invoice.ts). SDK опубликован в npm как `xrocket-pay-api-sdk`.

Автоматического переключения между контрактами нет. После ошибки создания счёта адаптер не выполняет второй POST к другому API. Для ключа из выбранного кабинета используйте соответствующий режим; переключение режима не переносит старые счета между API.

## Laveshka / Lave Pay

Пакет [`lavepay`](https://pypi.org/project/lavepay/) ссылается на документацию пользователя и репозиторий [`laveshka-wallet/lave-pay`](https://github.com/laveshka-wallet/lave-pay). Проверена версия исходников `4b2b9e7` от 07.10.2026.

- [transport.py](https://github.com/laveshka-wallet/lave-pay/blob/4b2b9e7/lavepay/transport.py): база `https://api.laveshka.io/merchant/v1`, заголовок `X-Api-Key`, успешный ответ с полем `data`.
- [invoices.py](https://github.com/laveshka-wallet/lave-pay/blob/4b2b9e7/lavepay/resources/invoices.py): `POST /invoices`, `GET /invoices/{id}`, поля `amount`, `currency` (по умолчанию `USD`), `description`, `order_id`, `payload`, `ttl`.
- [objects.py](https://github.com/laveshka-wallet/lave-pay/blob/4b2b9e7/lavepay/models/objects.py): `id`, `status`, `amount`, `currency`, `pay_url`, `payload`. Состояние оплаченного счёта — `paid`.

Исправлен хост API: `api.laveshka.io`, явно задаётся `currency: USD`. Нельзя путать Laveshka с другими сервисами, использующими название Lava Pay: их ключи и API невзаимозаменяемы.

## Crypto Pay

Существующий контракт соответствует опубликованному SDK [`layerqa/aiocryptopay`](https://github.com/layerqa/aiocryptopay), версия исходников `731b929` от 05.07.2025; это сторонняя библиотека, а не подтверждение работоспособности текущего боевого API.

[api.py](https://github.com/layerqa/aiocryptopay/blob/731b929/aiocryptopay/api.py): `Crypto-Pay-API-Token`, `POST /api/createInvoice`, `GET /api/getInvoices`, фиатная сумма `currency_type: fiat`, `fiat: RUB`, `amount`, `payload`; получение конкретного счёта через `invoice_ids`. Сохраняется база `https://pay.crypt.bot/api`, ответ `{ok: true, result: ...}`, массив счетов `result.items`. Статус оплаты — `paid`.

## Поведение адаптеров

При неуспешном HTTP-статусе, неверном JSON, отклонённом ответе или ошибке связи адаптер не возвращает оплаченный счёт. POST не повторяется автоматически. HTTP-перенаправления отключены, чтобы служебные ключи не пересылались на другой адрес. Тела ответов и тексты сетевых исключений не записываются в журнал.

Офлайн-проверки контрактов:

```sh
python -m unittest discover -s tests -p test_provider_apis.py
```

Тесты используют только фиктивные ключи и ответы HTTP. Для проверки подключения на VPS необходимы действующие ключи соответствующих кабинетов.

## Platega

Проверен опубликованный в PyPI сторонний SDK [platega==0.1.5](https://pypi.org/project/platega/0.1.5/), исходники [komarukomaru/platega](https://github.com/komarukomaru/platega): `client.py` (адрес `https://app.platega.io`, X-MerchantId/X-Secret, POST `/transaction/process`, GET `/transaction/{id}`), `models.py` (СБП=2, статус `CONFIRMED`, UUID, redirect, paymentDetails, payload). Это сторонний SDK, не доказательство доступности текущего боевого API.

Загруженная владельцем PDF «памятка почты.pdf» подтверждает `metadata.user_email` и постоянный Telegram ID в формате `ID@telegram.org` (правило на стр. 1; пример стр. 2 использует `@t.me`). Положения `paymentMethod` в SDK и примере PDF различаются; запрос содержит одинаковое значение 2 в обоих местах, без повторного POST или переключения API. Официальный сайт документации и страницы Telegra.ph были недоступны в среде (CONNECT 403). Рабочие ключи и реальные оплаченные счета не использовались. Подробности и настройка: [PLATEGA.md](PLATEGA.md).
