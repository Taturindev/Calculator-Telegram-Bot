#!/usr/bin/env python3
import sys
import os

# Добавляем текущую директорию в путь для импортов
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Сначала импортируем конфиг
from config import BOT_TOKEN, ADMIN_ID, CHANNEL_USERNAME, BOT_VERSION, DEBUG_MODE

# Затем импортируем остальные модули
import asyncio
import logging
import signal
import psutil
import time
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter, TelegramConflictError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

# Импортируем наши модули
from bot_database import db
from debug import debug_system

# Настройка логирования
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot_debug.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера с MemoryStorage
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=storage)

# Конфигурация
CHANNEL_URL = f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"
SESSION_TIMEOUT = 15 * 60

# История обновлений
UPDATE_HISTORY = {
    "2.3.1": """
🆕 **Версия 2.3.1** - *Ноябрь 2024*

🔧 **Исправление конфликтов бота:**
• Устранена ошибка множественных экземпляров бота
• Добавлена система graceful shutdown
• Улучшено управление процессами
• Исправлены конфликты getUpdates

🐛 **Исправления багов:**
• Исправлена ошибка TelegramConflictError
• Улучшена стабильность перезапуска
• Добавлена проверка запущенных процессов
• Улучшено логирование ошибок

⚡ **Улучшения производительности:**
• Оптимизировано использование памяти
• Улучшено управление соединениями
• Добавлены повторные попытки при конфликтах
    """
}

# Состояния
class BroadcastState(StatesGroup):
    waiting_for_message = State()
    waiting_for_confirmation = State()

# Кэш для проверки подписки
subscription_cache = {}

# Флаг для graceful shutdown
is_shutting_down = False

# Клавиатуры
def get_main_keyboard(user_id):
    """Основная клавиатура с командами"""
    keyboard = [
        [KeyboardButton(text="🧮 Калькулятор"), KeyboardButton(text="ℹ️ Помощь")],
        [KeyboardButton(text="📢 Подписаться на канал"), KeyboardButton(text="👤 Профиль")]
    ]
    
    # Автоматически добавляем кнопку админа если это админ
    if str(user_id) == str(ADMIN_ID):
        keyboard.append([KeyboardButton(text="👑 Админ панель"), KeyboardButton(text="🔧 Дебаг")])
    
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_profile_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔔 Вкл/Выкл уведомления", callback_data="toggle_notifications")],
        [InlineKeyboardButton(text="📊 Статистика вычислений", callback_data="calculation_stats")],
        [InlineKeyboardButton(text="🆕 Что нового", callback_data="whats_new")],
        [InlineKeyboardButton(text="🔄 Обновить профиль", callback_data="refresh_profile")]
    ])

def get_calculator_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text='C', callback_data='C'),
            InlineKeyboardButton(text='<=', callback_data='<='),
            InlineKeyboardButton(text='/', callback_data='/')
        ],
        [
            InlineKeyboardButton(text='7', callback_data='7'),
            InlineKeyboardButton(text='8', callback_data='8'),
            InlineKeyboardButton(text='9', callback_data='9'),
            InlineKeyboardButton(text='*', callback_data='*')
        ],
        [
            InlineKeyboardButton(text='4', callback_data='4'),
            InlineKeyboardButton(text='5', callback_data='5'),
            InlineKeyboardButton(text='6', callback_data='6'),
            InlineKeyboardButton(text='-', callback_data='-')
        ],
        [
            InlineKeyboardButton(text='1', callback_data='1'),
            InlineKeyboardButton(text='2', callback_data='2'),
            InlineKeyboardButton(text='3', callback_data='3'),
            InlineKeyboardButton(text='+', callback_data='+')
        ],
        [
            InlineKeyboardButton(text='0', callback_data='0'),
            InlineKeyboardButton(text=',', callback_data='.'),
            InlineKeyboardButton(text='=', callback_data='=')
        ]
    ])

def get_admin_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="📢 Создать рассылку", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin_users")],
        [InlineKeyboardButton(text="📋 История рассылок", callback_data="admin_broadcast_history")]
    ])

def get_subscription_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Подписаться", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="🔄 Проверить подписку", callback_data="check_subscription")]
    ])

