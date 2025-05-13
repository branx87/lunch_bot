import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, MessageHandler
from config import CONFIG
from keyboards import create_admin_keyboard, create_month_selection_keyboard
from admin import export_accounting_report
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
from db import db
import asyncio

logger = logging.getLogger(__name__)

async def handle_admin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка выбора в админ-меню"""
    text = update.message.text.strip().lower()
    user = update.effective_user

    # Проверка прав администратора
    if user.id not in CONFIG.get('admin_ids', []) and user.id not in CONFIG.get('accounting_ids', []):
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return ConversationHandler.END  # Заменили ADMIN_MESSAGE на завершение диалога

    if text == "📢 Сделать рассылку":
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
        return ConversationHandler.END  # Заменили ADMIN_MESSAGE

    elif text in ["📊 отчет за день", "отчет за день"]:
        if user.id in CONFIG.get('admin_ids', []) or user.id in CONFIG.get('accounting_ids', []):
            await export_accounting_report(update, context)
        else:
            await update.message.reply_text("❌ У вас нет прав для просмотра отчетов")
        return ConversationHandler.END  # Заменили ADMIN_MESSAGE

    elif text in ["📅 отчет за месяц", "отчет за месяц"]:
        if user.id in CONFIG.get('admin_ids', []) or user.id in CONFIG.get('accounting_ids', []):
            await update.message.reply_text(
                "Выберите период:",
                reply_markup=create_month_selection_keyboard()
            )
            return SELECT_MONTH_RANGE
        else:
            await update.message.reply_text("❌ У вас нет прав для просмотра отчетов")
        return ConversationHandler.END  # Заменили ADMIN_MESSAGE

    # Неизвестная команда
    await update.message.reply_text(
        "Неизвестная команда. Пожалуйста, используйте кнопки меню.",
        reply_markup=create_admin_keyboard()
    )
    return ConversationHandler.END  # Заменили ADMIN_MESSAGE