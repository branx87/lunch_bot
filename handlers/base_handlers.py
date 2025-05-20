# ##handlers/base_handlers.py
import logging
import asyncio
from telegram import Update, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ConversationHandler
from telegram.ext import ContextTypes
from datetime import datetime, timedelta

from config import ADMIN_IDS, CONFIG, TIMEZONE
from constants import FULL_NAME, PHONE, SELECT_MONTH_RANGE
from db import db
from handlers.common import show_main_menu
from handlers.common_handlers import view_orders
from handlers.menu_handlers import monthly_stats, show_today_menu, show_week_menu
from handlers.report_handlers import select_month_range
from keyboards import create_main_menu_keyboard
from report_generators import export_accounting_report, export_daily_admin_report, export_daily_orders_for_provider
from utils import check_registration, handle_unregistered


logger = logging.getLogger(__name__)

__all__ = ['start', 'error_handler', 'test_connection', 'main_menu', 'handle_text_message']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик команды /start. Проверяет регистрацию пользователя:
    - Для новых пользователей запрашивает номер телефона
    - Для незавершивших регистрацию очищает данные и запрашивает повторно
    - Для зарегистрированных пользователей показывает главное меню
    """
    await update.message.reply_text("Обновляю меню...", reply_markup=ReplyKeyboardRemove())
    user = update.effective_user
    
    try:
        db.cursor.execute("SELECT is_verified FROM users WHERE telegram_id = ?", (user.id,))
        user_data = db.cursor.fetchone()

        if not user_data:
            keyboard = [[KeyboardButton("📱 Отправить номер телефона", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "Для регистрации нам нужен ваш номер телефона:",
                reply_markup=reply_markup
            )
            return PHONE
        elif not user_data[0]:
            db.cursor.execute("DELETE FROM users WHERE telegram_id = ?", (user.id,))
            db.conn.commit()
            keyboard = [[KeyboardButton("📱 Отправить номер телефона", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
            await update.message.reply_text(
                "Пожалуйста, завершите регистрацию:",
                reply_markup=reply_markup
            )
            return PHONE
        else:
            return await show_main_menu(update, user.id)
    except Exception as e:
        logger.error(f"Ошибка в start: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return await show_main_menu(update, user.id)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Глобальный обработчик ошибок бота. Логирует ошибку и:
    - Отправляет уведомление администраторам
    - Информирует пользователя о проблеме
    Обрабатывает как ошибки в обработчиках, так и системные ошибки
    """
    error = str(context.error)
    logger.error(f"Ошибка: {error}", exc_info=context.error)
    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"⚠️ Ошибка в боте:\n\n{error}\n\n"
                     f"Update: {update if update else 'Нет данных'}"
            )
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")
    
    if update and isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("⚠️ Произошла ошибка. Пожалуйста, попробуйте позже.")
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение пользователю: {e}")