def check_other_bot_instances():
    """Проверяет, не запущены ли другие экземпляры бота"""
    current_pid = os.getpid()
    current_script = os.path.basename(__file__)
    
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if (process.info['pid'] != current_pid and 
                process.info['cmdline'] and 
                current_script in ' '.join(process.info['cmdline']) and
                'python' in process.info['name'].lower()):
                
                logger.warning(f"⚠️ Обнаружен другой запущенный процесс бота (PID: {process.info['pid']})")
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    return False

async def kill_other_bot_instances():
    """Завершает другие экземпляры бота"""
    current_pid = os.getpid()
    current_script = os.path.basename(__file__)
    killed_count = 0
    
    for process in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if (process.info['pid'] != current_pid and 
                process.info['cmdline'] and 
                current_script in ' '.join(process.info['cmdline']) and
                'python' in process.info['name'].lower()):
                
                logger.info(f"🛑 Завершаем процесс бота (PID: {process.info['pid']})")
                process.terminate()
                killed_count += 1
                
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    
    if killed_count > 0:
        logger.info(f"✅ Завершено {killed_count} процессов бота")
        # Даем время для завершения процессов
        await asyncio.sleep(2)
    
    return killed_count

# Улучшенная проверка подписки с обработкой ошибок
async def check_user_subscription(user_id):
    """Проверяет подписку пользователя на канал с обработкой ошибок"""
    if user_id in subscription_cache:
        cached_result, timestamp = subscription_cache[user_id]
        # Кэш действителен 5 минут
        if (time.time() - timestamp) < 300:
            return cached_result
    
    try:
        chat_member = await bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        is_subscribed = chat_member.status in ['member', 'administrator', 'creator']
        
        # Сохраняем в кэш с временной меткой
        subscription_cache[user_id] = (is_subscribed, time.time())
        
        logger.info(f"✅ Пользователь {user_id} подписка: {is_subscribed} (статус: {chat_member.status})")
        return is_subscribed
        
    except TelegramBadRequest as e:
        if "user not found" in str(e).lower() or "chat not found" in str(e).lower():
            logger.error(f"❌ Ошибка проверки подписки: канал {CHANNEL_USERNAME} не найден")
            # Если канал не найден, разрешаем доступ для тестирования
            return True
        else:
            logger.error(f"❌ Ошибка Telegram API при проверке подписки {user_id}: {e}")
            # При ошибке API временно разрешаем доступ
            return True
            
    except TelegramForbiddenError:
        logger.error(f"❌ Бот не имеет доступа к каналу {CHANNEL_USERNAME}")
        # Если бот не имеет доступа, разрешаем доступ для тестирования
        return True
        
    except TelegramRetryAfter as e:
        logger.warning(f"⚠️ Лимит запросов, ждем {e.retry_after} сек")
        await asyncio.sleep(e.retry_after)
        # Повторная попытка после ожидания
        return await check_user_subscription(user_id)
        
    except Exception as e:
        logger.error(f"❌ Неизвестная ошибка проверки подписки {user_id}: {e}")
        debug_system.log_error(str(e), "check_user_subscription", 0)
        # При неизвестной ошибке временно разрешаем доступ
        return True

# Быстрая проверка доступа
async def check_user_access(user_id, username=None, first_name=None, last_name=None):
    """Проверяет доступ пользователя к функциям бота"""
    try:
        # Создаем/обновляем пользователя в БД
        db.create_user(user_id, username or "", first_name or "", last_name or "")
        
        # Обновляем данные профиля если они изменились
        if username or first_name or last_name:
            db.update_profile_data(user_id, username, first_name, last_name)
        
        # Проверяем подписку
        is_subscribed = await check_user_subscription(user_id)
        db.update_subscription_status(user_id, is_subscribed)
        
        # Обновляем активность
        db.update_user_activity(user_id)
        
        return is_subscribed
        
    except Exception as e:
        logger.error(f"❌ Ошибка проверки доступа для {user_id}: {e}")
        debug_system.log_error(str(e), "check_user_access", 0)
        # При ошибке разрешаем доступ
        return True

# Отправка калькулятора
async def send_calculator(chat_id, user_id):
    session = db.get_calculator_session(user_id)
    value = session[1] if session else ''
    
    try:
        text = f"🧮 **Калькулятор**\n\n`{value or '0'}`"
        message = await bot.send_message(chat_id, text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_calculator_keyboard())
        db.update_calculator_session(user_id, value or '', value or '', message.message_id)
    except Exception as e:
        logger.error(f"❌ Ошибка отправки калькулятора: {e}")
        debug_system.log_error(str(e), "send_calculator", 0)

