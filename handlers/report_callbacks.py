# ##handlers/report_callbacks.py
from telegram import Update
from telegram.ext import CallbackQueryHandler
from telegram.ext import ContextTypes
from datetime import date, datetime, timedelta
import logging

from config import CONFIG, TIMEZONE
from constants import SELECT_MONTH_RANGE
from handlers.common import show_main_menu
from report_generators import export_accounting_report, export_monthly_report, export_orders_for_provider

logger = logging.getLogger(__name__)

async def select_month_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор периода для генерации отчетов.
    Определяет временной диапазон (текущий/прошлый месяц) и тип отчета.
    В зависимости от прав пользователя вызывает соответствующий генератор отчетов.
    """
    try:
        user = update.effective_user
        text = update.message.text
        
        if text == "Вернуться в главное меню":
            return await show_main_menu(update, user.id)

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
            await update.message.reply_text("❌ Пожалуйста, выберите период из предложенных вариантов")
            return SELECT_MONTH_RANGE

        report_type = context.user_data.get('report_type')
        
        try:
            if report_type == 'admin':
                await export_monthly_report(update, context, start_date, end_date)
            elif report_type == 'accounting':
                await export_accounting_report(update, context, start_date, end_date)
            elif report_type == 'provider':
                await export_orders_for_provider(update, context, start_date, end_date)
            else:
                await update.message.reply_text("❌ Неизвестный тип отчета")
        except Exception as e:
            logger.error(f"Ошибка генерации отчета {report_type}: {e}", exc_info=True)
            await update.message.reply_text("❌ Ошибка при формировании отчета")

        return await show_main_menu(update, user.id)
        
    except Exception as e:
        logger.error(f"Ошибка в select_month_range: {e}", exc_info=True)
        await update.message.reply_text("❌ Произошла ошибка при формировании отчета")
        return await show_main_menu(update, user.id)

async def generate_report(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                         user_id: int, start_date: date, end_date: date):
    """
    Генерирует отчеты в зависимости от роли пользователя:
    - Администраторы получают полный отчет (export_monthly_report)
    - Бухгалтеры - бухгалтерский отчет (export_accounting_report)
    - Поставщики - отчет по заказам (export_orders_for_provider)
    Обрабатывает ошибки генерации отчетов.
    """
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