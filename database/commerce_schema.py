"""Persistent carts, reservations, favorites, invoices and report delivery state."""
async def init_commerce_schema(cur, database_name):
    for column, definition in [('telegram_user_id', 'BIGINT DEFAULT NULL'), ('compare_price', 'DECIMAL(10,2) DEFAULT NULL')]:
        await cur.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s', (database_name, 'accounts', column))
        if not await cur.fetchone():
            await cur.execute(f'ALTER TABLE accounts ADD COLUMN {column} {definition}')
    for statement in (
        '''CREATE TABLE IF NOT EXISTS account_reservations (
            account_id INT PRIMARY KEY, user_id BIGINT NOT NULL,
            expires_at DATETIME NOT NULL, KEY reservation_user (user_id, expires_at),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS shopping_cart (
            user_id BIGINT NOT NULL, account_id INT NOT NULL, created_at DATETIME NOT NULL,
            PRIMARY KEY (user_id,account_id),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS account_favorites (
            user_id BIGINT NOT NULL, account_id INT NOT NULL, token CHAR(32) NOT NULL,
            last_price DECIMAL(18,8) NOT NULL, next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id,account_id), UNIQUE KEY favorite_token (token),
            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS payment_invoices (
            provider VARCHAR(16) NOT NULL, invoice_id VARCHAR(128) NOT NULL,
            user_id BIGINT NOT NULL, amount_rub DECIMAL(18,2) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending', credited_amount DECIMAL(18,2) DEFAULT NULL,
            created_at DATETIME NOT NULL, expires_at DATETIME NOT NULL,
            next_check_at DATETIME NOT NULL, attempts INT NOT NULL DEFAULT 0,
            PRIMARY KEY (provider,invoice_id), KEY invoice_queue (status,next_check_at),
            FOREIGN KEY (user_id) REFERENCES users(id)
        ) ENGINE=InnoDB''',
        '''CREATE TABLE IF NOT EXISTS daily_report_deliveries (
            admin_id BIGINT NOT NULL, report_date DATE NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            next_attempt_at DATETIME NOT NULL, PRIMARY KEY(admin_id,report_date)
        ) ENGINE=InnoDB''',
    ):
        await cur.execute(statement)