# Обновление калькулятора
async def update_calculator(chat_id, user_id, message_id):
    session = db.get_calculator_session(user_id)
    value = session[1] if session else ''
    
    try:
        text = f"🧮 **Калькулятор**\n\n`{value or '0'}`"
        await bot.edit_message_text(text, chat_id, message_id, parse_mode=ParseMode.MARKDOWN, reply_markup=get_calculator_keyboard())
    except Exception as e:
        logger.error(f"❌ Ошибка обновления калькулятора: {e}")
        debug_system.log_error(str(e), "update_calculator", 0)

# Функция для открытия админ панели
async def show_admin_panel(chat_id, user_id):
    """Показывает админ панель"""
    try:
        if str(user_id) != str(ADMIN_ID):
            await bot.send_message(chat_id, "❌ У вас нет доступа к админ панели")
            return False
        
        stats = db.get_user_stats()
        admin_text = (
            f"👑 **Админ панель**\n\n"
            f"📊 **Статистика бота:**\n"
            f"• Версия: {BOT_VERSION}\n"
            f"• Всего пользователей: {stats['total_users']}\n"
            f"• Подписанных пользователей: {stats['subscribed_users']}\n"
            f"• Активных сессий: {stats['active_sessions']}\n"
            f"• Активных за неделю: {stats['active_week']}\n"
            f"• Всего вычислений: {stats['total_calculations']}\n"
            f"• Охват: {(stats['subscribed_users']/stats['total_users']*100) if stats['total_users'] > 0 else 0:.1f}%"
        )
        
        await bot.send_message(chat_id, admin_text, reply_markup=get_admin_keyboard(), parse_mode=ParseMode.MARKDOWN)
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка при открытии админ панели: {e}")
        debug_system.log_error(str(e), "show_admin_panel", 0)
        await bot.send_message(chat_id, "❌ Ошибка при загрузке админ панели")
        return False

# Функция для показа профиля пользователя
async def show_user_profile(chat_id, user_id):
    """Показывает профиль пользователя"""
    try:
        user = db.get_user(user_id)
        if not user:
            await bot.send_message(chat_id, "❌ Профиль не найден")
            return
        
        notifications_status = db.get_user_notifications_status(user_id)
        stats = db.get_user_stats()
        
        profile_text = (
            f"👤 **Ваш профиль**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"👤 Имя: {user[2]} {user[3] or ''}\n"
            f"📊 Статус подписки: {'✅ Активна' if user[4] else '❌ Не активна'}\n"
            f"🔔 Уведомления: {'✅ Включены' if notifications_status else '❌ Выключены'}\n"
            f"🧮 Вычислений: {user[9] or 0}\n"
            f"📅 Зарегистрирован: {user[6][:16] if user[6] else 'Неизвестно'}\n"
            f"🕒 Последняя активность: {user[7][:16] if user[7] else 'Неизвестно'}\n"
        )
        
        profile_text += f"\n📈 **Статистика бота:**\n"
        profile_text += f"• Всего пользователей: {stats['total_users']}\n"
        profile_text += f"• Версия бота: {BOT_VERSION}"
        
        await bot.send_message(chat_id, profile_text, reply_markup=get_profile_keyboard(), parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"❌ Ошибка при показе профиля: {e}")
        debug_system.log_error(str(e), "show_user_profile", 0)
        await bot.send_message(chat_id, "❌ Ошибка загрузки профиля")

# Обработчики команд
@dp.message(Command(commands=['start']))
async def start_command(message: Message):
    user_id = message.from_user.id
    has_access = await check_user_access(user_id, message.from_user.username, message.from_user.first_name, message.from_user.last_name)
    
    welcome_text = (
        f"🚀 **Добро пожаловать в калькулятор!**\n\n"
        f"**Версия {BOT_VERSION}**\n\n"
        "Используйте кнопки ниже для навигации:\n"
        "• 🧮 Калькулятор - открыть калькулятор\n"
        "• ℹ️ Помощь - получить справку\n"
        "• 👤 Профиль - настройки и статистика\n"
        "• 📢 Подписаться - получить доступ к боту"
    )
    
    if not has_access:
        welcome_text += f"\n\n🔒 **Требуется подписка на канал:** {CHANNEL_URL}"
    
    await message.answer(welcome_text, reply_markup=get_main_keyboard(user_id), parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text == "🧮 Калькуляator")
