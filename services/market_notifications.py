"""Durable opt-in price alerts and daily Moscow-time admin summaries."""
import asyncio
from utils.i18n import tr
from datetime import datetime, timedelta, time, timezone
from decimal import Decimal
from html import escape
import logging
from zoneinfo import ZoneInfo
import aiomysql
from config import ADMIN_IDS
from database.db import _get_pool

log = logging.getLogger(__name__)
MOSCOW = ZoneInfo('Europe/Moscow')


async def report(day):
    start = datetime.combine(day, time(), MOSCOW)
    end = start + timedelta(days=1)
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT currency,COUNT(*) AS n,COALESCE(SUM(paid_amount),0) AS total,SUM(paid_amount IS NULL) AS unknown FROM purchases WHERE date>=%s AND date<%s GROUP BY currency', (start.strftime('%Y-%m-%d %H:%M:%S'), end.strftime('%Y-%m-%d %H:%M:%S')))
            sales = list(await cur.fetchall())
            await cur.execute('SELECT currency,SUM(amount>0) AS n,SUM(amount) AS total FROM payment_logs WHERE UNIX_TIMESTAMP(created_at)>=%s AND UNIX_TIMESTAMP(created_at)<%s GROUP BY currency', (int(start.timestamp()), int(end.timestamp())))
            deposits = list(await cur.fetchall())
            await cur.execute('SELECT currency,COUNT(*) AS n,SUM(amount) AS total FROM order_refunds WHERE created_at>=%s AND created_at<%s GROUP BY currency', (start.astimezone(timezone.utc).replace(tzinfo=None), end.astimezone(timezone.utc).replace(tzinfo=None)))
            refunds = list(await cur.fetchall())
            await cur.execute("SELECT COUNT(*) AS total,SUM(EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP())) AS reserved FROM accounts a JOIN categories c ON c.slug=a.country WHERE a.status='available' AND c.is_active=1")
            stock = await cur.fetchone()

    def lines(rows):
        return '\n'.join((tr('• {0} шт. / {1} {2}', f"{r['n']}", f"{Decimal(str(r['total'])):.2f}", f"{escape(r['currency'])}") + (tr(' (без суммы: {0})', f"{r['unknown']}") if r.get('unknown') else '') for r in rows)) or tr('• Нет')
    return tr('📊 <b>Sband ACCS · {0}</b>\nПериод: 00:00–24:00 МСК\n\nПродажи (до возвратов):\n{1}\n\nПополнения (без бонусов, за вычетом возвратов Stars):\n{2}\n\nВозвраты:\n{3}\n\nСейчас в продаже: {4}\nИз них в резерве: {5}', f'{day:%d.%m.%Y}', f'{lines(sales)}', f'{lines(deposits)}', f'{lines(refunds)}', f"{stock['total'] or 0}", f"{stock['reserved'] or 0}")


async def send_reports(bot, now=None):
    now = now or datetime.now(MOSCOW)
    if now.hour < 9:
        return
    day = now.date() - timedelta(days=1)
    for admin in set(ADMIN_IDS):
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("INSERT IGNORE INTO daily_report_deliveries (admin_id,report_date,next_attempt_at) VALUES (%s,%s,UTC_TIMESTAMP())",(admin,day))
                await cur.execute("UPDATE daily_report_deliveries SET next_attempt_at=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 10 MINUTE) WHERE admin_id=%s AND report_date=%s AND status='pending' AND next_attempt_at<=UTC_TIMESTAMP()",(admin,day))
                claimed = cur.rowcount > 0
        if not claimed:
            continue
        try:
            from utils.notification_language import recipient_language
            async with recipient_language(admin):
                await bot.send_message(admin,await report(day),parse_mode='HTML')
        except Exception:
            log.warning('Daily admin report delivery deferred')
            continue
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("UPDATE daily_report_deliveries SET status='sent' WHERE admin_id=%s AND report_date=%s",(admin,day))


async def price_alerts(bot):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT f.token,f.user_id,f.account_id,a.price,c.name FROM account_favorites f JOIN accounts a ON a.id=f.account_id JOIN categories c ON c.slug=a.country WHERE a.status='available' AND c.is_active=1 AND a.price<f.last_price AND f.next_attempt_at<=UTC_TIMESTAMP() AND NOT EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>f.user_id) ORDER BY f.next_attempt_at LIMIT 25")
            items = list(await cur.fetchall())
    for item in items:
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('UPDATE account_favorites SET next_attempt_at=DATE_ADD(UTC_TIMESTAMP(),INTERVAL 5 MINUTE) WHERE token=%s AND next_attempt_at<=UTC_TIMESTAMP()', (item['token'],))
                claimed=cur.rowcount>0
        if not claimed:
            continue
        try:
            from utils.notification_language import send_translated
            await send_translated(bot,item['user_id'],"💚 Цена снизилась!\n{0} · SBA-{1}\nНовая базовая цена: {2} ₽. Личная скидка применяется в магазине.\n\nУбрать уведомления можно, удалив аккаунт из избранного.",escape(item['name']),f"{item['account_id']:06d}",f"{item['price']:.2f}",parse_mode='HTML')
        except Exception:
            log.warning('Price alert delivery deferred')
            continue
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute('UPDATE account_favorites SET last_price=%s WHERE token=%s',(item['price'],item['token']))
        await asyncio.sleep(.05)


async def market_worker(bot):
    while True:
        try:
            await price_alerts(bot)
            await send_reports(bot)
            from database.expansion import stock_notifications
            await stock_notifications(bot,ADMIN_IDS)
        except Exception:
            log.exception('Marketplace notification batch failed')
        await asyncio.sleep(60)
