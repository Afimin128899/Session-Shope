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

async def listing():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT slug,name,emoji,is_active FROM categories WHERE slug LIKE 'section-%' ORDER BY is_active DESC,sort_order,name")
            return list(await cur.fetchall())
