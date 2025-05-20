# ##handlers/common.py
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ConversationHandler
from telegram.ext import ContextTypes  # вместо ContextType
import logging

from constants import MAIN_MENU
from db import db
from keyboards import create_main_menu_keyboard, create_unverified_user_keyboard


logger = logging.getLogger(__name__)

async def show_main_menu(update: Update, user_id: int):
    """Общая функция для показа главного меню"""
    try:
        db.cursor.execute("SELECT is_verified FROM users WHERE telegram_id = ?", (user_id,))
        result = db.cursor.fetchone()

        if not result or not result[0]:
            # Пользователь не зарегистрирован
            reply_markup = create_unverified_user_keyboard()
        else:
            # Пользователь зарегистрирован
            reply_markup = create_main_menu_keyboard(user_id)

        if isinstance(update, Update) and update.message:
            await update.message.reply_text("Главное меню:", reply_markup=reply_markup)
        return MAIN_MENU 

    except Exception as e:
        logger.error(f"Ошибка в show_main_menu: {e}", exc_info=True)
        if isinstance(update, Update) and update.message:
            await update.message.reply_text(
                "⚠️ Произошла ошибка. Попробуйте снова.",
                reply_markup=ReplyKeyboardRemove()
            )
        return ConversationHandler.END
