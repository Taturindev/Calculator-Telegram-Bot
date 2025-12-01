import sqlite3
import logging
import threading
import time
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_name='calculator_bot.db'):
        self.db_name = db_name
        self._lock = threading.Lock()
        self._init_db()
    
    @contextmanager
    def _get_connection(self):
        """Контекстный менеджер для безопасного подключения к БД"""
        conn = None
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries:
            try:
                with self._lock:
                    conn = sqlite3.connect(self.db_name, check_same_thread=False, timeout=30.0)
                    conn.execute("PRAGMA journal_mode=WAL")  # Включаем WAL mode для лучшей производительности
                    conn.execute("PRAGMA busy_timeout=10000")  # Увеличиваем таймаут до 10 секунд
                    yield conn
                break  # Успешное подключение, выходим из цикла
            except sqlite3.OperationalError as e:
                if "locked" in str(e) and retry_count < max_retries - 1:
                    retry_count += 1
                    logger.warning(f"БД заблокирована, повторная попытка {retry_count}/{max_retries}")
                    time.sleep(0.5)  # Ждем перед повторной попыткой
                    continue
                else:
                    logger.error(f"Ошибка подключения к БД после {retry_count} попыток: {e}")
                    raise
            finally:
                if conn:
                    conn.close()
    
    def _init_db(self):
        """Внутренняя инициализация базы данных"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Таблица пользователей
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        username TEXT,
                        first_name TEXT,
                        last_name TEXT,
                        subscribed BOOLEAN DEFAULT FALSE,
                        last_subscription_check TIMESTAMP,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        notifications_enabled BOOLEAN DEFAULT TRUE,
                        calculations_count INTEGER DEFAULT 0,
                        last_calculation TIMESTAMP,
                        profile_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Таблица сессий калькулятора
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS calculator_sessions (
                        user_id INTEGER PRIMARY KEY,
                        value TEXT DEFAULT '',
                        old_value TEXT DEFAULT '',
                        message_id INTEGER,
                        last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Таблица рассылок
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS broadcasts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        admin_id INTEGER,
                        message_text TEXT,
                        sent_count INTEGER DEFAULT 0,
                        failed_count INTEGER DEFAULT 0,
                        total_users INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'sending'
                    )
                ''')
                
                # Таблица настроек бота
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bot_settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    )
                ''')
                
                # Таблица истории обновлений
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS update_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        version TEXT,
                        changes_text TEXT,
                        release_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # Таблица истории вычислений
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS calculation_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        expression TEXT,
                        result TEXT,
                        calculation_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                conn.commit()
                logger.info("✅ База данных инициализирована")
                
        except Exception as e:
            logger.error(f"❌ Ошибка инициализации БД: {e}")
    
    def _migrate_database(self):
        """Миграция базы данных - добавляет новые столбцы при обновлении"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Проверяем существующие столбцы в users
                cursor.execute("PRAGMA table_info(users)")
                existing_columns = [column[1] for column in cursor.fetchall()]
                
                # Добавляем отсутствующие столбцы
                new_columns = [
                    ('calculations_count', 'INTEGER DEFAULT 0'),
                    ('last_calculation', 'TIMESTAMP'),
                    ('profile_updated', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
                ]
                
                for column_name, column_type in new_columns:
                    if column_name not in existing_columns:
                        cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}")
                        logger.info(f"✅ Добавлен столбец {column_name} в таблицу users")
                
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка миграции базы данных: {e}")
    
    def get_user(self, user_id):
        """Безопасное получение пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                user = cursor.fetchone()
                return user
        except Exception as e:
            logger.error(f"❌ Ошибка получения пользователя {user_id}: {e}")
            return None
    
    def create_user(self, user_id, username, first_name, last_name):
        """Безопасное создание пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, username, first_name, last_name, datetime.now()))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка создания пользователя {user_id}: {e}")
    
    def update_subscription_status(self, user_id, subscribed):
        """Безопасное обновление статуса подписки"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET subscribed = ?, last_subscription_check = ?, last_activity = ?
                    WHERE user_id = ?
                ''', (subscribed, datetime.now(), datetime.now(), user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка обновления подписки {user_id}: {e}")
    
    def update_user_activity(self, user_id):
        """Безопасное обновление активности"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET last_activity = ?
                    WHERE user_id = ?
                ''', (datetime.now(), user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка обновления активности {user_id}: {e}")
    
    def update_profile_data(self, user_id, username=None, first_name=None, last_name=None):
        """Безопасное обновление данных профиля"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                update_fields = []
                params = []
                
                if username is not None:
                    update_fields.append("username = ?")
                    params.append(username)
                if first_name is not None:
                    update_fields.append("first_name = ?")
                    params.append(first_name)
                if last_name is not None:
                    update_fields.append("last_name = ?")
                    params.append(last_name)
                
                update_fields.append("profile_updated = ?")
                params.append(datetime.now())
                
                params.append(user_id)
                
                if update_fields:
                    query = f"UPDATE users SET {', '.join(update_fields)} WHERE user_id = ?"
                    cursor.execute(query, params)
                
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка обновления профиля {user_id}: {e}")
    
    def increment_calculation_count(self, user_id):
        """Безопасное увеличение счетчика вычислений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET calculations_count = calculations_count + 1, last_calculation = ?, last_activity = ?
                    WHERE user_id = ?
                ''', (datetime.now(), datetime.now(), user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка увеличения счетчика {user_id}: {e}")
    
    def get_calculator_session(self, user_id):
        """Безопасное получение сессии калькулятора"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM calculator_sessions WHERE user_id = ?', (user_id,))
                session = cursor.fetchone()
                return session
        except Exception as e:
            logger.error(f"❌ Ошибка получения сессии {user_id}: {e}")
            return None
    
    def update_calculator_session(self, user_id, value, old_value, message_id):
        """Безопасное обновление сессии калькулятора"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO calculator_sessions 
                    (user_id, value, old_value, message_id, last_activity)
                    VALUES (?, ?, ?, ?, ?)
                ''', (user_id, value, old_value, message_id, datetime.now()))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка обновления сессии {user_id}: {e}")
    
    def reset_calculator_session(self, user_id):
        """Безопасный сброс сессии калькулятора"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM calculator_sessions WHERE user_id = ?', (user_id,))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка сброса сессии {user_id}: {e}")
    
    def get_user_stats(self):
        """Безопасное получение статистики"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                cursor.execute('SELECT COUNT(*) FROM users')
                total_users = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM users WHERE subscribed = 1')
                subscribed_users = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM calculator_sessions')
                active_sessions = cursor.fetchone()[0]
                
                # Активные пользователи за последние 7 дней
                cursor.execute('''
                    SELECT COUNT(*) FROM users 
                    WHERE last_activity > datetime('now', '-7 days')
                ''')
                active_week = cursor.fetchone()[0]
                
                # Общее количество вычислений
                cursor.execute('SELECT SUM(calculations_count) FROM users')
                total_calculations = cursor.fetchone()[0] or 0
                
                return {
                    'total_users': total_users,
                    'subscribed_users': subscribed_users,
                    'active_sessions': active_sessions,
                    'active_week': active_week,
                    'total_calculations': total_calculations
                }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {
                'total_users': 0,
                'subscribed_users': 0,
                'active_sessions': 0,
                'active_week': 0,
                'total_calculations': 0
            }
    
    def get_users_for_broadcast(self, only_subscribed=True):
        """Безопасное получение пользователей для рассылки"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                if only_subscribed:
                    cursor.execute('SELECT user_id FROM users WHERE subscribed = 1 AND notifications_enabled = 1')
                else:
                    cursor.execute('SELECT user_id FROM users WHERE notifications_enabled = 1')
                    
                users = [row[0] for row in cursor.fetchall()]
                return users
        except Exception as e:
            logger.error(f"❌ Ошибка получения пользователей для рассылки: {e}")
            return []
    
    def create_broadcast(self, admin_id, message_text, total_users=0):
        """Безопасное создание рассылки"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO broadcasts (admin_id, message_text, total_users, created_at)
                    VALUES (?, ?, ?, ?)
                ''', (admin_id, message_text, total_users, datetime.now()))
                broadcast_id = cursor.lastrowid
                conn.commit()
                return broadcast_id
        except Exception as e:
            logger.error(f"❌ Ошибка создания рассылки: {e}")
            return None
    
    def update_broadcast_stats(self, broadcast_id, sent_count, failed_count, status='completed'):
        """Безопасное обновление статистики рассылки"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE broadcasts 
                    SET sent_count = ?, failed_count = ?, status = ?
                    WHERE id = ?
                ''', (sent_count, failed_count, status, broadcast_id))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статистики рассылки {broadcast_id}: {e}")
    
    def get_broadcast_history(self, limit=5):
        """Безопасное получение истории рассылок"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM broadcasts 
                    ORDER BY created_at DESC 
                    LIMIT ?
                ''', (limit,))
                broadcasts = cursor.fetchall()
                return broadcasts
        except Exception as e:
            logger.error(f"❌ Ошибка получения истории рассылок: {e}")
            return []
    
    def get_all_users(self):
        """Безопасное получение всех пользователей"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT user_id, username, first_name, last_name, subscribed, created_at, last_activity, calculations_count, last_calculation
                    FROM users 
                    ORDER BY created_at DESC
                ''')
                users = cursor.fetchall()
                return users
        except Exception as e:
            logger.error(f"❌ Ошибка получения всех пользователей: {e}")
            return []
    
    def get_bot_setting(self, key):
        """Безопасное получение настройки бота"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT value FROM bot_settings WHERE key = ?', (key,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            logger.error(f"❌ Ошибка получения настройки {key}: {e}")
            return None
    
    def set_bot_setting(self, key, value):
        """Безопасная установка настройки бота"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO bot_settings (key, value)
                    VALUES (?, ?)
                ''', (key, value))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка установки настройки {key}: {e}")
    
    def add_update_history(self, version, changes_text):
        """Безопасное добавление истории обновлений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO update_history (version, changes_text, release_date)
                    VALUES (?, ?, ?)
                ''', (version, changes_text, datetime.now()))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка добавления истории обновлений: {e}")
    
    def get_update_history(self, limit=5):
        """Безопасное получение истории обновлений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT * FROM update_history 
                    ORDER BY release_date DESC 
                    LIMIT ?
                ''', (limit,))
                updates = cursor.fetchall()
                return updates
        except Exception as e:
            logger.error(f"❌ Ошибка получения истории обновлений: {e}")
            return []
    
    def toggle_user_notifications(self, user_id, enabled):
        """Безопасное переключение уведомлений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE users 
                    SET notifications_enabled = ?
                    WHERE user_id = ?
                ''', (enabled, user_id))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка переключения уведомлений {user_id}: {e}")
    
    def get_user_notifications_status(self, user_id):
        """Безопасное получение статуса уведомлений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT notifications_enabled FROM users WHERE user_id = ?', (user_id,))
                result = cursor.fetchone()
                return result[0] if result else True
        except Exception as e:
            logger.error(f"❌ Ошибка получения статуса уведомлений {user_id}: {e}")
            return True
    
    def add_calculation_history(self, user_id, expression, result):
        """Безопасное добавление истории вычислений"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO calculation_history (user_id, expression, result, calculation_date)
                    VALUES (?, ?, ?, ?)
                ''', (user_id, expression, result, datetime.now()))
                conn.commit()
        except Exception as e:
            logger.error(f"❌ Ошибка добавления истории вычислений {user_id}: {e}")
    
    def get_user_calculation_history(self, user_id, limit=10):
        """Безопасное получение истории вычислений пользователя"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT expression, result, calculation_date 
                    FROM calculation_history 
                    WHERE user_id = ?
                    ORDER BY calculation_date DESC 
                    LIMIT ?
                ''', (user_id, limit))
                history = cursor.fetchall()
                return history
        except Exception as e:
            logger.error(f"❌ Ошибка получения истории вычислений {user_id}: {e}")
            return []
    
    def cleanup_old_data(self, days=30):
        """Безопасная очистка старых данных с обработкой блокировок"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                
                # Очищаем старые сессии
                cursor.execute('''
                    DELETE FROM calculator_sessions 
                    WHERE last_activity < datetime('now', ?)
                ''', (f'-{days} days',))
                
                sessions_deleted = cursor.rowcount
                
                # Очищаем старую историю вычислений
                cursor.execute('''
                    DELETE FROM calculation_history 
                    WHERE calculation_date < datetime('now', ?)
                ''', (f'-{days} days',))
                
                history_deleted = cursor.rowcount
                
                conn.commit()
                
                if sessions_deleted > 0 or history_deleted > 0:
                    logger.info(f"✅ Очищено {sessions_deleted} сессий и {history_deleted} записей истории")
                    
        except sqlite3.OperationalError as e:
            if "locked" in str(e):
                logger.warning("📝 База данных временно заблокирована, пропускаем очистку")
            else:
                logger.error(f"❌ Ошибка очистки старых данных: {e}")
        except Exception as e:
            logger.error(f"❌ Ошибка очистки старых данных: {e}")

# Создаем глобальный экземпляр БД
db = Database()