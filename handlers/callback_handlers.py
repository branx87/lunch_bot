# ##handlers/callback_handlers.py
import logging
from telegram.ext import ContextTypes
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from datetime import datetime, time, timedelta
from config import CONFIG, LOCATIONS, TIMEZONE, MENU, ADMIN_IDS
from db import db
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters
import sqlite3

from handlers.common import show_main_menu
from handlers.common_handlers import view_orders
from handlers.order_callbacks import handle_cancel_callback, handle_change_callback, handle_confirm_callback, handle_order_callback, modify_portion_count
from utils import can_modify_order
from view_utils import refresh_day_view

logger = logging.getLogger(__name__)
        
async def handle_quantity_change(query, now, user, context):
    """
    Обработчик изменения количества порций в заказе.
    Выполняет:
    - Увеличение/уменьшение количества порций с проверкой лимитов
    - Автоматическую отмену заказа при уменьшении до 0 порций
    - Проверку временного окна для изменений (до 9:30)
    - Обновление представления дня через refresh_day_view
    """
    try:
        action, day_offset_str = query.data.split("_", 1)
        day_offset = int(day_offset_str)
        target_date = (now + timedelta(days=day_offset)).date()
        max_portions = 3  # Ваша константа

        # Проверка времени (ваша существующая проверка)
        if not can_modify_order(target_date):
            await query.answer("ℹ️ Изменение невозможно после 9:30", show_alert=True)
            return

        # Получаем ID пользователя (ваш существующий код)
        db.cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user.id,))
        user_record = db.cursor.fetchone()
        if not user_record:
            await query.answer("❌ Пользователь не найден", show_alert=True)
            return
        user_db_id = user_record[0]

        # Получаем текущее количество (ваш код)
        db.cursor.execute("""
            SELECT quantity 
            FROM orders 
            WHERE user_id = ?
              AND target_date = ?
              AND is_cancelled = FALSE
        """, (user_db_id, target_date.isoformat()))
        result = db.cursor.fetchone()
        if not result:
            await query.answer("❌ Заказ не найден", show_alert=True)
            return
        current_quantity = result[0]

        # Логика изменения (основана на вашей реализации)
        if action == "increase":
            if current_quantity >= max_portions:
                await query.answer("ℹ️ Максимальное количество порций (3) достигнуто", show_alert=True)
                return
            new_quantity = current_quantity + 1
            feedback = f"✅ Увеличено до {new_quantity} порций"
            
        elif action == "decrease":
            if current_quantity <= 1:
                # Ваш код отмены заказа
                with db.conn:
                    db.cursor.execute("""
                        UPDATE orders
                        SET is_cancelled = TRUE,
                            order_time = ?
                        WHERE user_id = ?
                          AND target_date = ?
                          AND is_cancelled = FALSE
                    """, (now.strftime("%H:%M:%S"), user_db_id, target_date.isoformat()))
                
                days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
                day_name = days_ru[target_date.weekday()]
                
                await query.edit_message_text(
                    text=f"❌ Заказ на {day_name} отменён",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("✅ Заказать", callback_data=f"order_{day_offset}")]
                    ])
                )
                await query.answer("ℹ️ Заказ отменён")
                return
                
            new_quantity = current_quantity - 1
            feedback = f"✅ Уменьшено до {new_quantity} порций"
            
        else:
            await query.answer("⚠️ Неизвестное действие")
            return

        # Обновляем количество (ваш код)
        with db.conn:
            db.cursor.execute("""
                UPDATE orders
                SET quantity = ?,
                    order_time = ?
                WHERE user_id = ?
                  AND target_date = ?
                  AND is_cancelled = FALSE
            """, (new_quantity, now.strftime("%H:%M:%S"), user_db_id, target_date.isoformat()))

        # Используем refresh_day_view вместо прямого редактирования
        await refresh_day_view(query, day_offset, user_db_id, now)
        await query.answer(feedback)

    except Exception as e:
        logger.error(f"Ошибка изменения количества ({action}): {e}")
        await query.answer("⚠️ Ошибка изменения. Попробуйте позже", show_alert=True)

