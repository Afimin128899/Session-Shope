"""Idempotently withdraw legacy unsold stock that no longer meets store rules."""
from utils.commerce_policy import category_allowed, require_stock


async def migrate(cur):
    await cur.execute('SELECT slug,name FROM categories')
    for item in await cur.fetchall():
        slug, name = (item['slug'], item['name']) if isinstance(item, dict) else item
        if not category_allowed(slug, name):
            await cur.execute('UPDATE categories SET is_active=0 WHERE slug=%s', (slug,))
    await cur.execute("SELECT a.id,a.country,a.number,a.price,c.name FROM accounts a LEFT JOIN categories c ON c.slug=a.country WHERE a.status='available' AND NOT EXISTS (SELECT 1 FROM purchases p WHERE p.account_id=a.id)")
    from database.admin_tools import _record
    for item in await cur.fetchall():
        row = item if isinstance(item, dict) else dict(zip(('id', 'country', 'number', 'price', 'category_name'), item))
        if isinstance(item, dict):
            row = {**row, 'category_name': row.get('name')}
        try:
            require_stock(row)
        except ValueError:
            # Never reprice silently, delete sessions, alter sold orders, or release reviews.
            await cur.execute("UPDATE accounts SET status='review',review_reason=%s,review_admin_id=0,review_started_at=UTC_TIMESTAMP(),spam_token=NULL,spam_lease_until=NULL WHERE id=%s AND status='available'", ('Ограничения магазина: проверьте страну аккаунта и цену (до 10 000 ₽).', row['id']))
            if cur.rowcount:
                await cur.execute('DELETE FROM account_reservations WHERE account_id=%s', (row['id'],))
                await cur.execute('DELETE FROM shopping_cart WHERE account_id=%s', (row['id'],))
                await _record(cur, 0, 'policy_review', 'account', row['id'], {'rule': 'country_or_price', 'after': 'review'})
