# ##handlers/admin_handlers.py
import logging
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ConversationHandler, MessageHandler
from telegram.ext import ContextTypes
import asyncio

from config import CONFIG
from constants import BROADCAST_MESSAGE
from keyboards import create_admin_keyboard

logger = logging.getLogger(__name__)

async def handle_admin_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Основной обработчик выбора в админ-меню. 
    Проверяет права пользователя и перенаправляет на соответствующие действия:
    - Рассылка сообщений
    - Генерация отчетов (закомментировано)
    - Обработка отмены операций
    Возвращает состояние для продолжения диалога или завершает его.
    """
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

    # elif text in ["📊 отчет за день", "отчет за день"]:
    #     if user.id in CONFIG.get('admin_ids', []) or user.id in CONFIG.get('accounting_ids', []):
    #         await export_accounting_report(update, context)
    #     else:
    #         await update.message.reply_text("❌ У вас нет прав для просмотра отчетов")
    #     return ConversationHandler.END  # Заменили ADMIN_MESSAGE

    # elif text in ["📅 отчет за месяц", "отчет за месяц"]:
    #     if user.id in CONFIG.get('admin_ids', []) or user.id in CONFIG.get('accounting_ids', []):
    #         await update.message.reply_text(
    #             "Выберите период:",
    #             reply_markup=create_month_selection_keyboard()
    #         )
    #         return SELECT_MONTH_RANGE
    #     else:
    #         await update.message.reply_text("❌ У вас нет прав для просмотра отчетов")
    #     return ConversationHandler.END  # Заменили ADMIN_MESSAGE

    # Неизвестная команда
    await update.message.reply_text(
        "Неизвестная команда. Пожалуйста, используйте кнопки меню.",
        reply_markup=create_admin_keyboard()
    )
    return ConversationHandler.END  # Заменили ADMIN_MESSAGE
