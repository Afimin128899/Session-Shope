"""Repeatable schema changes for persistent orders and support conversations."""
async def init_support_schema(cur, database_name):
    for name, definition in (
        ('status', "VARCHAR(24) NOT NULL DEFAULT 'issued'"),
        ('paid_amount', 'DECIMAL(18, 8) DEFAULT NULL'),
        ('referrer_id', 'BIGINT DEFAULT NULL'),
        ('referral_bonus', 'DECIMAL(18, 8) DEFAULT NULL'),
    ):
        await cur.execute(
            'SELECT COLUMN_NAME FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s',
            (database_name, 'purchases', name),
        )
        if not await cur.fetchone():
            await cur.execute(f'ALTER TABLE purchases ADD COLUMN {name} {definition}')
    # Repeatable even if a previous run stopped after ALTER TABLE.
    await cur.execute(
        "UPDATE purchases p JOIN accounts a ON a.id = p.account_id "
        "SET p.status = 'completed' WHERE p.status = 'issued' "
        "AND a.data = '✅ Сессия удалена (Покупка завершена)'"
    )
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS support_tickets (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            purchase_id INT DEFAULT NULL,
            user_id BIGINT NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'open',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            UNIQUE KEY support_order (purchase_id),
            KEY support_user (user_id, id),
            KEY support_queue (status, id),
            CONSTRAINT support_order_fk FOREIGN KEY (purchase_id)
                REFERENCES purchases(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB
    """)
    await cur.execute("SELECT IS_NULLABLE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME='support_tickets' AND COLUMN_NAME='purchase_id'", (database_name,))
    column = await cur.fetchone()
    nullable = column.get('IS_NULLABLE') if isinstance(column,dict) else column[0] if column else 'YES'
    if nullable == 'NO':
        await cur.execute('ALTER TABLE support_tickets MODIFY purchase_id INT DEFAULT NULL')
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS support_messages (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            ticket_id BIGINT NOT NULL,
            author_id BIGINT NOT NULL,
            author_role VARCHAR(16) NOT NULL,
            body VARCHAR(500) NOT NULL,
            created_at DATETIME NOT NULL,
            KEY support_history (ticket_id, id),
            CONSTRAINT support_message_ticket_fk FOREIGN KEY (ticket_id)
                REFERENCES support_tickets(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB
    """)
    await cur.execute("""
        CREATE TABLE IF NOT EXISTS order_refunds (
            purchase_id INT PRIMARY KEY,
            admin_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            amount DECIMAL(18, 8) NOT NULL,
            currency VARCHAR(16) NOT NULL,
            reason VARCHAR(500) NOT NULL,
            referral_reversed DECIMAL(18, 8) NOT NULL DEFAULT 0,
            legacy_referral TINYINT(1) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            CONSTRAINT refund_order_fk FOREIGN KEY (purchase_id)
                REFERENCES purchases(id) ON DELETE RESTRICT
        ) ENGINE=InnoDB
    """)
