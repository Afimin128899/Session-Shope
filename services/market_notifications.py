"""Durable opt-in price alerts and daily Moscow-time admin summaries."""
import asyncio
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
            await cur.execute('SELECT currency,COUNT(*) AS n,SUM(amount) AS total FROM payment_logs WHERE UNIX_TIMESTAMP(created_at)>=%s AND UNIX_TIMESTAMP(created_at)<%s GROUP BY currency', (int(start.timestamp()),int(end.timestamp())))
            deposits = list(await cur.fetchall())
            await cur.execute('SELECT currency,COUNT(*) AS n,SUM(amount) AS total FROM order_refunds WHERE created_at>=%s AND created_at<%s GROUP BY currency', (start.astimezone(timezone.utc).replace(tzinfo=None),end.astimezone(timezone.utc).replace(tzinfo=None)))
            refunds = list(await cur.fetchall())
            await cur.execute("SELECT COUNT(*) AS total,SUM(EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP())) AS reserved FROM accounts a JOIN categories c ON c.slug=a.country WHERE a.status='available' AND c.is_active=1")
            stock = await cur.fetchone()
    def lines(rows):
        return '\n'.join(f"• {r['n']} шт. / {Decimal(str(r['total'])):.2f} {escape(r['currency'])}" + (f" (без суммы: {r['unknown']})" if r.get('unknown') else '') for r in rows) or '• Нет'
    return (f'📊 <b>Sband ACCS · {day:%d.%m.%Y}</b>\nПериод: 00:00–24:00 МСК\n\n'
            f"Продажи (до возвратов):\n{lines(sales)}\n\nПополнения (без бонусов):\n{lines(deposits)}\n\nВозвраты:\n{lines(refunds)}\n\n"
            f"Сейчас в продаже: {stock['total'] or 0}\nИз них в резерве: {stock['reserved'] or 0}")


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
            await bot.send_message(item['user_id'],f"💚 Цена снизилась!\n{escape(item['name'])} · SBA-{item['account_id']:06d}\nНовая базовая цена: {item['price']:.2f} ₽. Личная скидка применяется в магазине.\n\nУбрать уведомления можно, удалив аккаунт из избранного.",parse_mode='HTML')
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
        except Exception:
            log.exception('Marketplace notification batch failed')
        await asyncio.sleep(60)
