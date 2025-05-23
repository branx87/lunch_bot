# ##handlers/registration_handlers.py
import sqlite3
import logging
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ConversationHandler
from telegram.ext import ContextTypes
from datetime import datetime, timedelta

from config import LOCATIONS
from constants import FULL_NAME, LOCATION, PHONE
from db import db
from handlers.common import show_main_menu
from handlers.message_handlers import handle_admin_message
from utils import is_employee

logger = logging.getLogger(__name__)

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает получение номера телефона пользователя.
    Проверяет формат номера и его уникальность в системе.
    Переводит в состояние FULL_NAME при успешной валидации.
    """
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
    """
    Обрабатывает ввод ФИО пользователя.
    Проверяет:
    - Формат ввода (минимум 2 слова)
    - Наличие в списке сотрудников
    - Уникальность в системе
    Переводит в состояние LOCATION при успешной проверке.
    """
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
    """
    Завершает процесс регистрации:
    - Проверяет выбор локации из доступных
    - Сохраняет все данные пользователя в БД
    - Переводит в главное меню после успешной регистрации
    Обрабатывает возможные ошибки уникальности записи.
    """
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
