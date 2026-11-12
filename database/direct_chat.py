"""One private support conversation per user, with no tickets or statuses."""
import aiomysql
from database.db import _get_pool


async def init_schema(cur):
    await cur.execute('''CREATE TABLE IF NOT EXISTS direct_support_messages (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,user_id BIGINT NOT NULL,
        author_role VARCHAR(8) NOT NULL,body TEXT NOT NULL,
        created_at DATETIME NOT NULL,KEY conversation(user_id,id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4''')


async def append(user_id,role,body):
    if role not in {'user','admin'} or not isinstance(body,str) or not 1 <= len(body.strip()) <= 4000:
        raise ValueError('Сообщение должно содержать от 1 до 4000 символов.')
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute('INSERT INTO direct_support_messages(user_id,author_role,body,created_at) VALUES(%s,%s,%s,UTC_TIMESTAMP())',(user_id,role,body.strip()))
            return cur.lastrowid


async def history(user_id,before=0):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT id,author_role,body,created_at FROM direct_support_messages WHERE user_id=%s'+(' AND id<%s' if before else '')+' ORDER BY id DESC LIMIT 51',(user_id,before) if before else (user_id,))
            rows=list(await cur.fetchall())
            return {'items':list(reversed(rows[:50])),'has_more':len(rows)>50}


async def inbox():
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute('SELECT m.user_id,m.body,m.author_role,m.created_at,u.username FROM direct_support_messages m JOIN (SELECT user_id,MAX(id) AS last_id FROM direct_support_messages GROUP BY user_id) latest ON latest.last_id=m.id LEFT JOIN users u ON u.id=m.user_id ORDER BY m.id DESC LIMIT 100')
            return {'items':list(await cur.fetchall())}
