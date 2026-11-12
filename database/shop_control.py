"""Inventory review and sales controls shared by every checkout entry point."""
from utils.i18n import tr
from html import escape

from database.admin_tools import _transaction, _record

DEFAULT_REASON = 'Обновляем магазин и проверяем работу сервисов.'
DEFAULT_SALES_REASON = 'Обновляем ассортимент. Покупки снова откроются после проверки.'


async def init_schema(cur, database):
    for table, fields in {
        'accounts': [('review_reason', 'VARCHAR(500) DEFAULT NULL'),
                     ('review_admin_id', 'BIGINT DEFAULT NULL'), ('review_started_at', 'DATETIME DEFAULT NULL')],
        'users': [('language', "VARCHAR(2) NOT NULL DEFAULT 'ru'")],
    }.items():
        for field, definition in fields:
            await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database, table, field))
            if not await cur.fetchone():
                await cur.execute(f'ALTER TABLE {table} ADD COLUMN {field} {definition}')
    for key, value in [('platega_stub', '1'), ('sales_paused', '0'), ('sales_pause_reason', DEFAULT_SALES_REASON),
                       ('maintenance_reason', DEFAULT_REASON), ('maintenance_eta', 'Время завершения пока уточняется.')]:
        await cur.execute('INSERT IGNORE INTO settings(`key`,`value`) VALUES(%s,%s)', (key, value))

    from database.sales_policy import migrate
    await migrate(cur)


async def set_review(admin, account, enabled, reason):
    if type(account) is not int or account <= 0 or type(enabled) is not bool:
        raise ValueError(tr('Некорректный товар.'))
    if not isinstance(reason, str) or not 3 <= len(reason.strip()) <= 500:
        raise ValueError(tr('Укажите причину: 3–500 символов.'))
    reason = reason.strip()
    async with _transaction() as cur:
        await cur.execute('SELECT id,status,review_reason FROM accounts WHERE id=%s FOR UPDATE', (account,))
        row = await cur.fetchone()
        expected, target = ('available', 'review') if enabled else ('review', 'available')
        if not row or row['status'] != expected:
            raise ValueError(tr('Статус товара уже изменился. Обновите карточку.'))
        await cur.execute('SELECT id FROM purchases WHERE account_id=%s LIMIT 1', (account,))
        if await cur.fetchone():
            raise ValueError(tr('Проданный аккаунт нельзя отправить на проверку или вернуть в продажу.'))
        if not enabled:
            from utils.commerce_policy import checkout
            await checkout(cur, [account])
        await cur.execute('DELETE FROM account_reservations WHERE account_id=%s', (account,))
        await cur.execute('DELETE FROM shopping_cart WHERE account_id=%s', (account,))
        await cur.execute('UPDATE accounts SET status=%s,review_reason=%s,review_admin_id=%s,\n            review_started_at=CASE WHEN %s THEN UTC_TIMESTAMP() ELSE NULL END,\n            spam_token=NULL,spam_lease_until=NULL,spam_requested=0,spam_next_check_at=UTC_TIMESTAMP()\n            WHERE id=%s', (target, reason if enabled else None, admin if enabled else None, enabled, account))
        await _record(cur, admin, 'account_review' if enabled else 'account_release', 'account', account, {'before': expected, 'after': target, 'reason': reason, 'previous_reason': row.get('review_reason')})
        return target


async def check_sales(cur, *, tuple_cursor=False, account_ids=None):
    """Lock the switch after inventory, before balances. The admin toggle waits for buyers.

    Shared locks allow unrelated purchases concurrently. Pausing obtains an exclusive
    lock on the same setting: after the toggle commits no checkout can debit a wallet.
    Do not bypass for administrators; the isolated demo store is independent.
    """
    if account_ids:
        from utils.commerce_policy import checkout
        try:
            await checkout(cur, account_ids, tuple_cursor=tuple_cursor)
        except ValueError as exc:
            from miniapp.storage import CheckoutError
            raise CheckoutError(str(exc), 'restricted_stock') from None
    await cur.execute("SELECT `value` FROM settings WHERE `key`='sales_paused' LOCK IN SHARE MODE")
    row = await cur.fetchone()
    value = (row[0] if tuple_cursor else row.get('value')) if row else '0'
    if value == '1':
        from miniapp.storage import CheckoutError
        raise CheckoutError(tr('⏸ Продажи временно приостановлены. Покупки, коды входа и поддержка доступны.'), 'sales_paused')


def public_status(settings):
    defaults = {'maintenance_reason': DEFAULT_REASON, 'maintenance_eta': 'Время завершения пока уточняется.', 'sales_pause_reason': DEFAULT_SALES_REASON}
    def notice(key):
        value = settings.get(key) or defaults[key]
        # Translate only our built-in notices. Operator-written text stays intact.
        return tr(value) if value == defaults[key] else value
    return {'maintenance': settings.get('maintenance_mode') == '1', 'sales_paused': settings.get('sales_paused') == '1',
            'reason': notice('maintenance_reason'), 'eta': notice('maintenance_eta'), 'sales_reason': notice('sales_pause_reason')}


def maintenance_message(settings):
    from utils.i18n import LANGUAGE
    from utils.interface_emojis import html_icon
    state = public_status(settings)
    if LANGUAGE.get() == 'en':
        return (f'{html_icon("tools")} <b>Maintenance</b>\nThe store is temporarily unavailable.\n\n'
                f'<b>What we are doing</b>\n<blockquote>{escape(state["reason"])}</blockquote>\n\n'
                f'{html_icon("clock")} <b>Expected completion</b>\n{escape(state["eta"])}\nThe time is an estimate and may change.\n\n'
                '<b>Your balance and purchases are preserved.</b> Confirmed payments continue to be processed automatically; you do not need to pay the same invoice again.\n\n'
                'Support remains available. Tap “Check status” to refresh this notice.').strip()
    return (f'{html_icon("tools")} <b>Технические работы</b>\nМагазин временно недоступен.\n\n'
            f'<b>Что делаем</b>\n<blockquote>{escape(state["reason"])}</blockquote>\n\n'
            f'{html_icon("clock")} <b>Ориентир завершения</b>\n{escape(state["eta"])}\nСрок ориентировочный и может измениться.\n\n'
            '<b>Баланс и покупки сохранены.</b> Подтверждённые оплаты продолжают обрабатываться автоматически. Повторно оплачивать тот же счёт не нужно.\n\n'
            'Поддержка остаётся на связи. Нажмите «Проверить статус», чтобы обновить информацию.').strip()
