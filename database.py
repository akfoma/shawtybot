import aiosqlite
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = 'vpn_bot.db'):
        self.db_path = db_path

    async def _connect(self):
        db = await aiosqlite.connect(self.db_path)
        await db.execute('PRAGMA foreign_keys = ON')
        return db

    async def _close(self, db):
        await db.close()

    async def init_db(self):
        db = await self._connect()
        try:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    username TEXT,
                    email TEXT UNIQUE NOT NULL,
                    uuid TEXT NOT NULL,
                    sub_id TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP,
                    device_limit INTEGER DEFAULT 3,
                    expiry_time INTEGER DEFAULT 0,
                    total_gb INTEGER DEFAULT 0
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    username TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP
                )
            ''')
            await self._migrate_requests_table(db)
            await self._migrate_users_table(db)
            await db.execute(
                'CREATE INDEX IF NOT EXISTS idx_requests_telegram_status ON requests(telegram_id, status)'
            )
            await db.execute(
                'CREATE UNIQUE INDEX IF NOT EXISTS idx_requests_one_pending '
                'ON requests(telegram_id) WHERE status = "pending"'
            )
            await db.commit()
        finally:
            await self._close(db)

    async def _migrate_requests_table(self, db):
        """Safely migrate requests table to add approved_at column if missing"""
        async with db.execute('PRAGMA table_info(requests)') as cursor:
            columns = [row[1] for row in await cursor.fetchall()]
        async with db.execute('PRAGMA foreign_key_list(requests)') as cursor:
            foreign_keys = await cursor.fetchall()

        # Check if migration is needed
        if 'approved_at' in columns and not foreign_keys:
            logger.info("Requests table already migrated")
            return

        # Check if approved_at column exists
        if 'approved_at' not in columns:
            logger.info("Adding approved_at column to requests table")
            try:
                await db.execute('ALTER TABLE requests ADD COLUMN approved_at TIMESTAMP')
                await db.commit()
                logger.info("Successfully added approved_at column")
            except Exception as e:
                logger.warning(f"Failed to add approved_at column: {e}")
                # Fallback to full migration if ALTER fails
                await self._full_migration(db, columns)
        else:
            logger.info("approved_at column already exists, skipping migration")

    async def _full_migration(self, db, existing_columns):
        """Full table migration as fallback"""
        logger.info("Performing full table migration")
        await db.execute('BEGIN TRANSACTION')
        try:
            await db.execute('ALTER TABLE requests RENAME TO requests_old')
            await db.execute('''
                CREATE TABLE requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    username TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    approved_at TIMESTAMP
                )
            ''')

            select_columns = ['id', 'telegram_id', 'username', 'status', 'created_at']
            target_columns = select_columns.copy()
            if 'approved_at' in existing_columns:
                select_columns.append('approved_at')
                target_columns.append('approved_at')

            await db.execute(
                f'''
                INSERT INTO requests ({', '.join(target_columns)})
                SELECT {', '.join(select_columns)} FROM requests_old
                '''
            )
            await db.execute('DROP TABLE requests_old')
            await db.commit()
            logger.info("Full migration completed successfully")
        except Exception as e:
            await db.execute('ROLLBACK')
            logger.error(f"Migration failed, rolled back: {e}")
            raise

    async def _migrate_users_table(self, db):
        """Migrate users table to add expiry_time and total_gb columns"""
        async with db.execute('PRAGMA table_info(users)') as cursor:
            columns = [row[1] for row in await cursor.fetchall()]

        if 'expiry_time' in columns and 'total_gb' in columns:
            logger.info("Users table already has expiry_time and total_gb columns")
            return

        logger.info("Adding expiry_time and total_gb columns to users table")
        try:
            if 'expiry_time' not in columns:
                await db.execute('ALTER TABLE users ADD COLUMN expiry_time INTEGER DEFAULT 0')
                logger.info("Added expiry_time column")
            if 'total_gb' not in columns:
                await db.execute('ALTER TABLE users ADD COLUMN total_gb INTEGER DEFAULT 0')
                logger.info("Added total_gb column")
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to add columns to users table: {e}")

    async def add_user(self, telegram_id: int, username: str, email: str, uuid: str, sub_id: str, expiry_time: int = 0, total_gb: int = 0):
        db = await self._connect()
        try:
            await db.execute('''
                INSERT INTO users (telegram_id, username, email, uuid, sub_id, status, approved_at, expiry_time, total_gb)
                VALUES (?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    email = excluded.email,
                    uuid = excluded.uuid,
                    sub_id = excluded.sub_id,
                    status = 'active',
                    approved_at = CURRENT_TIMESTAMP,
                    expiry_time = excluded.expiry_time,
                    total_gb = excluded.total_gb
            ''', (telegram_id, username, email, uuid, sub_id, expiry_time, total_gb))
            await db.commit()
        finally:
            await self._close(db)

    async def get_user_by_telegram_id(self, telegram_id: int):
        db = await self._connect()
        try:
            async with db.execute(
                'SELECT * FROM users WHERE telegram_id = ?',
                (telegram_id,)
            ) as cursor:
                return await cursor.fetchone()
        finally:
            await self._close(db)

    async def get_user_by_email(self, email: str):
        db = await self._connect()
        try:
            async with db.execute(
                'SELECT * FROM users WHERE email = ?',
                (email,)
            ) as cursor:
                return await cursor.fetchone()
        finally:
            await self._close(db)

    async def update_user_status(self, telegram_id: int, status: str):
        db = await self._connect()
        try:
            if status == 'active':
                await db.execute(
                    'UPDATE users SET status = ?, approved_at = CURRENT_TIMESTAMP WHERE telegram_id = ?',
                    (status, telegram_id)
                )
            else:
                await db.execute(
                    'UPDATE users SET status = ? WHERE telegram_id = ?',
                    (status, telegram_id)
                )
            await db.commit()
        finally:
            await self._close(db)

    async def delete_user(self, telegram_id: int):
        db = await self._connect()
        try:
            # Сначала удаляем связанные запросы (избегаем FK constraint violation)
            await db.execute('DELETE FROM requests WHERE telegram_id = ?', (telegram_id,))
            await db.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
            await db.commit()
        finally:
            await self._close(db)

    async def add_request(self, telegram_id: int, username: str):
        db = await self._connect()
        try:
            await db.execute('''
                INSERT INTO requests (telegram_id, username)
                VALUES (?, ?)
                ON CONFLICT(telegram_id) WHERE status = "pending"
                DO UPDATE SET username = excluded.username
            ''', (telegram_id, username))
            await db.commit()
        finally:
            await self._close(db)

    async def get_pending_requests(self):
        db = await self._connect()
        try:
            async with db.execute(
                'SELECT * FROM requests WHERE status = "pending" ORDER BY created_at DESC'
            ) as cursor:
                return await cursor.fetchall()
        finally:
            await self._close(db)

    async def get_request_by_id(self, request_id: int):
        db = await self._connect()
        try:
            async with db.execute(
                'SELECT * FROM requests WHERE id = ?',
                (request_id,)
            ) as cursor:
                return await cursor.fetchone()
        finally:
            await self._close(db)

    async def get_request_by_telegram_id(self, telegram_id: int):
        db = await self._connect()
        try:
            async with db.execute(
                'SELECT * FROM requests WHERE telegram_id = ? AND status = "pending" ORDER BY created_at DESC LIMIT 1',
                (telegram_id,)
            ) as cursor:
                return await cursor.fetchone()
        finally:
            await self._close(db)

    async def update_request_status(self, request_id: int, status: str):
        db = await self._connect()
        try:
            if status == 'approved':
                await db.execute(
                    'UPDATE requests SET status = ?, approved_at = CURRENT_TIMESTAMP WHERE id = ?',
                    (status, request_id)
                )
            else:
                await db.execute(
                    'UPDATE requests SET status = ? WHERE id = ?',
                    (status, request_id)
                )
            await db.commit()
        finally:
            await self._close(db)

    async def get_all_users(self):
        db = await self._connect()
        try:
            async with db.execute('SELECT * FROM users') as cursor:
                return await cursor.fetchall()
        finally:
            await self._close(db)

    async def delete_old_requests(self, hours: int = 12):
        """Delete pending requests older than specified hours"""
        db = await self._connect()
        try:
            await db.execute(f'DELETE FROM requests WHERE created_at < datetime("now", "-{hours} hours") AND status = "pending"')
            await db.commit()
            logger.info(f"Deleted requests older than {hours} hours")
        finally:
            await self._close(db)

    async def backup_database(self, backup_path: str = None):
        """Create a backup of the database"""
        import shutil
        from datetime import datetime

        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{self.db_path}.backup_{timestamp}"

        try:
            shutil.copy2(self.db_path, backup_path)
            logger.info(f"Database backed up to {backup_path}")
            return backup_path
        except Exception as e:
            logger.error(f"Failed to backup database: {e}")
            raise