async def calculator_button(message: Message):
    user_id = message.from_user.id
    has_access = await check_user_access(user_id)
    
    if has_access:
        await send_calculator(message.chat.id, user_id)
    else:
        await message.answer(
            "🔒 **Доступ закрыт!**\n\nПодпишитесь на канал чтобы использовать калькулятор:",
            reply_markup=get_subscription_keyboard(),
            parse_mode=ParseMode.MARKDOWN
        )

@dp.message(F.text == "ℹ️ Помощь")
async def help_button(message: Message):
    help_text = (
        f"ℹ️ **Помощь по боту** (v{BOT_VERSION})\n\n"
        "🧮 **Калькулятор:**\n"
        "• Используйте кнопки для ввода\n"
        "• C - очистить\n"
        "• <= - удалить символ\n"
        "• = - вычислить\n\n"
        "🔧 **Основные команды:**\n"
        "/start - перезапустить бота\n"
        "/help - эта справка\n"
        "/profile - ваш профиль\n\n"
        "⚠️ **Важно:** Бот работает только с кнопками!"
    )
    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)

@dp.message(F.text == "📢 Подписаться на канал")
async def subscribe_button(message: Message):
    await message.answer(
        f"📢 **Подписка на канал**\n\nДля доступа к калькулятору подпишитесь на наш канал:\n{CHANNEL_URL}\n\nПосле подписки нажмите кнопку проверки:",
        reply_markup=get_subscription_keyboard(),
        parse_mode=ParseMode.MARKDOWN
    )

@dp.message(F.text == "👤 Профиль")
async def profile_button(message: Message):
    await show_user_profile(message.chat.id, message.from_user.id)

@dp.message(F.text == "👑 Админ панель")
async def admin_button(message: Message):
    """Обработчик кнопки админ панели"""
    user_id = message.from_user.id
    await show_admin_panel(message.chat.id, user_id)

@dp.message(Command(commands=['help']))
async def help_command(message: Message):
    await help_button(message)

@dp.message(Command(commands=['admin']))
async def admin_command(message: Message):
    """Обработчик команды /admin"""
    user_id = message.from_user.id
    await show_admin_panel(message.chat.id, user_id)

@dp.message(Command(commands=['profile']))
async def profile_command(message: Message):
    """Обработчик команды /profile"""
    user_id = message.from_user.id
    await show_user_profile(message.chat.id, user_id)

# Callback обработчики
@dp.callback_query(F.data == "check_subscription")
async def check_subscription_callback(query: types.CallbackQuery):
    user_id = query.from_user.id
    
    # Очищаем кэш для принудительной проверки
    if user_id in subscription_cache:
        del subscription_cache[user_id]
    
    has_access = await check_user_access(user_id)
    
    if has_access:
        await query.message.edit_text("✅ Отлично! Доступ открыт!\n\nТеперь вы можете использовать калькулятор!")
        await send_calculator(query.message.chat.id, user_id)
    else:
        await query.answer("❌ Вы еще не подписались или подписка не обнаружена!", show_alert=True)

@dp.callback_query(F.data == "toggle_notifications")
async def toggle_notifications_callback(query: types.CallbackQuery):
    user_id = query.from_user.id
    current_status = db.get_user_notifications_status(user_id)
    new_status = not current_status
    
    db.toggle_user_notifications(user_id, new_status)
    
    status_text = "включены" if new_status else "выключены"
    await query.answer(f"🔔 Уведомления {status_text}!", show_alert=True)
    await show_user_profile(query.message.chat.id, user_id)

@dp.callback_query(F.data == "refresh_profile")
async def refresh_profile_callback(query: types.CallbackQuery):
    user_id = query.from_user.id
    
    # Очищаем кэш подписки для обновления статуса
    if user_id in subscription_cache:
        del subscription_cache[user_id]
    
    await show_user_profile(query.message.chat.id, user_id)

