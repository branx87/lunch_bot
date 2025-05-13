# report_handlers.py
import logging
from datetime import date, datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from config import CONFIG, TIMEZONE
from keyboards import create_main_menu_keyboard
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

logger = logging.getLogger(__name__)

async def handle_report_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик запросов отчетов"""
    from admin import export_orders_for_provider, export_accounting_report, export_monthly_report
    user_id = update.effective_user.id
    text = update.message.text
    
    if text == "📊 Отчет за день":
        today = datetime.now(TIMEZONE).date()
        await generate_report(update, context, user_id, today, today)
    elif text == "📅 Отчет за месяц":
        await update.message.reply_text(
            "Выберите период:",
            reply_markup=ReplyKeyboardMarkup([
                ["Текущий месяц", "Прошлый месяц"],
                ["Вернуться в главное меню"]
            ], resize_keyboard=True)
        )
        return SELECT_MONTH_RANGE

async def select_month_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора периода"""
    from admin import export_orders_for_provider, export_accounting_report, export_monthly_report
    try:
        user_id = update.effective_user.id
        text = update.message.text
        
        if text == "Вернуться в главное меню":
            from .common import show_main_menu
            return await show_main_menu(update, user_id)

        now = datetime.now(TIMEZONE)
        if text == "Текущий месяц":
            start_date = now.replace(day=1).date()
            end_date = now.date()
        elif text == "Прошлый месяц":
            first_day = now.replace(day=1)
            last_day_prev_month = first_day - timedelta(days=1)
            start_date = last_day_prev_month.replace(day=1).date()
            end_date = last_day_prev_month.date()
        else:
            await update.message.reply_text("Пожалуйста, выберите период")
            return SELECT_MONTH_RANGE

        await generate_report(update, context, user_id, start_date, end_date)
        from .common import show_main_menu
        return await show_main_menu(update, user_id)
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Ошибка формирования отчета")
        from .common import show_main_menu
        return await show_main_menu(update, user_id)

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         user_id: int, start_date: date, end_date: date):
    """Генерация отчета"""
    from admin import export_orders_for_provider, export_accounting_report, export_monthly_report
    try:
        if user_id in CONFIG.get('admin_ids', []):
            await export_monthly_report(update, context, start_date, end_date)
        elif user_id in CONFIG.get('accounting_ids', []):
            await export_accounting_report(update, context, start_date, end_date)
        elif user_id in CONFIG.get('provider_ids', []):
            await export_orders_for_provider(update, context, start_date, end_date)
        else:
            await update.message.reply_text("❌ Нет прав")
    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка отчета")