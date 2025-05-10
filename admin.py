import openpyxl
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes
from config import CONFIG, TIMEZONE
from db import db
import logging
from keyboards import create_main_menu_keyboard
from openpyxl.styles import Font
import sqlite3
from handlers.states import MAIN_MENU
from handlers.report_handlers import SELECT_MONTH_RANGE
from handlers.common import show_main_menu
from typing import Optional, Union, List, Dict, Any, Tuple, Callable
import os
from openpyxl import Workbook
from openpyxl.styles import Font
import logging

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='bot.log'
)
logger = logging.getLogger(__name__)

async def export_orders_for_provider(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    """
    Формирует Excel-файл с отчётом для поставщиков.
    Включает детализацию по дням и объектам.
    Учитываются только неотменённые заказы.
    """

    try:
        user = update.effective_user

        # Если даты не заданы — используем сегодняшнюю
        if not start_date or not end_date:
            today = datetime.now(TIMEZONE).date()
            start_date = end_date = today
        else:
            start_date = start_date if isinstance(start_date, date) else start_date.date()
            end_date = end_date if isinstance(end_date, date) else end_date.date()

        wb = openpyxl.Workbook()

        # 1. Лист "Заказы"
        ws_orders = wb.active
        ws_orders.title = "Заказы"
        orders_headers = ["Дата", "Локация", "Количество порций"]
        ws_orders.append(orders_headers)
        ws_orders.auto_filter.ref = "A1:C1"

        total_portions = 0

        # SQL-запрос: заказы по дням и локациям
        db.cursor.execute('''
            SELECT 
                o.target_date,
                u.location,
                SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
            GROUP BY o.target_date, u.location
            ORDER BY o.target_date, u.location
        ''', (start_date.isoformat(), end_date.isoformat()))

        for row in db.cursor.fetchall():
            formatted_date = datetime.strptime(row[0], "%Y-%m-%d").strftime("%d.%m.%Y")
            ws_orders.append([formatted_date, row[1], row[2]])
            total_portions += row[2]

        # 2. Лист "Сводка по объектам"
        valid_locations = {"Офис", "ПЦ 1", "ПЦ 2", "Склад"}
        ws_summary = wb.create_sheet("Сводка по объектам")
        summary_headers = ["Объект", "Количество порций"]
        ws_summary.append(summary_headers)
        ws_summary.auto_filter.ref = "A1:B1"

        # Получаем данные по локациям
        db.cursor.execute('''
            SELECT u.location, SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
            GROUP BY u.location
        ''', (start_date.isoformat(), end_date.isoformat()))

        location_data = dict(db.cursor.fetchall())

        for loc in sorted(valid_locations):
            portions = location_data.get(loc, 0)
            ws_summary.append([loc, portions])

        # 3. Лист "Итоги"
        ws_stats = wb.create_sheet("Итоги")
        stats_headers = ["Показатель", "Значение"]
        ws_stats.append(stats_headers)

        # Подсчёт уникальных локаций с заказами
        db.cursor.execute('''
            SELECT DISTINCT u.location
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
        ''', (start_date.isoformat(), end_date.isoformat()))
        unique_locations = [row[0] for row in db.cursor.fetchall() if row[0] in valid_locations]
        locations_count = len(unique_locations)

        stats_data = [
            ["Период", f"{start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}"],
            ["Всего порций", total_portions],
            ["Уникальных локаций", locations_count],
            ["Дата формирования", datetime.now(TIMEZONE).strftime("%d.%m.%Y %H:%M")]
        ]
        for row in stats_data:
            ws_stats.append(row)

        # Форматирование
        bold_font = Font(bold=True)
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(min_row=1, max_row=1):
                for cell in row:
                    cell.font = bold_font
            for column in sheet.columns:
                max_length = max((len(str(cell.value)) if cell.value else 0 for cell in column), default=0)
                adjusted_width = (max_length + 2) * 1.2
                sheet.column_dimensions[column[0].column_letter].width = adjusted_width

        # Сохраняем файл
        file_path = f"provider_report_{start_date.strftime('%Y%m%d')}"
        if start_date != end_date:
            file_path += f"_to_{end_date.strftime('%Y%m%d')}"
        file_path += ".xlsx"
        wb.save(file_path)

        # Отправляем файл
        caption = (
            f"🍽 Заказы на {start_date.strftime('%d.%m.%Y')}"
            f"{f' — {end_date.strftime('%d.%m.%Y')}' if start_date != end_date else ''}\n"
            f"📍 Локаций: {locations_count} | 🍛 Всего: {total_portions} порций\n"
            "📋 Детализация в приложенном файле"
        )

        with open(file_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=caption
            )

        return file_path

    except Exception as e:
        logger.error(f"Ошибка при создании отчета для поставщика: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при формировании отчёта.")
        raise

async def export_accounting_report(update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                 start_date=None, end_date=None):
    """Генерация отчёта с правильными датами"""
    try:
        now = datetime.now(TIMEZONE)
        
        # Если даты не указаны - отчёт за сегодня
        if not start_date or not end_date:
            start_date = now.date()
            end_date = now.date()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Заказы"
        
        # Заголовки
        headers = [
            "ФИО", "Объект", 
            "Дата заказа", "Время заказа",  # Когда сделан заказ
            "Дата обеда",                   # На какую дату заказ
            "Количество", "Тип заказа", 
            "Статус"
        ]
        ws.append(headers)

        # Получаем данные
        db.cursor.execute('''
            SELECT 
                u.full_name,
                u.location,
                date(o.created_at) as target_date,
                time(o.created_at) as order_time,
                o.target_date,
                o.quantity,
                CASE WHEN o.is_preliminary THEN 'Предзаказ' ELSE 'Обычный' END,
                CASE WHEN o.is_cancelled THEN 'Отменён' ELSE 'Активен' END
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE date(o.created_at) BETWEEN ? AND ?
            ORDER BY o.target_date, u.full_name
        ''', (start_date.isoformat(), end_date.isoformat()))

        for row in db.cursor.fetchall():
            # Форматируем даты для отчёта
            formatted_row = list(row)
            formatted_row[2] = datetime.strptime(row[2], "%Y-%m-%d").strftime("%d.%m.%Y")  # Дата заказа
            formatted_row[4] = datetime.strptime(row[4], "%Y-%m-%d").strftime("%d.%m.%Y")  # Дата обеда
            ws.append(formatted_row)

        # Сохраняем и отправляем файл
        file_path = f"report_{now.strftime('%Y%m%d_%H%M')}.xlsx"
        wb.save(file_path)
        
        with open(file_path, 'rb') as file:
            await update.message.reply_document(
                document=file,
                caption=f"Отчёт за период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
            )
            
    except Exception as e:
        logger.error(f"Ошибка формирования отчёта: {e}")
        await update.message.reply_text("❌ Ошибка при формировании отчёта")
        
# Добавьте эту новую функцию
async def export_orders_for_month(
    update: Update = None, 
    context: ContextTypes.DEFAULT_TYPE = None,
    start_date: date = None,
    end_date: date = None,
    month_offset: int = 0,
    send_to_providers: bool = False
):
    """
    Генерация отчета за месяц/период
    :param update: Объект Update (опционально)
    :param context: Контекст (опционально)
    :param start_date: Начальная дата (если None - будет месяц)
    :param end_date: Конечная дата (если None - будет месяц)
    :param month_offset: Смещение месяца (0 - текущий, -1 - предыдущий)
    :param send_to_providers: Отправлять ли отчет поставщикам
    :return: Путь к файлу или None при ошибке
    """
    try:
        now = datetime.now(TIMEZONE)
        
        # Определяем период
        if start_date is None or end_date is None:
            if month_offset == -1:  # Предыдущий месяц
                first_day = now.replace(day=1)
                start_date = (first_day - timedelta(days=1)).replace(day=1)
                end_date = first_day - timedelta(days=1)
            else:  # Текущий месяц
                start_date = now.replace(day=1)
                end_date = now
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Заказы"
        
        # Заголовки
        headers = ["Объект", "Количество порций"]
        ws.append(headers)
        
        # Получаем данные
        db.cursor.execute('''
            SELECT u.location, SUM(o.quantity) AS portions
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
            GROUP BY u.location
            ORDER BY portions DESC
        ''', (start_date.isoformat(), end_date.isoformat()))
        
        total = 0
        for location, portions in db.cursor.fetchall():
            ws.append([location, portions])
            total += portions
        
        ws.append(["ИТОГО", total])
        
        # Автоподбор ширины столбцов
        for col in ws.columns:
            max_len = max(len(str(cell.value)) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = (max_len + 2) * 1.2
        
        # Сохраняем файл
        if month_offset != 0:
            file_path = f"orders_report_{start_date.strftime('%Y-%m')}.xlsx"
        else:
            file_path = f"orders_report_{start_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.xlsx"
        wb.save(file_path)
        
        # Если вызывается из обработчика - отправляем отчет
        if update and context:
            if send_to_providers:
                success = 0
                with open(file_path, 'rb') as file:
                    for provider_id in CONFIG['provider_ids']:
                        try:
                            await context.bot.send_document(
                                chat_id=provider_id,
                                document=file,
                                caption=(
                                    f"🍽 Заказы за период {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
                                    f"📍 Локации | 🍛 Всего: {total} порций"
                                )
                            )
                            success += 1
                            file.seek(0)
                        except Exception as e:
                            logger.error(f"Ошибка отправки поставщику {provider_id}: {e}")
                
                await update.message.reply_text(
                    f"✅ Отчёт готов\n"
                    f"• Период: {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}\n"
                    f"• Порций: {total}\n"
                    f"• Отправлено: {success}/{len(CONFIG['provider_ids'])}"
                )
            else:
                with open(file_path, 'rb') as file:
                    await update.message.reply_document(
                        document=file,
                        caption=f"Отчет за период {start_date.strftime('%d.%m.%Y')} - {end_date.strftime('%d.%m.%Y')}"
                    )
            
            return await show_main_menu(update, update.effective_user.id)
        
        return file_path
        
    except Exception as e:
        logger.error(f"Ошибка формирования отчёта: {e}")
        if update:
            await update.message.reply_text("❌ Ошибка при создании отчёта")
            return await show_main_menu(update, update.effective_user.id)
        raise

async def export_monthly_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.effective_user.id not in CONFIG['admin_ids']:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        wb = openpyxl.Workbook()
        
        ws_detailed = wb.active
        ws_detailed.title = "Детализация"
        ws_detailed.append(["ФИО", "Локация", "Дата", "Порции", "Тип"])
        
        ws_summary = wb.create_sheet("Итоги")
        ws_summary.append(["Локация", "Порции"])
        
        month_start = datetime.now(TIMEZONE).replace(day=1).date()
        
        db.cursor.execute('''
            SELECT u.full_name, u.location, o.target_date, o.quantity, 
                   CASE WHEN o.is_preliminary THEN 'Предзаказ' ELSE 'Обычный' END
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND date('now')
            ORDER BY o.target_date, u.location
        ''', (month_start.isoformat(),))
        
        for row in db.cursor.fetchall():
            ws_detailed.append(row)
        
        db.cursor.execute('''
            SELECT u.location, SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND date('now')
            GROUP BY u.location
        ''', (month_start.isoformat(),))
        
        total = 0
        for location, portions in db.cursor.fetchall():
            ws_summary.append([location, portions])
            total += portions
        
        ws_summary.append(["ВСЕГО", total])
        
        for sheet in wb.worksheets:
            for col in sheet.columns:
                sheet.column_dimensions[col[0].column_letter].width = max(
                    len(str(cell.value)) * 1.2 for cell in col
                )

        file_path = f"monthly_report_{datetime.now(TIMEZONE).strftime('%Y-%m')}.xlsx"
        wb.save(file_path)
        
        with open(file_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=f"📅 Отчёт за {month_start.strftime('%B %Y')}\n"
                       f"🍽 Всего порций: {total}"
            )

    except Exception as e:
        logger.error(f"Ошибка месячного отчёта: {e}")
        await update.message.reply_text("❌ Ошибка формирования отчёта")

async def message_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ истории сообщений админам"""
    user = update.effective_user
    if user.id not in CONFIG.get('admin_ids', []):
        await update.message.reply_text("❌ У вас нет прав для просмотра истории сообщений.")
        return ADMIN_MESSAGE

    try:
        db.cursor.execute("""
            SELECT m.sent_at, u1.full_name AS admin, u2.full_name AS user, m.message_text
            FROM admin_messages m
            JOIN users u1 ON m.admin_id = u1.telegram_id
            LEFT JOIN users u2 ON m.user_id = u2.telegram_id
            ORDER BY m.sent_at DESC LIMIT 20
        """)
        messages = db.cursor.fetchall()

        if not messages:
            await update.message.reply_text("📜 История сообщений пуста")
            return ADMIN_MESSAGE

        response = "📜 Последние сообщения:\n\n"
        for msg in messages:
            sent_at, admin, user_name, message, *rest = msg
            user_part = f"👤 {user_name}" if user_name else "👥 Всем"
            response += f"🕒 {sent_at}\n🧑‍💼 Админ: {admin}\n{user_part}\n📝 Текст: {message}\n\n"

        await update.message.reply_text(response[:4096])
    except Exception as e:
        logger.error(f"Ошибка при выводе истории: {e}")
        await update.message.reply_text("❌ Не удалось загрузить историю сообщений")
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
