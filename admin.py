import openpyxl
from datetime import datetime, date, timedelta
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes
from config import CONFIG, TIMEZONE, LOCATIONS  # Импортируем LOCATIONS из config
from db import db
import logging
from keyboards import create_main_menu_keyboard
from openpyxl.styles import Font
import sqlite3
from handlers.constants import (
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
from handlers.common import show_main_menu
from typing import Optional, Union, List, Dict, Any, Tuple, Callable
import os
from openpyxl import Workbook
from openpyxl.styles import Font

SELECT_MONTH_RANGE = "SELECT_MONTH_RANGE"

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
        reports_dir = ensure_reports_dir('provider')

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

        for loc in sorted(LOCATIONS):  # Используем LOCATIONS из config
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
        unique_locations = [row[0] for row in db.cursor.fetchall() if row[0] in LOCATIONS]
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
        timestamp = datetime.now(TIMEZONE).strftime("%Y%m%d_%H%M%S")
        file_name = f"provider_report_{timestamp}.xlsx"
        file_path = os.path.join(reports_dir, file_name)
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
                caption=caption,
                filename=file_name
            )

        return file_path

    except Exception as e:
        logger.error(f"Ошибка при создании отчета для поставщика: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при формировании отчёта.")
        raise

async def export_accounting_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    """Генерация детализированного отчета для бухгалтерии"""
    try:
        reports_dir = ensure_reports_dir('accounting')
        now = datetime.now(TIMEZONE)
        
        # Обработка дат
        if not start_date or not end_date:
            start_date = end_date = now.date()
        else:
            start_date = start_date if isinstance(start_date, date) else start_date.date()
            end_date = end_date if isinstance(end_date, date) else end_date.date()

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        # Создаем Excel файл
        wb = Workbook()
        
        # 1. Лист "Детализация"
        ws_detailed = wb.active
        ws_detailed.title = "Детализация"
        detailed_headers = ["ФИО", "Объект", "Дата заказа", "Время заказа", "Дата обеда", "Количество", "Тип заказа"]
        ws_detailed.append(detailed_headers)
        ws_detailed.auto_filter.ref = "A1:G1"
        
        # Получаем данные (только неотмененные заказы)
        query = '''
            SELECT 
                u.full_name,
                u.location,
                date(o.created_at) as order_date,
                time(o.created_at) as order_time,
                o.target_date,
                o.quantity,
                CASE WHEN o.is_preliminary THEN 'Предзаказ' ELSE 'Обычный' END
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
              AND u.is_deleted = FALSE
            ORDER BY o.target_date, u.full_name
        '''
        db.cursor.execute(query, (start_date.isoformat(), end_date.isoformat()))
        
        total_portions = 0
        orders_count = 0
        for row in db.cursor.fetchall():
            order_date = datetime.strptime(row[2], "%Y-%m-%d").strftime("%d.%m.%Y")
            target_date = datetime.strptime(row[4], "%Y-%m-%d").strftime("%d.%m.%Y")
            ws_detailed.append([
                row[0], row[1], order_date, row[3], target_date, row[5], row[6]
            ])
            total_portions += row[5]
            orders_count += 1

        # 2. Лист "Сводка по сотрудникам"
        ws_summary_users = wb.create_sheet("Сводка по сотрудникам")
        summary_headers = ["ФИО", "Объект", "Всего порций"]
        ws_summary_users.append(summary_headers)
        ws_summary_users.auto_filter.ref = "A1:C1"
        
        db.cursor.execute('''
            SELECT 
                u.full_name,
                u.location,
                SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
            GROUP BY u.full_name, u.location
            ORDER BY SUM(o.quantity) DESC
        ''', (start_date.isoformat(), end_date.isoformat()))
        
        for row in db.cursor.fetchall():
            ws_summary_users.append(row)

        # 3. Лист "Сводка по объектам"
        ws_summary_locations = wb.create_sheet("Сводка по объектам")
        loc_headers = ["Объект", "Порции"]
        ws_summary_locations.append(loc_headers)
        ws_summary_locations.auto_filter.ref = "A1:B1"
        
        db.cursor.execute('''
            SELECT u.location, SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
            GROUP BY u.location
            ORDER BY SUM(o.quantity) DESC
        ''', (start_date.isoformat(), end_date.isoformat()))
        
        for row in db.cursor.fetchall():
            ws_summary_locations.append(row)
        ws_summary_locations.append(["ВСЕГО", total_portions])

        # 4. Лист "Итоги"
        ws_stats = wb.create_sheet("Итоги")
        stats_headers = ["Показатель", "Значение"]
        ws_stats.append(stats_headers)
        
        db.cursor.execute('''
            SELECT COUNT(DISTINCT u.id)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND ?
              AND o.is_cancelled = FALSE
        ''', (start_date.isoformat(), end_date.isoformat()))
        unique_users = db.cursor.fetchone()[0]

        stats_data = [
            ["Период", f"{start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}"],
            ["Всего заказов", orders_count],
            ["Всего порций", total_portions],
            ["Уникальных сотрудников", unique_users],
            ["Дата формирования", now.strftime("%d.%m.%Y %H:%M")]
        ]
        for row in stats_data:
            ws_stats.append(row)

        # Форматирование
        bold_font = Font(bold=True)
        for sheet in wb.worksheets:
            # Заголовки жирным
            for row in sheet.iter_rows(min_row=1, max_row=1):
                for cell in row:
                    cell.font = bold_font
            
            # Автоподбор ширины столбцов
            for col in sheet.columns:
                max_length = max(len(str(cell.value)) for cell in col)
                sheet.column_dimensions[col[0].column_letter].width = max_length + 2

        # Сохраняем файл
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        file_name = f"accounting_report_{timestamp}.xlsx"
        file_path = os.path.join(reports_dir, file_name)
        wb.save(file_path)

        # Отправляем файл
        caption = (
            f"📊 Бухгалтерский отчет\n"
            f"📅 Период: {start_date.strftime('%d.%m.%Y')} — {end_date.strftime('%d.%m.%Y')}\n"
            f"🍽 Всего порций: {total_portions}\n"
            f"👥 Уникальных сотрудников: {unique_users}"
        )

        with open(file_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=caption,
                filename=file_name
            )

        return file_path

    except Exception as e:
        logger.error(f"Ошибка формирования отчета: {e}", exc_info=True)
        await update.message.reply_text(
            "❌ Произошла ошибка при создании отчета. Подробности в логах."
        )
        raise

