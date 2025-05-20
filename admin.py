# ##admin.py
import openpyxl
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import CallbackContext
from telegram.ext import ContextTypes
import logging

from config import CONFIG
from constants import ADMIN_MESSAGE, MAIN_MENU, SELECT_MONTH_RANGE
from db import db
from keyboards import create_admin_keyboard
try:
    from openpyxl.styles import Font
except RuntimeError:  # Для окружений без GUI
    class Font:
        def __init__(self, bold=False):
            self.bold = bold
import sqlite3
from typing import Optional, Union, List, Dict, Any, Tuple, Callable
import os
from openpyxl import Workbook
from openpyxl.styles import Font

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log'
)
logger = logging.getLogger(__name__)

def ensure_reports_dir(report_type: str = 'accounting') -> str:
    """Создает папку для отчетов если ее нет и возвращает путь к ней"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    if report_type == 'provider':
        reports_dir = os.path.join(base_dir, 'reports', 'provider_reports')
    elif report_type == 'admin':
        reports_dir = os.path.join(base_dir, 'reports', 'admin_reports')
    else:
        reports_dir = os.path.join(base_dir, 'reports', 'accounting_reports')
    
    os.makedirs(reports_dir, exist_ok=True)
    
    # Очищаем старые отчеты (оставляем 5 последних)
    report_files = sorted(
        [f for f in os.listdir(reports_dir) if f.endswith('.xlsx')],
        key=lambda x: os.path.getmtime(os.path.join(reports_dir, x)),
        reverse=True
    )
    for old_file in report_files[5:]:
        try:
            os.remove(os.path.join(reports_dir, old_file))
        except Exception as e:
            logger.error(f"Ошибка удаления старого отчета {old_file}: {e}")
    
    return reports_dir

# Остальные функции (message_history, handle_export_orders_for_month) остаются без изменений

async def message_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ истории сообщений админам"""
    user = update.effective_user
    logger.info(f"Запрос истории сообщений от {user.id}")

    if user.id not in CONFIG.get('admin_ids', []):
        await update.message.reply_text(
            "❌ У вас нет прав для просмотра истории сообщений.",
            reply_markup=create_admin_keyboard()
        )
        return ADMIN_MESSAGE

    try:
        # Получаем последние 20 сообщений
        db.cursor.execute("""
            SELECT 
                m.sent_at, 
                a.full_name AS admin_name,
                u.full_name AS user_name,
                m.message_text,
                CASE WHEN m.admin_id IS NOT NULL THEN 'admin_to_user' ELSE 'user_to_admin' END AS direction
            FROM admin_messages m
            LEFT JOIN users a ON m.admin_id = a.telegram_id
            LEFT JOIN users u ON m.user_id = u.telegram_id
            ORDER BY m.sent_at DESC 
            LIMIT 20
        """)
        messages = db.cursor.fetchall()

        if not messages:
            await update.message.reply_text(
                "📭 История сообщений пуста",
                reply_markup=create_admin_keyboard()
            )
            return ADMIN_MESSAGE

        # Формируем ответ с разбивкой на части (из-за ограничения длины в Telegram)
        responses = ["📜 Последние 20 сообщений:\n\n"]
        current_length = len(responses[0])
        
        for msg in messages:
            sent_at, admin_name, user_name, message_text, direction = msg
            
            # Форматируем сообщение в зависимости от направления
            if direction == 'admin_to_user':
                msg_text = (
                    f"⬇️ Отправлено: {sent_at}\n"
                    f"👨‍💼 Админ: {admin_name or 'Система'}\n"
                    f"👤 Пользователь: {user_name or 'Неизвестно'}\n"
                    f"📝 Сообщение: {message_text}\n"
                )
            else:
                msg_text = (
                    f"⬆️ Получено: {sent_at}\n"
                    f"👤 Пользователь: {user_name or 'Неизвестно'}\n"
                    f"📝 Сообщение: {message_text}\n"
                )
            
            msg_text += "━━━━━━━━━━━━━━\n"
            
            # Проверяем, не превысим ли лимит
            if current_length + len(msg_text) > 4000:
                responses.append(msg_text)
                current_length = len(msg_text)
            else:
                responses[-1] += msg_text
                current_length += len(msg_text)

        # Отправляем все части
        for response in responses:
            await update.message.reply_text(
                response,
                reply_markup=create_admin_keyboard()
            )
            
    except Exception as e:
        logger.error(f"Ошибка при выводе истории: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Не удалось загрузить историю сообщений",
            reply_markup=create_admin_keyboard()
        )
    
    return ADMIN_MESSAGE

async def handle_export_orders_for_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка нажатия кнопки 'Выгрузить заказы за месяц'"""
    if update.effective_user.id not in CONFIG['provider_ids']:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return MAIN_MENU

    keyboard = [["Текущий месяц"], ["Прошлый месяц"], ["Вернуться в главное меню"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Выберите период для выгрузки:", reply_markup=reply_markup)
    return SELECT_MONTH_RANGE
    
def _check_access(user_id: int, report_type: str) -> bool:
    """Проверка прав доступа к отчету"""
    if report_type == 'admin' and user_id in CONFIG['admin_ids']:
        return True
    if report_type == 'provider' and user_id in CONFIG['provider_ids']:
        return True
    if report_type == 'accounting' and user_id in CONFIG['accounting_ids']:
        return True
    return False