"""Public product departments; switching readiness reuses category administration."""
import aiomysql
from database.db import _get_pool

DEPARTMENTS = [('email','Почта','✉'),('gmail','Gmail','M'),('chatgpt','ChatGPT','◎'),
               ('roblox','Roblox','◇'),('discord','Discord','◉'),('steam','Steam','S'),
               ('spotify','Spotify','♫'),('youtube','YouTube','▶')]

async def seed(cur):
    await cur.execute("INSERT IGNORE INTO settings(`key`,`value`) VALUES('product_departments_v1','1')")
    if cur.rowcount != 1:
        return
    for slug,name,icon in DEPARTMENTS:
        await cur.execute('INSERT IGNORE INTO categories(slug,name,emoji,is_active) VALUES(%s,%s,%s,0)', ('section-'+slug,name,icon))

async def listing(user_id=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT c.slug,c.name,c.emoji,c.is_active,COUNT(a.id) AS count FROM categories c LEFT JOIN accounts a ON a.country=c.slug AND a.status='available' AND NOT EXISTS(SELECT 1 FROM account_reservations r WHERE r.account_id=a.id AND r.expires_at>UTC_TIMESTAMP() AND r.user_id<>%s) WHERE c.slug LIKE 'section-%%' GROUP BY c.slug,c.name,c.emoji,c.is_active,c.sort_order ORDER BY c.is_active DESC,COUNT(a.id) DESC,c.sort_order,c.name", (user_id,))
            return list(await cur.fetchall())


def stock_label(count):
    from utils.i18n import tr,LANGUAGE
    count=int(count or 0)
    if LANGUAGE.get()=='en':return tr('{0} товар' if count==1 else '{0} товаров',count)
    word='товар' if count%10==1 and count%100!=11 else 'товара' if count%10 in {2,3,4} and count%100 not in {12,13,14} else 'товаров'
    return f'{count} {word}'
