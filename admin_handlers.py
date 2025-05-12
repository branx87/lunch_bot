import logging
from datetime import datetime, timedelta
from .base_handlers import show_main_menu
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler
from config import CONFIG, ADMIN_IDS  # Добавляем импорт
from .states import ADMIN_MESSAGE, SELECT_USER, AWAIT_MESSAGE_TEXT, BROADCAST_MESSAGE, FULL_NAME, MAIN_MENU, SELECT_MONTH_RANGE
from keyboards import create_main_menu_keyboard, create_admin_keyboard, create_month_selection_keyboard
import asyncio
from db import db
from admin import export_accounting_report

logger = logging.getLogger(__name__)

async def start_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало диалога с администратором"""
    await update.message.reply_text(
        "📝 Введите текст сообщения для администратора:",
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
    )
    return "AWAIT_ADMIN_MESSAGE"

async def handle_admin_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка введенного текста сообщения"""
    user = update.effective_user
    message_text = update.message.text
    
    # Проверяем, не хочет ли пользователь отменить
    if message_text.lower() == "отмена":
        await update.message.reply_text(
            "❌ Отправка сообщения отменена",
            reply_markup=ReplyKeyboardMarkup(create_main_menu_keyboard(user.id), resize_keyboard=True)
        )
        return ConversationHandler.END

    # Получаем информацию о пользователе из БД
    db.cursor.execute("SELECT full_name FROM users WHERE telegram_id = ?", (user.id,))
    user_data = db.cursor.fetchone()
    full_name = user_data[0] if user_data else "Неизвестный пользователь"

    # Формируем сообщение для администратора
    admin_msg = (
        f"✉️ Новое сообщение от пользователя:\n"
        f"👤 {full_name}\n"
        f"🆔 ID: {user.id}\n"
        f"📱 @{user.username if user.username else 'нет'}\n"
        f"📝 Текст: {message_text}"
    )

    # Отправляем всем администраторам
    success = 0
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(chat_id=admin_id, text=admin_msg)
            success += 1
        except Exception as e:
            logger.error(f"Не удалось отправить сообщение админу {admin_id}: {e}")

    # Ответ пользователю
    await update.message.reply_text(
        f"✅ Сообщение отправлено {success}/{len(ADMIN_IDS)} администраторам",
        reply_markup=ReplyKeyboardMarkup(create_main_menu_keyboard(user.id), resize_keyboard=True)
    )
    return ConversationHandler.END

