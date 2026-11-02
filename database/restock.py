"""Persistent, one-shot subscriptions to the next newly added stock."""
from uuid import uuid4

import aiomysql

from database.db import _get_pool


async def subscribe(user_id: int, slug: str) -> None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            # A repeated click preserves the existing subscription and its watermark.
            await cur.execute(
                "INSERT IGNORE INTO stock_subscriptions "
                "(user_id, category_slug, token, after_account_id) "
                "SELECT %s, %s, %s, COALESCE(MAX(id), 0) FROM accounts",
                (user_id, slug, uuid4().hex),
            )


async def unsubscribe(user_id: int, slug: str) -> None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM stock_subscriptions WHERE user_id = %s AND category_slug = %s",
                (user_id, slug),
            )


async def subscriptions(user_id: int) -> set[str]:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT category_slug FROM stock_subscriptions WHERE user_id = %s", (user_id,))
            return {row[0] for row in await cur.fetchall()}


async def pending_notifications() -> list[dict]:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(
                "SELECT s.user_id, s.category_slug, s.token, c.name "
                "FROM stock_subscriptions s JOIN categories c ON c.slug = s.category_slug "
                "WHERE c.is_active = 1 AND s.next_attempt_at <= NOW() "
                "AND EXISTS (SELECT 1 FROM accounts a WHERE a.country = s.category_slug "
                "AND a.status = 'available' AND a.id > s.after_account_id) "
                "ORDER BY s.next_attempt_at, s.user_id LIMIT 100"
            )
            return await cur.fetchall()


async def claim_notification(token: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            # The lease also prevents a failing recipient from starving the queue.
            await cur.execute(
                "UPDATE stock_subscriptions SET next_attempt_at = DATE_ADD(NOW(), INTERVAL 5 MINUTE) "
                "WHERE token = %s AND next_attempt_at <= NOW()",
                (token,),
            )
            return cur.rowcount > 0


async def finish_notification(token: str) -> None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            # A fresh subscription created during delivery must survive completion.
            await cur.execute("DELETE FROM stock_subscriptions WHERE token = %s", (token,))
