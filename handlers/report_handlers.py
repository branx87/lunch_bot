import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from .common import show_main_menu
from .states import SELECT_MONTH_RANGE
from .base_handlers import show_main_menu
from admin import export_orders_for_provider, export_accounting_report
from config import TIMEZONE, CONFIG
from keyboards import create_main_menu_keyboard

logger = logging.getLogger(__name__)

async def handle_admin_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 Отчет за день":
        await export_accounting_report(update, context)  # Детализированный
    elif text == "📅 Отчет за месяц":
        # Показываем клавиатуру выбора месяца
        await update.message.reply_text(
            "Выберите период:",
            reply_markup=ReplyKeyboardMarkup([
                ["Текущий месяц", "Прошлый месяц"],
                ["Отмена"]
            ], resize_keyboard=True)
        )
        return SELECT_MONTH_RANGE

async def select_month_range(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user
        user_id = user.id
        text = update.message.text
        
        # Убираем дублирующуюся проверку в начале
        if text == "Вернуться в главное меню":
            return await show_main_menu(update, user_id)

        # Исправлено: используем user_id вместо user.id
        logger.info(f"User ID: {user_id}")
        logger.info(f"Admin IDs: {CONFIG['admin_ids']}")
        logger.info(f"Provider IDs: {CONFIG['provider_ids']}")
        logger.info(f"Accounting IDs: {CONFIG['accounting_ids']}")
        logger.info(f"Обработка периода: {text}, report_type: {context.user_data.get('report_type')}")

        # Определяем клавиатуру один раз
        reply_markup = ReplyKeyboardMarkup(
            [["Текущий месяц", "Прошлый месяц"], 
             ["Вернуться в главное меню"]],
            resize_keyboard=True
        )

        # Проверяем валидность ввода
        if text not in ["Текущий месяц", "Прошлый месяц"]:
            await update.message.reply_text(
                "Пожалуйста, выберите период:",
                reply_markup=reply_markup
            )
            return SELECT_MONTH_RANGE

        # Получаем тип отчета
        report_type = context.user_data.get('report_type')
        if not report_type:
            await update.message.reply_text(
                "Ошибка: тип отчета не определен",
                reply_markup=ReplyKeyboardRemove()
            )
            return await show_main_menu(update, user_id)

        logger.info(f"Обработка выбора периода: {text}")

        # Определяем даты
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
            # Этот else технически недостижим из-за предыдущей проверки
            await update.message.reply_text("Неизвестный период")
            return await show_main_menu(update, user_id)

        logger.info(f"Формирование отчета {report_type} за {start_date} - {end_date}")

        # Формируем отчет
        try:
            if report_type == 'provider':
                await export_orders_for_provider(update, context, start_date, end_date)
            else:
                await export_accounting_report(update, context, start_date, end_date)
        except Exception as e:
            logger.error(f"Ошибка формирования отчета: {e}")
            await update.message.reply_text(
                "❌ Не удалось сформировать отчет",
                reply_markup=ReplyKeyboardMarkup(
                    create_main_menu_keyboard(user_id),  # Используем user_id
                    resize_keyboard=True
                )
            )
            return await show_main_menu(update, user_id)  # Добавлен return

        return await show_main_menu(update, user_id)

    except Exception as e:
        logger.error(f"Критическая ошибка в select_month_range: {e}", exc_info=True)
        await update.message.reply_text("⚠️ Произошла системная ошибка")
        return await show_main_menu(update, user_id)