import aiomysql 
import logging 
import warnings
from contextlib import asynccontextmanager
from config import DB_CONFIG, TONKEEPER_WALLET, RUB_DETAILS, REVIEWS_LINK, SUPPORT_USERNAME

class PoolWrapper:
    """Обертка над aiomysql.Pool для автоматической проверки (ping) и реконнекта сокетов при получении соединения."""

    def __init__(self, raw_pool: aiomysql.Pool):
        self._pool = raw_pool

    @asynccontextmanager
    async def acquire(self):
        async with self._pool.acquire() as conn:
            try:
                await conn.ping(reconnect=True)
            except Exception as ping_err:
                logging.warning(f"[db] Connection ping failed during acquire: {ping_err}")
            yield conn

    def close(self):
        self._pool.close()

    async def wait_closed(self):
        await self._pool.wait_closed()

    def __getattr__(self, name):
        return getattr(self._pool, name)

pool = None 

def _get_pool():
    if pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_db() first.")
    return pool

async def init_db ():
    global pool 
    try :
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=Warning)

            conn = await aiomysql.connect(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password']
            )
            async with conn.cursor() as cur:
                db_name = DB_CONFIG['db'].replace('`', '``')
                await cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` COLLATE utf8mb4_unicode_ci")
            conn.close()

            raw_pool = await aiomysql.create_pool(
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                db=DB_CONFIG['db'],
                autocommit=True,
                minsize=1,
                maxsize=20,
                pool_recycle=300
            )
            pool = PoolWrapper(raw_pool)

            async with _get_pool().acquire() as conn :
                async with conn .cursor ()as cur :

                    await cur .execute ('''
                        CREATE TABLE IF NOT EXISTS users (
                            id BIGINT PRIMARY KEY,
                            balance DECIMAL(18, 8) DEFAULT 0.00000000
                        )
                    ''')

                    # Безопасная миграция: меняем тип только если колонка ещё не DECIMAL(18,8)
                    try:
                        await cur.execute(
                            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'balance'",
                            (DB_CONFIG['db'],)
                        )
                        col_row = await cur.fetchone()
                        if col_row and 'decimal(18,8)' not in str(col_row[0]).lower():
                            await cur.execute(
                                'ALTER TABLE users MODIFY COLUMN balance DECIMAL(18, 8) DEFAULT 0.00000000'
                            )
                    except Exception as alter_err:
                        logging.warning(f"[db] ALTER TABLE users skipped: {alter_err}")

                    # Безопасная миграция: добавляем balance_usdt, если её нет
                    try:
                        await cur.execute(
                            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'balance_usdt'",
                            (DB_CONFIG['db'],)
                        )
                        col_row = await cur.fetchone()
                        if not col_row:
                            await cur.execute(
                                'ALTER TABLE users ADD COLUMN balance_usdt DECIMAL(18, 8) DEFAULT 0.00000000'
                            )
                    except Exception as alter_err:
                        logging.warning(f"[db] ALTER TABLE users ADD COLUMN balance_usdt skipped: {alter_err}")

                    # Безопасная миграция: флаг использования бонуса за первое пополнение
                    try:
                        await cur.execute(
                            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'first_deposit_bonus_used'",
                            (DB_CONFIG['db'],)
                        )
                        if not await cur.fetchone():
                            await cur.execute(
                                "ALTER TABLE users ADD COLUMN first_deposit_bonus_used TINYINT(1) NOT NULL DEFAULT 0"
                            )
                    except Exception as alter_err:
                        logging.warning(f"[db] ALTER TABLE users ADD COLUMN first_deposit_bonus_used skipped: {alter_err}")

                    # Безопасная миграция: добавляем username, если её нет
                    try:
                        await cur.execute(
                            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'users' AND COLUMN_NAME = 'username'",
                            (DB_CONFIG['db'],)
                        )
                        col_row = await cur.fetchone()
                        if not col_row:
                            await cur.execute(
                                'ALTER TABLE users ADD COLUMN username VARCHAR(255) DEFAULT NULL'
                            )
                    except Exception as alter_err:
                        logging.warning(f"[db] ALTER TABLE users ADD COLUMN username skipped: {alter_err}")

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS referrals (
                            referral_id BIGINT PRIMARY KEY,
                            referrer_id BIGINT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            FOREIGN KEY (referral_id) REFERENCES users(id),
                            FOREIGN KEY (referrer_id) REFERENCES users(id)
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS referral_settings (
                            id INT PRIMARY KEY DEFAULT 1,
                            discount_pct DECIMAL(5,2) DEFAULT 5.00,
                            bonus_pct DECIMAL(5,2) DEFAULT 5.00
                        )
                    ''')
                    await cur.execute('INSERT IGNORE INTO referral_settings (id) VALUES (1)')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS button_labels (
                            btn_key VARCHAR(64) PRIMARY KEY,
                            label VARCHAR(255) NOT NULL,
                            emoji_id VARCHAR(64) DEFAULT NULL
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS categories (
                            slug VARCHAR(64) PRIMARY KEY,
                            name VARCHAR(255) NOT NULL,
                            emoji VARCHAR(255) DEFAULT NULL,
                            is_active TINYINT(1) DEFAULT 1,
                            sort_order INT DEFAULT 0,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS accounts (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            country VARCHAR(255),
                            code VARCHAR(50),
                            number VARCHAR(255),
                            password VARCHAR(255),
                            price DECIMAL(10, 2),
                            data TEXT,
                            status VARCHAR(50) DEFAULT 'available'
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS purchases (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT,
                            account_id INT,
                            date VARCHAR(255),
                            currency VARCHAR(16) DEFAULT 'TON',
                            FOREIGN KEY (user_id) REFERENCES users(id),
                            FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
                        )
                    ''')

                    # Безопасная миграция: добавляем currency в purchases, если её нет
                    try:
                        await cur.execute(
                            "SELECT COLUMN_TYPE FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'purchases' AND COLUMN_NAME = 'currency'",
                            (DB_CONFIG['db'],)
                        )
                        col_row = await cur.fetchone()
                        if not col_row:
                            await cur.execute(
                                "ALTER TABLE purchases ADD COLUMN currency VARCHAR(16) DEFAULT 'TON'"
                            )
                    except Exception as alter_err:
                        logging.warning(f"[db] ALTER TABLE purchases ADD COLUMN currency skipped: {alter_err}")

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS promocodes (
                            code VARCHAR(255) PRIMARY KEY,
                            value DECIMAL(10, 2),
                            uses INT DEFAULT 0,
                            max_uses INT
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS used_promos (
                            user_id BIGINT,
                            code VARCHAR(255),
                            PRIMARY KEY (user_id, code)
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS broadcast_logs (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            admin_id BIGINT,
                            created_at VARCHAR(255),
                            total_users INT,
                            success INT,
                            failed INT,
                            note TEXT
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS used_transactions (
                            comment VARCHAR(255) PRIMARY KEY,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS payment_logs (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            user_id BIGINT NOT NULL,
                            amount DECIMAL(18, 8) NOT NULL,
                            currency VARCHAR(16) NOT NULL,
                            method VARCHAR(32) NOT NULL,
                            reference VARCHAR(255) DEFAULT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    ''')

                    await cur.execute('''
                        CREATE TABLE IF NOT EXISTS settings (
                            `key` VARCHAR(64) PRIMARY KEY,
                            `value` TEXT NOT NULL
                        )
                    ''')

                    # Создание индексов для ускорения выборки и защиты от нагрузок
                    indexes = [
                        ("accounts", "idx_accounts_status_country", "status, country"),
                        ("accounts", "idx_accounts_status", "status"),
                        ("purchases", "idx_purchases_user_id", "user_id"),
                        ("purchases", "idx_purchases_account_id", "account_id"),
                        ("referrals", "idx_referrals_referrer_id", "referrer_id"),
                        ("payment_logs", "idx_payment_logs_user_id", "user_id"),
                        ("categories", "idx_categories_active_sort", "is_active, sort_order"),
                        ("users", "idx_users_username", "username"),
                    ]
                    for table_name, index_name, columns_sql in indexes:
                        try:
                            await cur.execute(
                                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND INDEX_NAME = %s",
                                (DB_CONFIG['db'], table_name, index_name)
                            )
                            idx_row = await cur.fetchone()
                            if not idx_row or idx_row[0] == 0:
                                await cur.execute(f"CREATE INDEX `{index_name}` ON `{table_name}` ({columns_sql})")
                                logging.info(f"[db] Created index {index_name} on {table_name}")
                        except Exception as idx_err:
                            logging.warning(f"[db] Failed to create index {index_name} on {table_name}: {idx_err}")

                    # Seed default categories if categories table is empty
                    try:
                        await cur.execute("SELECT COUNT(*) FROM categories")
                        cat_row = await cur.fetchone()
                        if not cat_row or cat_row[0] == 0:
                            default_cats = [
                                ("ru", "Россия 🇷🇺", "5258509201306557640"),
                                ("kz", "Казахстан 🇰🇿", "5258509201306557640"),
                                ("us", "США 🇺🇸", "5258509201306557640"),
                                ("id", "Индонезия 🇮🇩", "5258509201306557640"),
                                ("uz", "Узбекистан 🇺🇿", "5258509201306557640"),
                                ("de", "Германия 🇩🇪", "5258509201306557640"),
                            ]
                            for c_slug, c_name, c_emoji in default_cats:
                                await cur.execute(
                                    "INSERT IGNORE INTO categories (slug, name, emoji, is_active) VALUES (%s, %s, %s, 1)",
                                    (c_slug, c_name, c_emoji)
                                )
                    except Exception as cat_err:
                        logging.warning(f"[db] Failed to seed default categories: {cat_err}")

                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS admin_audit_log (
                            id BIGINT AUTO_INCREMENT PRIMARY KEY,
                            admin_id BIGINT NOT NULL,
                            action VARCHAR(32) NOT NULL,
                            target_type VARCHAR(16) NOT NULL,
                            target_id VARCHAR(64) NOT NULL,
                            details TEXT NOT NULL,
                            created_at DATETIME NOT NULL,
                            KEY admin_audit_actor (admin_id, id)
                        ) ENGINE=InnoDB
                    """)

                    from database.support_schema import init_support_schema
                    await init_support_schema(cur, DB_CONFIG["db"])
                    from database.commerce_schema import init_commerce_schema
                    await init_commerce_schema(cur, DB_CONFIG["db"])
                    from database.quality import init_schema as init_quality_schema
                    await init_quality_schema(cur, DB_CONFIG["db"])

                    await cur.execute("""
                        CREATE TABLE IF NOT EXISTS stock_subscriptions (
                            user_id BIGINT NOT NULL,
                            category_slug VARCHAR(64) NOT NULL,
                            token CHAR(32) NOT NULL,
                            after_account_id INT NOT NULL DEFAULT 0,
                            next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            PRIMARY KEY (user_id, category_slug),
                            UNIQUE KEY stock_subscription_token (token),
                            KEY stock_notification_queue (next_attempt_at),
                            CONSTRAINT stock_subscriptions_category_fk FOREIGN KEY (category_slug)
                                REFERENCES categories(slug) ON DELETE CASCADE
                        ) ENGINE=InnoDB
                    """)

                    await cur.execute(
                        "INSERT IGNORE INTO settings (`key`, `value`) VALUES (%s, %s), (%s, %s), (%s, %s), (%s, %s)",
                        ("reviews_link", REVIEWS_LINK or "https://t.me", 
                         "tonkeeper_wallet", TONKEEPER_WALLET or "Не задан", 
                         "rub_details", RUB_DETAILS or "Реквизиты уточняйте у администратора",
                         "support_username", SUPPORT_USERNAME or "Не задана")
                    )
        logging.info("--- Database Init Success ---")
    except Exception as e:
        if pool is not None:
            pool.close()
            await pool.wait_closed()
            pool = None
        logging.error(f"Critical DB Error: {e}")
        raise


async def get_user(user_id: int):
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
            return await cur.fetchone()


async def get_user_by_username(username: str):
    clean_username = username.lstrip("@").strip().lower()
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM users WHERE LOWER(username) = %s", (clean_username,))
            return await cur.fetchone()


async def update_user_username(user_id: int, username: str | None):
    clean_username = username.lstrip("@").strip() if username else None
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE users SET username = %s WHERE id = %s", (clean_username, user_id))


async def create_user(user_id: int, username: str | None = None):
    clean_username = username.lstrip("@").strip() if username else None
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO users (id, balance, balance_usdt, username) VALUES (%s, 0, 0, %s) "
                "ON DUPLICATE KEY UPDATE username = IF(%s IS NOT NULL AND %s != '', %s, username)",
                (user_id, clean_username, clean_username, clean_username, clean_username)
            )

async def add_balance (user_id :int ,amount :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE users SET balance = balance + %s WHERE id = %s",(amount ,user_id ))


async def add_deposit_with_first_bonus(user_id: int, amount: float) -> tuple[float, float]:
    """Зачисляет пополнение и одноразовый бонус 10% за первое пополнение."""
    amount = round(float(amount), 2)
    if amount <= 0:
        return 0.0, 0.0

    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            bonus = round(amount * 0.10, 2)
            await cur.execute(
                "UPDATE users SET balance = balance + %s, first_deposit_bonus_used = 1 "
                "WHERE id = %s AND first_deposit_bonus_used = 0",
                (amount + bonus, user_id),
            )
            if cur.rowcount > 0:
                return amount + bonus, bonus

            await cur.execute(
                "UPDATE users SET balance = balance + %s WHERE id = %s",
                (amount, user_id),
            )
            return amount, 0.0

async def credit_paid_deposit(
    user_id: int, amount, provider: str, invoice_id: str,
) -> tuple[float, float] | None:
    """Зачисляет платёж, бонус и запись в журнале одной транзакцией.

    None означает, что этот счёт уже зачислен. При ошибке маркер платежа
    тоже откатывается, поэтому проверку можно безопасно повторить.
    """
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

    try:
        amount = Decimal(str(amount))
        if not amount.is_finite() or not Decimal("10") <= amount <= Decimal("1000000"):
            raise ValueError("Invalid deposit amount")
        amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Invalid deposit amount") from exc
    if provider not in {"lave", "xrocket", "crypto"} or not invoice_id:
        raise ValueError("Invalid payment reference")
    comment_key = f"{provider}_{invoice_id}"
    if len(comment_key) > 255:
        raise ValueError("Payment reference is too long")

    async with _get_pool().acquire() as conn:
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                try:
                    await cur.execute(
                        "INSERT INTO used_transactions (comment) VALUES (%s)",
                        (comment_key,),
                    )
                except aiomysql.IntegrityError as exc:
                    if exc.args[0] != 1062:
                        raise
                    await conn.rollback()
                    return None
                await cur.execute(
                    "SELECT first_deposit_bonus_used FROM users WHERE id = %s FOR UPDATE",
                    (user_id,),
                )
                user = await cur.fetchone()
                if user is None:
                    raise ValueError("Deposit user does not exist")
                bonus = (
                    (amount * Decimal("0.10")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    if not user[0] else Decimal("0.00")
                )
                credited = amount + bonus
                await cur.execute(
                    "UPDATE users SET balance = balance + %s, first_deposit_bonus_used = 1 WHERE id = %s",
                    (credited, user_id),
                )
                await cur.execute(
                    "INSERT INTO payment_logs (user_id, amount, currency, method, reference) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (user_id, amount, "RUB", f"{provider}_pay", str(invoice_id)),
                )
            await conn.commit()
            return float(credited), float(bonus)
        except BaseException:
            # Cancellation must not return a connection with an open transaction.
            await conn.rollback()
            raise


async def add_balance_usdt (user_id :int ,amount :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE users SET balance_usdt = balance_usdt + %s WHERE id = %s",(amount ,user_id ))

async def set_user_balance (user_id :int ,amount :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE users SET balance = %s WHERE id = %s",(amount ,user_id ))

async def set_user_balance_usdt (user_id :int ,amount :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE users SET balance_usdt = %s WHERE id = %s",(amount ,user_id ))


async def get_all_users ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM users ORDER BY id DESC")
            return await cur .fetchall ()


async def get_users_with_balance ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM users WHERE balance > 0 OR balance_usdt > 0 ORDER BY balance DESC, balance_usdt DESC")
            return await cur .fetchall ()


async def get_available_countries ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("""
                SELECT country, code, COUNT(id) as count, MIN(price) as min_price 
                FROM accounts WHERE status = 'available' GROUP BY country, code
            """)
            return await cur .fetchall ()

async def get_accounts_by_country (country :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            if country =="all":
                await cur .execute ("SELECT * FROM accounts ORDER BY id DESC")
            else :
                await cur .execute ("SELECT * FROM accounts WHERE country = %s AND status = 'available'",(country ,))
            return await cur .fetchall ()

async def get_account (account_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM accounts WHERE id = %s",(account_id ,))
            return await cur .fetchone ()


async def get_account_by_number (number :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM accounts WHERE number = %s",(number ,))
            return await cur .fetchone ()

async def get_first_available_account_by_country (country :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute (
            "SELECT * FROM accounts WHERE country = %s AND status = 'available' ORDER BY id ASC LIMIT 1",
            (country ,)
            )
            return await cur .fetchone ()


async def buy_account(user_id: int, account_id: int, price: float, date_str: str, currency: str = "TON"):
    async with _get_pool().acquire() as conn:
        await conn.autocommit(False)
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                # Блокируем аккаунт и проверяем статус
                await cur.execute(
                    "SELECT id, status FROM accounts WHERE id = %s AND status = 'available' AND (spam_lease_until IS NULL OR spam_lease_until<=UTC_TIMESTAMP()) FOR UPDATE",
                    (account_id,)
                )
                acc_row = await cur.fetchone()
                if not acc_row:
                    await conn.rollback()
                    return None

                await cur.execute("SELECT user_id FROM account_reservations WHERE account_id = %s AND expires_at > UTC_TIMESTAMP() FOR UPDATE", (account_id,))
                reservation = await cur.fetchone()
                if reservation and reservation[0] != user_id:
                    await conn.rollback()
                    return None

                # Проверяем баланс с блокировкой строки
                balance_col = "balance_usdt" if currency == "USDT" else "balance"
                await cur.execute(f"SELECT {balance_col} FROM users WHERE id = %s FOR UPDATE", (user_id,))
                row = await cur.fetchone()
                if not row or float(row[0]) < price:
                    await conn.rollback()
                    return None

                await cur.execute(f"UPDATE users SET {balance_col} = {balance_col} - %s WHERE id = %s", (price, user_id))
                await cur.execute("UPDATE accounts SET status = 'sold' WHERE id = %s", (account_id,))
                await cur.execute("INSERT INTO purchases (user_id, account_id, date, currency, paid_amount, referral_bonus) VALUES (%s, %s, %s, %s, %s, 0)", (user_id, account_id, date_str, currency, price))
                purc_id = cur.lastrowid
                from database.quality import snapshot
                await snapshot(cur, purc_id)
                await cur.execute("DELETE FROM shopping_cart WHERE user_id = %s AND account_id = %s", (user_id, account_id))
                await cur.execute("DELETE FROM account_reservations WHERE account_id = %s", (account_id,))
            await conn.commit()
            logging.info(f"[db] Purchase completed: user={user_id}, account={account_id}, price={price} {currency}, purchase_id={purc_id}")
            return purc_id
        except Exception as e:
            await conn.rollback()
            logging.error(f"[db] buy_account error: {e}")
            return None
        finally:
            await conn.autocommit(True)


async def get_user_purchases (user_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("""
                SELECT p.id, p.account_id, a.country, a.number, a.password, a.data, p.date, p.currency, p.status, p.paid_amount, t.status AS ticket_status
                FROM purchases p JOIN accounts a ON p.account_id = a.id
                LEFT JOIN support_tickets t ON t.purchase_id = p.id
                WHERE p.user_id = %s ORDER BY p.id DESC
            """,(user_id ,))
            return await cur .fetchall ()

async def get_purchase_for_user (purchase_id :int ,user_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("""
                SELECT p.*, a.country, a.code, a.number, a.password, a.data, a.price, a.telegram_user_id, t.status AS ticket_status
                FROM purchases p JOIN accounts a ON p.account_id = a.id
                LEFT JOIN support_tickets t ON t.purchase_id = p.id
                WHERE p.id = %s AND p.user_id = %s
            """,(purchase_id ,user_id ))
            return await cur .fetchone ()

async def complete_user_purchase(account_id: int):
    from database.admin_tools import _transaction
    async with _transaction() as cur:
        await cur.execute("UPDATE purchases SET status = 'completed' WHERE account_id = %s AND status <> 'refunded'", (account_id,))
        await cur.execute("UPDATE accounts SET data = '✅ Сессия удалена (Покупка завершена)' WHERE id = %s AND status <> 'refunded'", (account_id,))


async def add_account(country, code, number, password, price, data, telegram_user_id=None, is_premium=None):
    from database.admin_tools import _transaction
    from database.imports import claim, bind
    async with _transaction() as cur:
        keys = await claim(cur, number, telegram_user_id, data)
        await cur.execute("INSERT INTO accounts(country,code,number,password,price,data,telegram_user_id,warranty_hours,is_premium,attributes_checked_at) VALUES(%s,%s,%s,%s,%s,%s,%s,24,%s,UTC_TIMESTAMP())", (country,code,number,password,price,data,telegram_user_id,is_premium))
        await bind(cur, keys, cur.lastrowid)

async def delete_account (account_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("DELETE FROM purchases WHERE account_id = %s",(account_id ,))
            await cur .execute ("DELETE FROM accounts WHERE id = %s",(account_id ,))

async def update_account_country(account_id: int, new_country: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not await cur.fetchone():
                return False
            await cur.execute("UPDATE accounts SET country = %s WHERE id = %s", (new_country, account_id))
            return True

async def update_account_price(account_id: int, new_price: float) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not await cur.fetchone():
                return False
            await cur.execute("UPDATE accounts SET price = %s WHERE id = %s", (new_price, account_id))
            return True

async def create_promo (code ,value ,max_uses ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("REPLACE INTO promocodes (code, value, max_uses) VALUES (%s, %s, %s)",(code ,value ,max_uses ))

async def get_all_promocodes ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM promocodes")
            return await cur .fetchall ()

async def delete_promo (code :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :

            await cur .execute ("DELETE FROM promocodes WHERE code = %s",(code ,))

            await cur .execute ("DELETE FROM used_promos WHERE code = %s",(code ,))

async def check_and_use_promo(user_id: int, code: str) -> float:
    from database.coupons import redeem_balance
    try:
        return float(await redeem_balance(user_id, code))
    except ValueError:
        return 0.0

async def update_country_price (country :str ,new_price :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE accounts SET price = %s WHERE country = %s AND status = 'available'",(new_price ,country ))
            return cur .rowcount 

async def log_broadcast (admin_id :int ,created_at :str ,total_users :int ,success :int ,failed :int ,note :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("""
                INSERT INTO broadcast_logs (admin_id, created_at, total_users, success, failed, note)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,(admin_id ,created_at ,total_users ,success ,failed ,note ))

async def get_stats ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT COUNT(id) as total, SUM(balance) as bal, SUM(balance_usdt) as bal_usdt FROM users")
            u =await cur .fetchone ()
            await cur .execute ("SELECT COUNT(id) as cnt, SUM(price) as val FROM accounts WHERE status = 'available'")
            a =await cur .fetchone ()
            await cur .execute ("SELECT COUNT(id) as sold FROM accounts WHERE status = 'sold'")
            s =await cur .fetchone ()

            await cur .execute ("""
                SELECT COUNT(p.id) as purc, SUM(COALESCE(p.paid_amount, acc.price)) as rev
                FROM purchases p 
                JOIN accounts acc ON p.account_id = acc.id
                WHERE p.status <> 'refunded'
            """)
            p_res =await cur .fetchone ()

            await cur .execute ("SELECT COUNT(code) as promos FROM promocodes")
            pr =await cur .fetchone ()
            return {
            "users":u ['total']or 0 ,"total_balance":u ['bal']or 0.0 ,"total_balance_usdt":u ['bal_usdt']or 0.0 ,
            "accounts_available":a ['cnt']or 0 ,"accounts_value":a ['val']or 0.0 ,
            "accounts_sold":s ['sold']or 0 ,"revenue":p_res ['rev']or 0.0 ,
            "purchases":p_res ['purc']or 0 ,"promos":pr ['promos']or 0 
            }


async def is_comment_used (comment :str )->bool :
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("SELECT comment FROM used_transactions WHERE comment = %s",(comment ,))
            return await cur .fetchone ()is not None 

async def mark_comment_used (comment :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("INSERT IGNORE INTO used_transactions (comment) VALUES (%s)",(comment ,))

async def try_mark_comment_used(comment: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT IGNORE INTO used_transactions (comment) VALUES (%s)", (comment,)
            )
            return cur.rowcount > 0


async def log_payment(user_id: int, amount: float, currency: str, method: str, reference: str = None):
    try:
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO payment_logs (user_id, amount, currency, method, reference) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, amount, currency, method, reference),
                )
    except Exception as e:
        logging.error(f"[db] log_payment error: {e}")


async def get_setting(key: str, default: str = "") -> str:
    try:
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT `value` FROM settings WHERE `key` = %s", (key,))
                row = await cur.fetchone()
                if row:
                    return str(row[0])
    except Exception as e:
        logging.error(f"[db] get_setting error for key {key}: {e}")
    return default
async def get_user_purchases (user_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("""
                SELECT p.id, p.account_id, a.country, a.number, a.password, a.data, p.date, p.currency, p.status, p.paid_amount, t.status AS ticket_status
                FROM purchases p JOIN accounts a ON p.account_id = a.id
                LEFT JOIN support_tickets t ON t.purchase_id = p.id
                WHERE p.user_id = %s ORDER BY p.id DESC
            """,(user_id ,))
            return await cur .fetchall ()

async def get_purchase_for_user (purchase_id :int ,user_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("""
                SELECT p.*, a.country, a.code, a.number, a.password, a.data, a.price, a.telegram_user_id, t.status AS ticket_status
                FROM purchases p JOIN accounts a ON p.account_id = a.id
                LEFT JOIN support_tickets t ON t.purchase_id = p.id
                WHERE p.id = %s AND p.user_id = %s
            """,(purchase_id ,user_id ))
            return await cur .fetchone ()

async def complete_user_purchase(account_id: int):
    from database.admin_tools import _transaction
    async with _transaction() as cur:
        await cur.execute("UPDATE purchases SET status = 'completed' WHERE account_id = %s AND status <> 'refunded'", (account_id,))
        await cur.execute("UPDATE accounts SET data = '✅ Сессия удалена (Покупка завершена)' WHERE id = %s AND status <> 'refunded'", (account_id,))


async def add_account(country, code, number, password, price, data, telegram_user_id=None, is_premium=None):
    from database.admin_tools import _transaction
    from database.imports import claim, bind
    async with _transaction() as cur:
        keys = await claim(cur, number, telegram_user_id, data)
        await cur.execute("INSERT INTO accounts(country,code,number,password,price,data,telegram_user_id,warranty_hours,is_premium,attributes_checked_at) VALUES(%s,%s,%s,%s,%s,%s,%s,24,%s,UTC_TIMESTAMP())", (country,code,number,password,price,data,telegram_user_id,is_premium))
        await bind(cur, keys, cur.lastrowid)

async def delete_account (account_id :int ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("DELETE FROM purchases WHERE account_id = %s",(account_id ,))
            await cur .execute ("DELETE FROM accounts WHERE id = %s",(account_id ,))

async def update_account_country(account_id: int, new_country: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not await cur.fetchone():
                return False
            await cur.execute("UPDATE accounts SET country = %s WHERE id = %s", (new_country, account_id))
            return True

async def update_account_price(account_id: int, new_price: float) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM accounts WHERE id = %s", (account_id,))
            if not await cur.fetchone():
                return False
            await cur.execute("UPDATE accounts SET price = %s WHERE id = %s", (new_price, account_id))
            return True

async def create_promo (code ,value ,max_uses ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("REPLACE INTO promocodes (code, value, max_uses) VALUES (%s, %s, %s)",(code ,value ,max_uses ))

async def get_all_promocodes ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT * FROM promocodes")
            return await cur .fetchall ()

async def delete_promo (code :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :

            await cur .execute ("DELETE FROM promocodes WHERE code = %s",(code ,))

            await cur .execute ("DELETE FROM used_promos WHERE code = %s",(code ,))

async def check_and_use_promo(user_id: int, code: str) -> float:
    from database.coupons import redeem_balance
    try:
        return float(await redeem_balance(user_id, code))
    except ValueError:
        return 0.0

async def update_country_price (country :str ,new_price :float ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("UPDATE accounts SET price = %s WHERE country = %s AND status = 'available'",(new_price ,country ))
            return cur .rowcount 

async def log_broadcast (admin_id :int ,created_at :str ,total_users :int ,success :int ,failed :int ,note :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("""
                INSERT INTO broadcast_logs (admin_id, created_at, total_users, success, failed, note)
                VALUES (%s, %s, %s, %s, %s, %s)
            """,(admin_id ,created_at ,total_users ,success ,failed ,note ))

async def get_stats ():
    async with _get_pool().acquire() as conn :
        async with conn .cursor (aiomysql .DictCursor )as cur :
            await cur .execute ("SELECT COUNT(id) as total, SUM(balance) as bal, SUM(balance_usdt) as bal_usdt FROM users")
            u =await cur .fetchone ()
            await cur .execute ("SELECT COUNT(id) as cnt, SUM(price) as val FROM accounts WHERE status = 'available'")
            a =await cur .fetchone ()
            await cur .execute ("SELECT COUNT(id) as sold FROM accounts WHERE status = 'sold'")
            s =await cur .fetchone ()

            await cur .execute ("""
                SELECT COUNT(p.id) as purc, SUM(COALESCE(p.paid_amount, acc.price)) as rev
                FROM purchases p 
                JOIN accounts acc ON p.account_id = acc.id
                WHERE p.status <> 'refunded'
            """)
            p_res =await cur .fetchone ()

            await cur .execute ("SELECT COUNT(code) as promos FROM promocodes")
            pr =await cur .fetchone ()
            return {
            "users":u ['total']or 0 ,"total_balance":u ['bal']or 0.0 ,"total_balance_usdt":u ['bal_usdt']or 0.0 ,
            "accounts_available":a ['cnt']or 0 ,"accounts_value":a ['val']or 0.0 ,
            "accounts_sold":s ['sold']or 0 ,"revenue":p_res ['rev']or 0.0 ,
            "purchases":p_res ['purc']or 0 ,"promos":pr ['promos']or 0 
            }


async def is_comment_used (comment :str )->bool :
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("SELECT comment FROM used_transactions WHERE comment = %s",(comment ,))
            return await cur .fetchone ()is not None 

async def mark_comment_used (comment :str ):
    async with _get_pool().acquire() as conn :
        async with conn .cursor ()as cur :
            await cur .execute ("INSERT IGNORE INTO used_transactions (comment) VALUES (%s)",(comment ,))




async def set_setting(key: str, value: str) -> None:
    """Устанавливает значение настройки в базе данных."""
    try:
        async with _get_pool().acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO settings (`key`, `value`) VALUES (%s, %s) "
                    "ON DUPLICATE KEY UPDATE `value` = %s",
                    (key, value, value),
                )
    except Exception as e:
        logging.error(f"[db] set_setting error for key {key}: {e}")


# ── Referral DB functions ─────────────────────────────────────────────

async def create_user_with_referrer(user_id: int, referrer_id: int | None, username: str | None = None) -> None:
    clean_username = username.lstrip("@").strip() if username else None
    async with _get_pool().acquire() as conn:
        await conn.autocommit(False)
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO users (id, balance, balance_usdt, username) VALUES (%s, 0, 0, %s) "
                    "ON DUPLICATE KEY UPDATE username = IF(%s IS NOT NULL AND %s != '', %s, username)",
                    (user_id, clean_username, clean_username, clean_username, clean_username)
                )
                if referrer_id is not None and int(referrer_id) != int(user_id):
                    await cur.execute("SELECT id FROM users WHERE id = %s", (referrer_id,))
                    if await cur.fetchone():
                        await cur.execute(
                            "INSERT IGNORE INTO referrals (referral_id, referrer_id) VALUES (%s, %s)",
                            (user_id, referrer_id),
                        )
                    else:
                        logging.warning(f"[db] Referrer {referrer_id} does not exist. Skipping referral relationship.")
            await conn.commit()
        except Exception as e:
            await conn.rollback()
            logging.error(f"[db] create_user_with_referrer error: {e}")
        finally:
            await conn.autocommit(True)


async def is_new_user(user_id: int) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            return await cur.fetchone() is None


async def get_referrer(user_id: int) -> int | None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT referrer_id FROM referrals WHERE referral_id = %s", (user_id,))
            row = await cur.fetchone()
            return int(row["referrer_id"]) if row else None


async def get_referral_count(user_id: int) -> int:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id = %s", (user_id,))
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def get_referral_settings() -> dict:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT discount_pct, bonus_pct FROM referral_settings WHERE id = 1")
            row = await cur.fetchone()
            if row:
                return {"discount_pct": float(row["discount_pct"]), "bonus_pct": float(row["bonus_pct"])}
            return {"discount_pct": 5.0, "bonus_pct": 5.0}


# ── Referral purchase ─────────────────────────────────────────────────

async def buy_account_with_referral(
    user_id: int, account_id: int, price: float,
    date_str: str, discount_pct: float, bonus_pct: float,
    referrer_id: int | None = None, currency: str = "USDT",
) -> int | None:
    async with _get_pool().acquire() as conn:
        await conn.autocommit(False)
        await conn.begin()
        try:
            async with conn.cursor() as cur:
                effective_price = round(price * (1 - discount_pct / 100), 2 if currency == "RUB" else 8)
                bonus_amount = round(price * bonus_pct / 100, 8)

                await cur.execute(
                    "SELECT id, status FROM accounts WHERE id = %s AND status = 'available' AND (spam_lease_until IS NULL OR spam_lease_until<=UTC_TIMESTAMP()) FOR UPDATE",
                    (account_id,)
                )
                acc_row = await cur.fetchone()
                if not acc_row:
                    await conn.rollback()
                    return None

                await cur.execute("SELECT user_id FROM account_reservations WHERE account_id = %s AND expires_at > UTC_TIMESTAMP() FOR UPDATE", (account_id,))
                reservation = await cur.fetchone()
                if reservation and reservation[0] != user_id:
                    await conn.rollback()
                    return None

                balance_col = "balance_usdt" if currency == "USDT" else "balance"
                await cur.execute(
                    f"SELECT {balance_col} FROM users WHERE id = %s FOR UPDATE",
                    (user_id,)
                )
                row = await cur.fetchone()
                if not row or float(row[0]) < effective_price:
                    await conn.rollback()
                    return None

                await cur.execute(f"UPDATE users SET {balance_col} = {balance_col} - %s WHERE id = %s", (effective_price, user_id))
                await cur.execute("UPDATE accounts SET status = 'sold' WHERE id = %s", (account_id,))
                await cur.execute(
                    "INSERT INTO purchases (user_id, account_id, date, currency, paid_amount) VALUES (%s, %s, %s, %s, %s)",
                    (user_id, account_id, date_str, currency, effective_price),
                )
                purc_id = cur.lastrowid
                from database.quality import snapshot
                await snapshot(cur, purc_id)
                await cur.execute("DELETE FROM shopping_cart WHERE user_id = %s AND account_id = %s", (user_id, account_id))
                await cur.execute("DELETE FROM account_reservations WHERE account_id = %s", (account_id,))

                if referrer_id is None:
                    await cur.execute("SELECT referrer_id FROM referrals WHERE referral_id = %s", (user_id,))
                    ref_row = await cur.fetchone()
                    referrer_id = int(ref_row[0]) if ref_row else None

                if referrer_id is not None:
                    await cur.execute(
                        f"UPDATE users SET {balance_col} = {balance_col} + %s WHERE id = %s",
                        (bonus_amount, referrer_id),
                    )
                    if cur.rowcount == 0:
                        referrer_id = None
                await cur.execute(
                    "UPDATE purchases SET referrer_id = %s, referral_bonus = %s WHERE id = %s",
                    (referrer_id, bonus_amount if referrer_id is not None else 0, purc_id),
                )
            await conn.commit()
            logging.info(
                f"[db] Referral purchase completed: user={user_id}, account={account_id}, "
                f"effective_price={effective_price} {currency}, referrer={referrer_id}, bonus={bonus_amount} {currency}"
            )
            return purc_id
        except Exception as e:
            await conn.rollback()
            logging.error(f"[db] buy_account_with_referral error: {e}")
            return None
        finally:
            await conn.autocommit(True)


# ── ButtonLabelManager DB functions ───────────────────────────────────

async def get_button_label(key: str) -> dict | None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT label, emoji_id FROM button_labels WHERE btn_key = %s", (key,))
            return await cur.fetchone()


async def set_button_label(key: str, label: str) -> None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO button_labels (btn_key, label) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE label = %s",
                (key, label, label),
            )


async def set_button_emoji(key: str, emoji_id: str | None) -> None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            if emoji_id is None:
                await cur.execute(
                    "UPDATE button_labels SET emoji_id = NULL WHERE btn_key = %s",
                    (key,),
                )
            else:
                await cur.execute(
                    "INSERT INTO button_labels (btn_key, label, emoji_id) VALUES (%s, '', %s) "
                    "ON DUPLICATE KEY UPDATE emoji_id = VALUES(emoji_id)",
                    (key, emoji_id),
                )


async def get_all_button_labels() -> list[dict]:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT btn_key, label, emoji_id FROM button_labels")
            return await cur.fetchall()


# ── Category DB functions ──────────────────────────────────────────────

async def get_all_categories() -> list[dict]:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM categories ORDER BY sort_order ASC")
            return await cur.fetchall()


async def get_active_categories() -> list[dict]:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM categories WHERE is_active = 1 ORDER BY sort_order ASC")
            return await cur.fetchall()


async def get_category(slug: str) -> dict | None:
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM categories WHERE slug = %s", (slug,))
            return await cur.fetchone()


async def create_category(slug: str, name: str, emoji: str | None = None) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await cur.execute(
                    "INSERT INTO categories (slug, name, emoji) VALUES (%s, %s, %s)",
                    (slug, name, emoji),
                )
                return cur.rowcount > 0
            except Exception:
                return False


async def update_category(slug: str, name: str, emoji: str | None) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE categories SET name = %s, emoji = %s WHERE slug = %s",
                (name, emoji, slug),
            )
            return cur.rowcount > 0


async def update_category_emoji(slug: str, emoji: str | None) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE categories SET emoji = %s WHERE slug = %s",
                (emoji, slug),
            )
            return cur.rowcount > 0


async def toggle_category(slug: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("UPDATE categories SET is_active = NOT is_active WHERE slug = %s", (slug,))
            return cur.rowcount > 0


async def delete_category(slug: str) -> bool:
    async with _get_pool().acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM categories WHERE slug = %s", (slug,))
            return cur.rowcount > 0


async def get_available_categories() -> list[dict]:
    """Возвращает активные категории, в которых есть доступные аккаунты"""
    async with _get_pool().acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("""
                SELECT c.*, COUNT(a.id) as accounts_count, MIN(a.price) as min_price
                FROM categories c
                LEFT JOIN accounts a ON a.country = c.slug AND a.status = 'available'
                WHERE c.is_active = 1
                GROUP BY c.slug
                HAVING accounts_count > 0
                ORDER BY c.sort_order ASC
            """)
            return await cur.fetchall()


async def get_subscription_settings() -> dict:
    """Получает настройки обязательной подписки на канал."""
    try:
        async with _get_pool().acquire() as conn:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(
                    "SELECT `key`, `value` FROM settings WHERE `key` IN ('sub_channel_id', 'sub_channel_url', 'sub_channel_enabled')"
                )
                rows = await cur.fetchall()
                res = {"enabled": False, "channel_id": "", "channel_url": ""}
                for r in rows:
                    if r["key"] == "sub_channel_id":
                        res["channel_id"] = r["value"]
                    elif r["key"] == "sub_channel_url":
                        res["channel_url"] = r["value"]
                    elif r["key"] == "sub_channel_enabled":
                        res["enabled"] = (r["value"] == "1")
                return res
    except Exception as e:
        logging.error(f"[db] get_subscription_settings error: {e}")
        return {"enabled": False, "channel_id": "", "channel_url": ""}
