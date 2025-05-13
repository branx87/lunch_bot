import sqlite3
import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from db import db
from config import CONFIG, LOCATIONS, ADMIN_IDS  # Добавлен импорт LOCATIONS
from utils import is_employee
from .constants import (
    AWAIT_MESSAGE_TEXT,
    PHONE, FULL_NAME,
    LOCATION, MAIN_MENU,
    ORDER_ACTION,
    ORDER_CONFIRMATION,
    SELECT_MONTH_RANGE,
    BROADCAST_MESSAGE,
    ADMIN_MESSAGE,
    AWAIT_USER_SELECTION,
    SELECT_MONTH_RANGE_STATS
)
from .base_handlers import show_main_menu
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message.contact:
            keyboard = [[KeyboardButton("📱 Отправить номер телефона", request_contact=True)]]
            reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            await update.message.reply_text(
                "Пожалуйста, используйте кнопку для отправки номера телефона:",
                reply_markup=reply_markup
            )
            return PHONE

        phone = update.message.contact.phone_number
        if not phone:
            await update.message.reply_text("Не удалось получить номер телефона. Попробуйте снова.")
            return PHONE

        db.cursor.execute("SELECT 1 FROM users WHERE phone = ?", (phone,))
        if db.cursor.fetchone():
            await update.message.reply_text("Этот номер телефона уже зарегистрирован.")
            return ConversationHandler.END

        context.user_data['phone'] = phone
        await update.message.reply_text("Отлично! Теперь введите ваше имя и фамилию одной строкой:")
        return FULL_NAME
    except Exception as e:
        logger.error(f"Ошибка при обработке номера телефона: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return PHONE

async def get_full_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получает и проверяет ФИО пользователя."""
    try:
        user_input = update.message.text.strip()
        logger.info(f"Получено имя: '{user_input}' от пользователя {update.effective_user.id}")

        # Обработка специальных команд
        if user_input == "Написать администратору":
            return await handle_admin_message(update, context)

        if user_input == "Попробовать снова":
            await update.message.reply_text("Введите ваше имя и фамилию:")
            return FULL_NAME

        # Проверяем формат имени
        name_parts = user_input.split()
        if len(name_parts) < 2:
            await update.message.reply_text(
                "❌ Пожалуйста, введите имя и фамилию полностью.\nПример: Иван Иванов"
            )
            return FULL_NAME

        full_name = ' '.join(name_parts)  # Нормализуем пробелы
        context.user_data['full_name'] = full_name

        # Проверяем, есть ли в списке сотрудников
        if not is_employee(full_name):
            context.user_data['unverified_name'] = full_name
            reply_markup = ReplyKeyboardMarkup(
                [["Попробовать снова"], ["Написать администратору"]],
                resize_keyboard=True
            )
            await update.message.reply_text(
                "❌ Вас нет в списке сотрудников. Вы можете:",
                reply_markup=reply_markup
            )
            return FULL_NAME

        # Проверяем, зарегистрирован ли уже
        db.cursor.execute(
            "SELECT 1 FROM users WHERE full_name = ? LIMIT 1",
            (full_name,)
        )
        if db.cursor.fetchone():
            await update.message.reply_text("⚠️ Данный сотрудник уже зарегистрирован.")
            return ConversationHandler.END

        # Переход к выбору локации
        keyboard = [[loc] for loc in LOCATIONS]
        reply_markup = ReplyKeyboardMarkup(
            keyboard,
            one_time_keyboard=True,
            resize_keyboard=True
        )
        await update.message.reply_text(
            "Выберите ваш объект:",
            reply_markup=reply_markup
        )
        return LOCATION

    except Exception as e:
        logger.error(f"Критическая ошибка в get_full_name: {e}", exc_info=True)
        await update.message.reply_text(
            "⚠️ Произошла системная ошибка. Попробуйте позже.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

async def get_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        
        location = update.message.text
        if location not in LOCATIONS:
            await update.message.reply_text("Пожалуйста, выберите объект из списка.")
            return LOCATION
            
        user = update.effective_user
        try:
            db.cursor.execute(
                "INSERT INTO users (telegram_id, full_name, phone, location, is_verified, username) "
                "VALUES (?, ?, ?, ?, TRUE, ?)",
                (user.id, context.user_data['full_name'], context.user_data['phone'], 
                 location, user.username or "")
            )
            db.conn.commit()
            logger.info(f"Пользователь {user.id} успешно зарегистрирован")
            return await show_main_menu(update, user_id)
        except sqlite3.IntegrityError as e:
            if "UNIQUE constraint failed" in str(e):
                await update.message.reply_text("❌ Этот пользователь уже зарегистрирован")
                return ConversationHandler.END
            raise e
    except Exception as e:
        logger.error(f"Ошибка в get_location: {e}")
        await update.message.reply_text("Произошла ошибка. Попробуйте снова.")
        return LOCATION
