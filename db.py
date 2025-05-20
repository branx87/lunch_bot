# ##db.py
import sqlite3
import logging
from config import CONFIG, TIMEZONE
from datetime import datetime

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.conn = sqlite3.connect('lunch_bot.db', check_same_thread=False, isolation_level=None)
        self.cursor = self.conn.cursor()
        self._init_db()

    def execute(self, query, params=()):
        """Безопасное выполнение запроса с обработкой транзакций"""
        try:
            self.cursor.execute("BEGIN")
            if not isinstance(params, (tuple, list, dict)):
                raise ValueError("Параметры должны быть кортежем, списком или словарём")
                
            self.cursor.execute(query, params)
            result = self.cursor.fetchall()
            self.conn.commit()
            return result
        except sqlite3.Error as e:
            self.conn.rollback()
            logger.error(f"Ошибка выполнения SQL: {e} | Query: {query} | Params: {params}")
            raise

    def _init_db(self):
        """Создание таблиц и индексов при первом запуске"""
        try:
            # Настройки SQLite
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=5000")

            # Таблица пользователей
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    location TEXT NOT NULL,
                    is_verified BOOLEAN DEFAULT FALSE,
                    username TEXT,
                    is_deleted BOOLEAN DEFAULT FALSE,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Таблица заказов (обновлённая структура)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    target_date TEXT NOT NULL,
                    order_time TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 3),
                    is_preliminary BOOLEAN DEFAULT FALSE,
                    is_cancelled BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
                    /* Убрали CHECK с date() */
                )
            ''')

            # Таблица сообщений
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS admin_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    admin_id INTEGER,
                    user_id INTEGER,
                    message_text TEXT NOT NULL,
                    is_broadcast BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY(admin_id) REFERENCES users(telegram_id),
                    FOREIGN KEY(user_id) REFERENCES users(telegram_id)
                )
            ''')
            
            # Таблица отзывов поставщикам (добавлены NOT NULL constraints)
            self.cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    provider_id INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_processed BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY(provider_id) REFERENCES users(id) ON DELETE CASCADE
                )
            ''')

            # Создаем индексы (обновлённые)
            with self.conn:
                # Индексы для таблицы users
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_id)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_verified ON users(is_verified)")
                
                # Индексы для таблицы orders
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_target_date ON orders(target_date)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_created_at ON orders(created_at)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_cancelled ON orders(is_cancelled)")
                
                # Индексы для таблицы feedback_messages
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_user_id ON feedback_messages(user_id)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_provider_id ON feedback_messages(provider_id)")
                self.cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_processed ON feedback_messages(is_processed)")

            logger.info("✅ Все таблицы и индексы созданы корректно")

        except sqlite3.OperationalError as e:
            logger.error(f"❌ Ошибка создания таблиц: {e}")
            raise
        except Exception as e:
            logger.critical(f"⚠️ Критическая ошибка при инициализации БД: {e}")
            raise
            
# Глобальный экземпляр базы данных
db = Database()