@dp.callback_query(F.data.startswith("admin_"))
async def admin_callback_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    if str(user_id) != str(ADMIN_ID):
        await query.answer("❌ Доступ запрещен", show_alert=True)
        return
    
    action = query.data
    
    try:
        if action == "admin_stats":
            stats = db.get_user_stats()
            stats_text = (
                f"📊 **Статистика:**\n"
                f"• Версия: {BOT_VERSION}\n"
                f"• Всего пользователей: {stats['total_users']}\n"
                f"• Подписанных: {stats['subscribed_users']}\n"
                f"• Активных сессий: {stats['active_sessions']}\n"
                f"• Активных за неделю: {stats['active_week']}\n"
                f"• Всего вычислений: {stats['total_calculations']}\n"
                f"• Охват: {(stats['subscribed_users']/stats['total_users']*100) if stats['total_users'] > 0 else 0:.1f}%"
            )
            await query.message.edit_text(stats_text, parse_mode=ParseMode.MARKDOWN)
            
        elif action == "admin_users":
            users = db.get_all_users()
            
            if not users:
                await query.message.edit_text("📭 В базе данных нет пользователей.")
                return
            
            users_text = "👥 **Последние пользователи:**\n\n"
            for user in users[:5]:
                user_id, username, first_name, last_name, subscribed, created_at, last_activity, calculations_count, last_calculation = user
                users_text += f"• {first_name} {last_name or ''} (@{username or 'нет'})\n  ID: {user_id} - {'✅' if subscribed else '❌'} - 🧮 {calculations_count or 0}\n\n"
            
            if len(users) > 5:
                users_text += f"... и еще {len(users) - 5} пользователей"
            
            await query.message.edit_text(users_text, parse_mode=ParseMode.MARKDOWN)
            
    except Exception as e:
        logger.error(f"❌ Ошибка в админ callback: {e}")
        debug_system.log_error(str(e), "admin_callback_handler", 0)
        await query.answer("❌ Ошибка выполнения", show_alert=True)

# Обработчик калькулятора
@dp.callback_query()
async def calculator_callback_handler(query: types.CallbackQuery):
    user_id = query.from_user.id
    
    if not await check_user_access(user_id):
        await query.answer("❌ Подпишитесь на канал!", show_alert=True)
        return
    
    session = db.get_calculator_session(user_id)
    value = session[1] if session else ''
    old_value = session[2] if session else ''
    
    data = query.data
    
    try:
        if data == 'C':
            value = ''
        elif data == '<=':
            value = value[:-1] if value else ''
        elif data == '=':
            try:
                # Заменяем запятые на точки для вычисления
                expression = value.replace(',', '.')
                result = eval(expression)
                value = str(result).replace('.', ',') if isinstance(result, float) else str(result)
                # Увеличиваем счетчик вычислений
                db.increment_calculation_count(user_id)
                # Сохраняем в историю
                db.add_calculation_history(user_id, value, str(result))
            except ZeroDivisionError:
                value = 'Ошибка: деление на 0!'
            except:
                value = 'Ошибка вычисления!'
        else:
            value += data

        if value != old_value:
            await update_calculator(query.message.chat.id, user_id, query.message.message_id)
            db.update_calculator_session(user_id, value, value, query.message.message_id)

        if 'Ошибка' in value:
            # Сбрасываем значение после показа ошибки
            await asyncio.sleep(1)
            value = ''
            db.update_calculator_session(user_id, value, value, query.message.message_id)
            await update_calculator(query.message.chat.id, user_id, query.message.message_id)

    except Exception as e:
        logger.error(f"❌ Ошибка калькулятора: {e}")
        debug_system.log_error(str(e), "calculator_callback_handler", 0)
        await query.answer("Ошибка!", show_alert=True)

    await query.answer()

@dp.message()
async def any_message_handler(message: Message):
    """Обработчик любого текстового сообщения"""
    user_id = message.from_user.id
    
    if message.text and not message.text.startswith('/'):
        if not await check_user_access(user_id):
            await message.answer(
                "🔒 Для использования калькулятора необходимо подписаться на наш канал!",
                reply_markup=get_subscription_keyboard()
            )
            return
        
        warning_text = (
            "⚠️ **ВНИМАНИЕ!**\n\n"
            "Этот бот работает только с инлайн-клавиатурой!\n\n"
            "❌ **НЕ ПИШИТЕ** числа и операции в чат\n"
            "✅ **ИСПОЛЬЗУЙТЕ** кнопки калькулятора для всех действий\n\n"
            "Доступные команды:\n"
            "/start - главное меню\n"
            "/help - помощь\n" 
            "/profile - ваш профиль"
        )
        
        await message.answer(warning_text, parse_mode=ParseMode.MARKDOWN)

