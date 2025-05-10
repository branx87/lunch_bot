import logging
import asyncio
from telegram import Update, ReplyKeyboardRemove, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ConversationHandler, ContextTypes
from .states import PHONE, MAIN_MENU, SELECT_MONTH_RANGE, FULL_NAME
from db import db
from config import CONFIG, ADMIN_IDS
from keyboards import create_main_menu_keyboard
from utils import check_registration, handle_unregistered
from .menu_handlers import show_today_menu, show_week_menu, view_orders, monthly_stats
from datetime import datetime, timedelta
from .common import show_main_menu
from .report_handlers import select_month_range
from admin import export_accounting_report

logger = logging.getLogger(__name__)

__all__ = ['start', 'error_handler', 'test_connection', 'main_menu', 'handle_text_message']

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Обновляю меню...", reply_markup=ReplyKeyboardRemove())
    user = update.effective_user
    context.user_data['restored'] = True
    
    try:
        context.user_data['is_initialized'] = True
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

        # 2. Проверка регистрации для остальных сообщений
        if not await check_registration(update, context):
            return await handle_unregistered(update, context)

        # 3. Обработка команд от зарегистрированных пользователей
        if text in ["💰 Бухгалтерский отчет", "📦 Отчет поставщика"]:
            context.user_data['report_type'] = 'accounting' if text.startswith('💰') else 'provider'
            await update.message.reply_text(
                "Выберите период:",
                reply_markup=ReplyKeyboardMarkup([
                    ["Текущий месяц", "Прошлый месяц"],
                    ["Вернуться в главное меню"]
                ], resize_keyboard=True)
            )
            return SELECT_MONTH_RANGE
        
        if text in ["Текущий месяц", "Прошлый месяц"] and context.user_data.get('report_type'):
            return await select_month_range(update, context)
        
        # 4. Все остальные команды передаем в основное меню
        return await main_menu(update, context)
        
    except Exception as e:
        logger.error(f"Ошибка в handle_text_message: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте снова или используйте /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return await show_main_menu(update, user.id)

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда: '{update.message.text}' от пользователя {update.effective_user.id}")
    
    try:
        user = update.effective_user
        text = update.message.text
        
        # Проверка регистрации
        if not await check_registration(update, context):
            return await handle_unregistered(update, context)

        from keyboards import create_main_menu_keyboard  # Добавляем импорт
        
        # Основные команды меню
        if text == "Меню на сегодня":
            return await show_today_menu(update, context)
        
        elif text == "Меню на неделю":
            return await show_week_menu(update, context)
        
        elif text == "Просмотреть заказы":
            return await view_orders(update, context)
        
        elif text == "Статистика за месяц":
            return await monthly_stats(update, context)
        
        # elif text == "Написать администратору":
            # return await start_admin_message(update, context)
        
        elif text == "Вернуться в главное меню":
            return await show_main_menu(update, user.id)
        
        elif text == "Обновить меню":
            await update.message.reply_text("Обновляю меню...", reply_markup=ReplyKeyboardRemove())
            return await show_main_menu(update, user.id)

        # Обработка отчетов
        elif text == "💰 Бухгалтерский отчет":
            if user.id in CONFIG['accounting_ids']:
                context.user_data['report_type'] = 'accounting'
                logger.info(f"Установлен report_type: accounting для пользователя {user.id}")
                await update.message.reply_text(
                    "Выберите период:",
                    reply_markup=ReplyKeyboardMarkup([
                        ["Текущий месяц"],
                        ["Прошлый месяц"],
                        ["Вернуться в главное меню"]
                    ], resize_keyboard=True)
                )
                return SELECT_MONTH_RANGE
            else:
                await update.message.reply_text("❌ У вас нет прав для просмотра бухгалтерских отчетов")
                return await show_main_menu(update, user.id)

        elif text == "📦 Отчет поставщика":
            if user.id in CONFIG['provider_ids']:
                context.user_data['report_type'] = 'provider'
                logger.info(f"Установлен report_type: provider для пользователя {user.id}")
                await update.message.reply_text(
                    "Выберите период:",
                    reply_markup=ReplyKeyboardMarkup([
                        ["Текущий месяц"],
                        ["Прошлый месяц"],
                        ["Вернуться в главное меню"]
                    ], resize_keyboard=True)
                )
                return SELECT_MONTH_RANGE
            else:
                await update.message.reply_text("❌ У вас нет прав для просмотра отчетов поставщика")
                return await show_main_menu(update, user.id)

        # Для администраторов
        elif text == "📊 Отчет за день":
            if user.id in CONFIG['admin_ids']:
                context.user_data['report_type'] = 'admin'
                await export_accounting_report(update, context)
                return await show_main_menu(update, user.id)
            else:
                await update.message.reply_text("❌ Эта команда только для администраторов")
                return await show_main_menu(update, user.id)

        elif text == "📅 Отчет за месяц":
            if user.id in CONFIG['admin_ids']:
                context.user_data['report_type'] = 'admin'
                await update.message.reply_text(
                    "Выберите период:",
                    reply_markup=ReplyKeyboardMarkup([
                        ["Текущий месяц"],
                        ["Прошлый месяц"],
                        ["Вернуться в главное меню"]
                    ], resize_keyboard=True)
                )
                return SELECT_MONTH_RANGE
            else:
                await update.message.reply_text("❌ Эта команда только для администраторов")
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
        from keyboards import create_main_menu_keyboard  # Импорт в блоке except
        await update.message.reply_text(
            "⚠️ Произошла ошибка. Попробуйте снова.",
            reply_markup=create_main_menu_keyboard(user.id)
        )
    
async def handle_registered_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик для зарегистрированных пользователей"""
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