async def test_connection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Тестирует работоспособность соединения с Telegram API.
    Проверяет доступность бота, выводит его основные данные.
    Автоматически удаляет тестовые сообщения через 5 секунд.
    """
    try:
        msg = await update.message.reply_text("🔄 Тестируем соединение...")
        bot_info = await context.bot.get_me()
        test_msg = await update.message.reply_text(
            f"✅ Соединение работает\n"
            f"🤖 Бот: @{bot_info.username}\n"
            f"🆔 ID: {bot_info.id}\n"
            f"📝 Имя: {bot_info.first_name}"
        )
        await asyncio.sleep(5)
        await msg.delete()
        await test_msg.delete()
    except Exception as e:
        logger.error(f"Ошибка соединения: {e}")
        await update.message.reply_text(
            f"❌ Ошибка соединения:\n{str(e)}\n"
            "Проверьте:\n"
            "1. Интернет-соединение\n"
            "2. Токен бота\n"
            "3. Ограничения сервера"
        )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Основной обработчик текстовых сообщений. Выполняет:
    - Обработку сообщений от незарегистрированных пользователей
    - Проверку регистрации пользователя
    - Перенаправление команд в соответствующие обработчики
    - Обработку запросов отчетов по месяцам
    """
    user = update.effective_user
    text = update.message.text
    logger.info(f"Получено сообщение: '{text}' от {user.id}")
    
    try:
        # 1. Обработка сообщения от незарегистрированного пользователя
        if text == "Написать администратору":
            unverified_name = context.user_data.get('unverified_name', 'не указано')
            message = (
                f"⚠️ Незарегистрированный пользователь сообщает:\n"
                f"👤 Имя: {unverified_name}\n"
                f"🆔 ID: {user.id}\n"
                f"📱 Username: @{user.username if user.username else 'нет'}\n"
                f"✉️ Сообщение: Пользователь не найден в списке сотрудников"
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(chat_id=admin_id, text=message)
                except Exception as e:
                    logger.error(f"Ошибка отправки админу {admin_id}: {e}")
            
            await update.message.reply_text(
                "✅ Ваше сообщение отправлено администратору. Ожидайте ответа.",
                reply_markup=ReplyKeyboardMarkup([["Попробовать снова"]], resize_keyboard=True)
            )
            return FULL_NAME

        # 2. Проверка регистрации
        if not await check_registration(update, context):
            return await handle_unregistered(update, context)

        if text in ["Текущий месяц", "Прошлый месяц"] and context.user_data.get('report_type'):
            return await select_month_range(update, context)
        
        # 4. Все остальные команды
        return await main_menu(update, context)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_text_message: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте снова или используйте /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, user.id)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный обработчик команд основного меню. Обеспечивает:
    - Навигацию по разделам меню (дневное/недельное меню, заказы)
    - Формирование отчетов (дневных/месячных) с проверкой прав доступа
    - Обработку команды обновления меню
    - Перенаправление неизвестных команд
    """
    logger.info(f"Получена команда: '{update.message.text}' от пользователя {update.effective_user.id}")
    
    try:
        user = update.effective_user
        text = update.message.text
        
        # Проверка регистрации
        if not await check_registration(update, context):
            return await handle_unregistered(update, context)

        # Основные команды меню
        if text == "Меню на сегодня":
            return await show_today_menu(update, context)
        
        elif text == "Меню на неделю":
            return await show_week_menu(update, context)
        
        elif text == "Просмотреть заказы":
            return await view_orders(update, context)
        
        elif text == "Статистика за месяц":
            return await monthly_stats(update, context)
        
        elif text == "📅 Отчет за месяц":
            # Устанавливаем тип отчета в зависимости от прав пользователя
            if user.id in CONFIG.get('admin_ids', []):
                context.user_data['report_type'] = 'admin'
            elif user.id in CONFIG.get('provider_ids', []):
                context.user_data['report_type'] = 'provider'
            elif user.id in CONFIG.get('accounting_ids', []):
                context.user_data['report_type'] = 'accounting'
            else:
                await update.message.reply_text("❌ У вас нет прав для просмотра отчетов")
                return await show_main_menu(update, user.id)
            
            # Запрашиваем период
            await update.message.reply_text(
                "Выберите период:",
                reply_markup=ReplyKeyboardMarkup([
                    ["Текущий месяц"],
                    ["Прошлый месяц"],
                    ["Вернуться в главное меню"]
                ], resize_keyboard=True)
            )
            return SELECT_MONTH_RANGE
        
        elif text == "📊 Отчет за день":
            today = datetime.now(TIMEZONE).date()
            if user.id in CONFIG.get('admin_ids', []):
                await export_daily_admin_report(update, context, today)
            elif user.id in CONFIG.get('provider_ids', []):
                await export_daily_orders_for_provider(update, context, today)
            elif user.id in CONFIG.get('accounting_ids', []):
                await export_accounting_report(update, context, today, today)
            else:
                await update.message.reply_text("❌ Нет прав доступа")
            return await show_main_menu(update, user.id)
        
        elif text == "Вернуться в главное меню":
            return await show_main_menu(update, user.id)
        
        elif text == "Обновить меню":
            await update.message.reply_text("Обновляю меню...", reply_markup=ReplyKeyboardRemove())
            return await show_main_menu(update, user.id)

        # Обработка неизвестной команды
        else:
            await update.message.reply_text(
                "Неизвестная команда. Попробуйте обновить меню или используйте /start",
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, user.id)

    except Exception as e:
        logger.error(f"Ошибка в main_menu: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте снова.",
            reply_markup=create_main_menu_keyboard(user.id) if user else ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
async def handle_registered_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Специализированный обработчик для зарегистрированных пользователей.
    Проверяет права доступа и предоставляет функционал:
    - Формирование бухгалтерских отчетов
    - Генерацию отчетов для поставщиков
    - Перенаправление остальных команд в main_menu
    """
    try:
        user = update.effective_user
        
        # Проверяем регистрацию
        db.cursor.execute("SELECT is_verified FROM users WHERE telegram_id = ?", (user.id,))
        result = db.cursor.fetchone()
        
        if not result or not result[0]:
            await update.message.reply_text(
                "Пожалуйста, сначала зарегистрируйтесь через /start",
                reply_markup=ReplyKeyboardRemove()
            )
            return
        
        # Если пользователь зарегистрирован - обрабатываем команду
        text = update.message.text
        
        # Обработка отчетов
        if text == "💰 Бухгалтерский отчет":
            if user.id in CONFIG['accounting_ids']:
                context.user_data['report_type'] = 'accounting'
                await update.message.reply_text(
                    "Выберите период:",
                    reply_markup=ReplyKeyboardMarkup([
                        ["Текущий месяц", "Прошлый месяц"],
                        ["Вернуться в главное меню"]
                    ], resize_keyboard=True)
                )
                return SELECT_MONTH_RANGE
        
        elif text == "📦 Отчет поставщика":
            if user.id in CONFIG['provider_ids']:
                context.user_data['report_type'] = 'provider'
                await update.message.reply_text(
                    "Выберите период:",
                    reply_markup=ReplyKeyboardMarkup([
                        ["Текущий месяц", "Прошлый месяц"],
                        ["Вернуться в главное меню"]
                    ], resize_keyboard=True)
                )
                return SELECT_MONTH_RANGE
        
        # Все остальные команды обрабатываем через main_menu
        return await main_menu(update, context)
    
    except Exception as e:
        logger.error(f"Ошибка в handle_registered_user: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте снова.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END