# Фоновая задача для очистки кэша
async def background_maintenance():
    """Фоновая задача для обслуживания системы"""
    while not is_shutting_down:
        try:
            # Очищаем старый кэш подписок (старше 10 минут)
            current_time = time.time()
            global subscription_cache
            subscription_cache = {user_id: data for user_id, data in subscription_cache.items() 
                                if current_time - data[1] < 600}
            
            # Очищаем старые данные (с обработкой возможных блокировок)
            try:
                db.cleanup_old_data(days=7)
            except Exception as e:
                if "locked" in str(e):
                    logger.warning("📝 База данных временно заблокирована, пропускаем очистку")
                else:
                    logger.error(f"❌ Ошибка при очистке данных: {e}")
            
            if DEBUG_MODE:
                logger.info("✅ Фоновая задача обслуживания выполнена")
            
            await asyncio.sleep(300)  # 5 минут
        except Exception as e:
            if not is_shutting_down:
                logger.error(f"❌ Ошибка в фоновой задаче: {e}")
                debug_system.log_error(str(e), "background_maintenance", 0)
                await asyncio.sleep(60)  # Ждем минуту при ошибке

async def graceful_shutdown():
    """Корректное завершение работы бота"""
    global is_shutting_down
    is_shutting_down = True
    
    logger.info("🛑 Завершение работы бота...")
    
    # Закрываем сессию бота
    await bot.session.close()
    
    logger.info("✅ Бот корректно завершил работу")

def signal_handler(signum, frame):
    """Обработчик сигналов завершения"""
    logger.info(f"📞 Получен сигнал {signum}, завершаем работу...")
    asyncio.create_task(graceful_shutdown())

# Запуск бота
async def main():
    # Регистрируем обработчики сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Проверяем и завершаем другие экземпляры бота
    if check_other_bot_instances():
        logger.warning("⚠️ Обнаружены другие запущенные экземпляры бота")
        killed_count = await kill_other_bot_instances()
        if killed_count > 0:
            logger.info("⏳ Ждем завершения процессов...")
            await asyncio.sleep(3)
    
    # Запускаем фоновые задачи
    maintenance_task = asyncio.create_task(background_maintenance())
    
    try:
        logger.info(f"🚀 Бот запущен (версия {BOT_VERSION})")
        logger.info(f"📢 Канал для подписки: {CHANNEL_USERNAME}")
        logger.info(f"👑 Админ ID: {ADMIN_ID}")
        if DEBUG_MODE:
            logger.info("🔧 Режим отладки включен")
        
        # Запускаем опрос с обработкой конфликтов
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except TelegramConflictError as e:
        logger.error(f"❌ Конфликт бота: {e}")
        logger.info("🔄 Попытка перезапуска через 10 секунд...")
        await asyncio.sleep(10)
        # Перезапускаем бота
        await main()
        
    except Exception as e:
        logger.error(f"❌ Критическая ошибка бота: {e}")
        debug_system.log_error(str(e), "main", 0)
        
    finally:
        # Отменяем фоновые задачи
        maintenance_task.cancel()
        try:
            await maintenance_task
        except asyncio.CancelledError:
            pass
            
        await graceful_shutdown()

if __name__ == "__main__":
    # Создаем файл блокировки
    lock_file = "bot.lock"
    
    try:
        # Проверяем, не запущен ли уже бот
        if os.path.exists(lock_file):
            logger.error("❌ Бот уже запущен! Удалите файл bot.lock если бот не работает")
            sys.exit(1)
        
        # Создаем файл блокировки
        with open(lock_file, 'w') as f:
            f.write(str(os.getpid()))
        
        asyncio.run(main())
        
    except Exception as e:
        logger.error(f"❌ Ошибка запуска: {e}")
        
    finally:
        # Удаляем файл блокировки при завершении
        if os.path.exists(lock_file):
            os.remove(lock_file)