# --- Callback для отмены заказа ---

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Главный обработчик callback-запросов. Распределяет обработку по типам действий:
    - Изменение количества порций (увеличение/уменьшение)
    - Изменение, отмена, подтверждение заказов
    - Создание новых заказов
    - Навигационные команды (возврат в меню, обновление)
    Логирует неизвестные callback-запросы
    """
    query = update.callback_query
    await query.answer()
    now = datetime.now(TIMEZONE)
    user = update.effective_user
    
    try:
        if query.data.startswith("inc_"):
            await modify_portion_count(query, now, user, context, +1)
        elif query.data.startswith("dec_"):
            await modify_portion_count(query, now, user, context, -1)
        elif query.data.startswith("change_"):
            await handle_change_callback(query, now, user, context)
        elif query.data.startswith("cancel_"):
            await handle_cancel_callback(query, now, user, context)
        elif query.data.startswith("confirm_"):
            await handle_confirm_callback(query, now, user, context)
        elif query.data.startswith("order_"):
            await handle_order_callback(query, now, user, context)
        elif query.data == "back_to_menu":
            await show_main_menu(query.message, user.id)
        elif query.data == "noop":
            await query.answer()  # Пустое действие
        elif query.data == "refresh":
            pass  # Логика обновления, если нужно
        else:
            logger.warning(f"Неизвестный callback: {query.data}")
            await query.answer("⚠️ Неизвестная команда")

    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}", exc_info=True)
        try:
            await query.answer("⚠️ Произошла ошибка. Попробуйте позже")
        except Exception as inner_e:
            logger.error(f"Ошибка при обработке callback: {inner_e}")
    
async def handle_cancel_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработчик отмены конкретного заказа. Выполняет:
    - Проверку возможности отмены (временное окно до 9:30)
    - Обновление статуса заказа в базе данных
    - Визуальное подтверждение отмены
    - Обновление списка заказов пользователя
    """
    query = update.callback_query
    await query.answer()
    
    try:
        # Получаем дату из callback_data
        target_date_str = query.data.split('_')[1]
        
        # Парсим дату (поддерживаем оба формата: YYYY-MM-DD и смещение дней)
        if '-' in target_date_str:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            day_offset = (target_date - datetime.now(TIMEZONE).date()).days
        else:
            day_offset = int(target_date_str)
            target_date = (datetime.now(TIMEZONE) + timedelta(days=day_offset)).date()
        
        # Проверяем можно ли отменять заказ
        if not can_modify_order(target_date):
            await query.answer("ℹ️ Отмена невозможна после 9:30", show_alert=True)
            return

        # Отменяем заказ
        user_id = query.from_user.id
        db.cursor.execute("""
            UPDATE orders 
            SET is_cancelled = TRUE 
            WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
            AND target_date = ?
            AND is_cancelled = FALSE
        """, (user_id, target_date.isoformat()))
        db.conn.commit()

        if db.cursor.rowcount == 0:
            await query.answer("❌ Заказ не найден или уже отменен", show_alert=True)
            return

        logger.info(f"Пользователь {user_id} отменил заказ на {target_date}")
        
        # Обновляем интерфейс
        await view_orders(update, context, is_cancellation=True)
        await query.answer(f"✅ Заказ на {target_date.strftime('%d.%m')} отменён")

    except Exception as e:
        logger.error(f"Ошибка при отмене заказа: {e}")
        await query.answer("⚠️ Ошибка при отмене заказа", show_alert=True)

async def handle_back_callback(query, now, user, context):
    """
    Обработчик кнопки 'Назад'. 
    Обновляет представление дня через refresh_day_view,
    возвращая пользователя к предыдущему состоянию интерфейса.
    """
    try:
        _, day_offset_str = query.data.split("_", 1)
        day_offset = int(day_offset_str)
        await refresh_day_view(query, day_offset, context.user_data['user_db_id'], now)
        await query.answer("Возврат к меню")
    except Exception as e:
        logger.error(f"Ошибка в handle_back_callback: {e}")
        await query.answer("⚠️ Ошибка возврата", show_alert=True)