async def export_monthly_report(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None
):
    """Генерация административного отчёта с возможностью указания дат"""
    try:
        if update.effective_user.id not in CONFIG['admin_ids']:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        now = datetime.now(TIMEZONE)
        
        # Если даты не переданы - используем текущий месяц
        if not start_date or not end_date:
            month_start = now.replace(day=1).date()
            end_date = now.date()
        else:
            # Проверяем, что start_date <= end_date
            if start_date > end_date:
                start_date, end_date = end_date, start_date

        reports_dir = ensure_reports_dir('admin')
        now = datetime.now(TIMEZONE)
        month_start = now.replace(day=1).date()
        
        wb = Workbook()
        
        # Удаляем лист по умолчанию, если он есть
        if 'Sheet' in wb.sheetnames:
            del wb['Sheet']
        
        # Создаем листы для каждой локации
        for location in LOCATIONS:
            ws = wb.create_sheet(location)
            headers = ["Дата обеда", "Сотрудник", "Территориальный признак", "Подпись", "Кол-во обедов", "Тип заказа"]
            ws.append(headers)
            ws.auto_filter.ref = f"A1:F1"
            
            # Получаем данные для локации (только неотмененные заказы)
            db.cursor.execute('''
                SELECT 
                    o.target_date,
                    u.full_name,
                    u.location,
                    o.quantity,
                    CASE WHEN o.is_preliminary THEN 'Предзаказ' ELSE 'Обычный' END
                FROM orders o
                JOIN users u ON o.user_id = u.id
                WHERE o.target_date BETWEEN ? AND date('now')
                  AND u.location = ?
                  AND o.is_cancelled = FALSE
                  AND u.is_deleted = FALSE
                ORDER BY o.target_date, u.full_name
            ''', (month_start.isoformat(), location))
            
            for row in db.cursor.fetchall():
                target_date = datetime.strptime(row[0], "%Y-%m-%d").strftime("%d.%m.%Y")
                ws.append([target_date, row[1], row[2], "", row[3], row[4]])  # Пустая колонка для подписи
        
        # Лист "Итоги"
        ws_summary = wb.create_sheet("Итоги")
        summary_headers = ["Локация", "Порции"]
        ws_summary.append(summary_headers)
        ws_summary.auto_filter.ref = "A1:B1"
        
        db.cursor.execute('''
            SELECT u.location, SUM(o.quantity)
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.target_date BETWEEN ? AND date('now')
              AND o.is_cancelled = FALSE
            GROUP BY u.location
            ORDER BY SUM(o.quantity) DESC
        ''', (month_start.isoformat(),))
        
        total = 0
        for location, portions in db.cursor.fetchall():
            ws_summary.append([location, portions])
            total += portions
        
        ws_summary.append(["ВСЕГО", total])
        
        # Форматирование
        bold_font = Font(bold=True)
        for sheet in wb.worksheets:
            # Заголовки жирным
            for row in sheet.iter_rows(min_row=1, max_row=1):
                for cell in row:
                    cell.font = bold_font
            
            # Автоподбор ширины столбцов
            for col in sheet.columns:
                max_length = max(len(str(cell.value)) for cell in col)
                sheet.column_dimensions[col[0].column_letter].width = max_length + 2

        # Сохраняем файл
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        file_name = f"admin_report_{timestamp}.xlsx"
        file_path = os.path.join(reports_dir, file_name)
        wb.save(file_path)
        
        with open(file_path, 'rb') as file:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=file,
                caption=f"📅 Админ отчет за {month_start.strftime('%B %Y')}\n"
                       f"🍽 Всего порций: {total}",
                filename=file_name
            )

    except Exception as e:
        logger.error(f"Ошибка формирования админ отчёта: {e}")
        await update.message.reply_text("❌ Ошибка формирования отчёта")

# Остальные функции (message_history, handle_export_orders_for_month) остаются без изменений

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