# 3. Отправка личного сообщения
async def send_personal_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        
        if text.lower() == "отмена":
            await update.message.reply_text(
                "Отправка отменена",
                reply_markup=create_admin_keyboard()
            )
            return ADMIN_MESSAGE
        
        recipient = context.user_data.get('recipient')
        is_username = context.user_data.get('is_username')
        
        if is_username:
            db.cursor.execute(
                "SELECT telegram_id FROM users WHERE username = ?",
                (recipient,)
            )
        else:
            db.cursor.execute(
                "SELECT telegram_id FROM users WHERE telegram_id = ?",
                (recipient,)
            )
        
        user = db.cursor.fetchone()
        if not user:
            raise ValueError("Пользователь не найден")
        
        await context.bot.send_message(
            chat_id=user[0],
            text=f"✉️ Сообщение от администратора:\n\n{text}"
        )
        
        await update.message.reply_text(
            f"✅ Сообщение отправлено пользователю {'@' + recipient if is_username else recipient}",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
        
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        await update.message.reply_text(
            f"❌ Ошибка: {e}\nПопробуйте начать заново",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
    
# 4. Обработчик рассылки
async def handle_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip()
        
        if text.lower() == "отмена":
            await update.message.reply_text(
                "Рассылка отменена",
                reply_markup=create_admin_keyboard()
            )
            return ADMIN_MESSAGE
        
        db.cursor.execute("SELECT telegram_id FROM users WHERE is_verified = TRUE")
        users = db.cursor.fetchall()
        
        success = 0
        for user in users:
            try:
                await context.bot.send_message(
                    chat_id=user[0],
                    text=f"📢 Рассылка от администратора:\n\n{text}"
                )
                success += 1
                await asyncio.sleep(0.1)  # Задержка между сообщениями
            except Exception as e:
                logger.error(f"Не удалось отправить пользователю {user[0]}: {e}")
        
        await update.message.reply_text(
            f"✅ Рассылка завершена\nУспешно отправлено: {success}/{len(users)}",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}")
        await update.message.reply_text(
            f"❌ Ошибка рассылки: {e}",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
    
# 2. Обработчик выбора пользователя
async def select_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text.strip()
        
        if user_input.lower() == "отмена":
            await update.message.reply_text(
                "Действие отменено",
                reply_markup=create_admin_keyboard()
            )
            return ADMIN_MESSAGE
        
        # Сохраняем получателя
        if user_input.startswith('@'):
            context.user_data['recipient'] = user_input[1:]  # Убираем @
            context.user_data['is_username'] = True
        else:
            try:
                context.user_data['recipient'] = int(user_input)
                context.user_data['is_username'] = False
            except ValueError:
                raise ValueError("ID должен быть числом или укажите @username")
        
        await update.message.reply_text(
            "Введите сообщение для отправки (или 'отмена'):",
            reply_markup=ReplyKeyboardRemove()
        )
        return AWAIT_MESSAGE_TEXT
        
    except Exception as e:
        logger.error(f"Ошибка выбора пользователя: {e}")
        await update.message.reply_text(
            f"❌ Ошибка: {e}\nПопробуйте еще раз:",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
        )
        return SELECT_USER
    
async def handle_message_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text.strip()
        
        # Обработка отмены (регистронезависимая)
        if user_input.lower() == "отмена":
            await update.message.reply_text(
                "Отправка сообщения отменена",
                reply_markup=create_admin_keyboard()
            )
            return ADMIN_MESSAGE
        
        # Получаем сохраненные данные
        recipient = context.user_data.get('message_recipient')
        is_username = context.user_data.get('is_username')
        
        if not recipient:
            raise ValueError("Не выбран получатель")
        
        # Ищем пользователя
        if is_username:
            db.cursor.execute(
                "SELECT telegram_id, username FROM users WHERE username = ?",
                (recipient,)
            )
        else:
            db.cursor.execute(
                "SELECT telegram_id, username FROM users WHERE telegram_id = ?",
                (recipient,)
            )
        
        user_data = db.cursor.fetchone()
        if not user_data:
            raise ValueError("Пользователь не найден в базе")
        
        # Отправляем сообщение
        await context.bot.send_message(
            chat_id=user_data[0],
            text=f"✉️ Сообщение от администратора:\n\n{update.message.text}"
        )
        
        await update.message.reply_text(
            f"✅ Сообщение отправлено пользователю {'@' + user_data[1] if user_data[1] else user_data[0]}",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
        
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        await update.message.reply_text(
            f"❌ Ошибка: {e}\nПопробуйте начать заново",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
    
# 1. Обработчик меню администратора
async def handle_admin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    user = update.effective_user
    
    if text == "написать пользователю":
        await update.message.reply_text(
            "Введите ID пользователя или @username:",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
        )
        return SELECT_USER
    
    elif text == "сделать рассылку":
        await update.message.reply_text(
            "Введите сообщение для рассылки:",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
        )
        return BROADCAST_MESSAGE
    
    elif text == "отмена":
        await update.message.reply_text(
            "Действие отменено",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE
    
    elif text in ["📊 отчет за день", "отчет за день"]:
        await export_accounting_report(update, context)
        return ADMIN_MESSAGE
    
    elif text in ["📅 отчет за месяц", "отчет за месяц"]:
        await update.message.reply_text(
            "Выберите период:",
            reply_markup=create_month_selection_keyboard()
        )
        return SELECT_MONTH_RANGE
    
    await update.message.reply_text(
        "Пожалуйста, используйте кнопки меню",
        reply_markup=create_admin_keyboard()
    )
    return ADMIN_MESSAGE

# Добавьте в конец файла
async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Старая функция для совместимости"""
    return await start_admin_message(update, context)