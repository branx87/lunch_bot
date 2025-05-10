import logging
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from datetime import datetime, timedelta
from config import CONFIG, LOCATIONS, TIMEZONE, MENU, ADMIN_IDS
from db import db
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, filters, ContextTypes
from .states import MAIN_MENU
from .common import show_main_menu
from utils import can_modify_order, is_order_cancelled
from utils import format_menu
import sqlite3
from .menu_handlers import view_orders

logger = logging.getLogger(__name__)

async def handle_order_callback(query, now, user, context):
    """Оформление заказа с ручной проверкой дат"""
    try:
        # Парсим параметры из callback
        _, day_offset_str = query.data.split("_", 1)
        day_offset = int(day_offset_str)
        target_date = (now + timedelta(days=day_offset)).date()
        
        # Ручная проверка 1: Заказы на выходные не принимаются
        if target_date.weekday() >= 5:  # 5-6 = суббота-воскресенье
            await query.answer("ℹ️ Заказы на выходные не принимаются", show_alert=True)
            return

        # Ручная проверка 2: Предзаказы только на будущие даты
        if day_offset > 0 and target_date <= now.date():
            await query.answer("❌ Предзаказ можно сделать только на будущие даты", show_alert=True)
            return

        # Ручная проверка 3: Обычные заказы только на сегодня и до 9:30
        if day_offset == 0:
            if now.time() >= time(9, 30):
                await query.answer("ℹ️ Приём заказов на сегодня завершён в 9:30", show_alert=True)
                return

        # Получаем ID пользователя из БД
        db.cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user.id,))
        user_record = db.cursor.fetchone()
        if not user_record:
            await query.answer("❌ Пользователь не найден", show_alert=True)
            return
        user_db_id = user_record[0]

        # Проверяем существующий заказ
        db.cursor.execute("""
            SELECT quantity FROM orders 
            WHERE user_id = ? 
              AND target_date = ?
              AND is_cancelled = FALSE
        """, (user_db_id, target_date.isoformat()))
        existing_order = db.cursor.fetchone()

        if existing_order:
            await query.answer(f"ℹ️ У вас уже заказано {existing_order[0]} порций", show_alert=True)
            return

        # Создаём новый заказ
        with db.conn:
            db.cursor.execute("""
                INSERT INTO orders (
                    user_id,
                    target_date,
                    order_time,
                    quantity,
                    is_preliminary,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                user_db_id,
                target_date.isoformat(),
                now.strftime("%H:%M:%S"),  # Только время
                1,  # Количество порций
                day_offset > 0,  # Это предзаказ?
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Полная дата-время
            ))

        # Обновляем интерфейс
        await refresh_day_view(query, day_offset, user_db_id, now, is_order=True)
        await query.answer("✅ Заказ успешно оформлен")

    except Exception as e:
        logger.error(f"Ошибка при оформлении заказа: {e}", exc_info=True)
        await query.answer("⚠️ Произошла ошибка. Попробуйте позже", show_alert=True)

async def handle_change_callback(query, now, user, context):
    """Обработчик изменения количества порций с сохранением меню"""
    try:
        _, day_offset_str = query.data.split("_", 1)
        day_offset = int(day_offset_str)
        target_date = (now + timedelta(days=day_offset)).date()
        days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        day_name = days_ru[target_date.weekday()]
        menu = MENU.get(day_name)

        # Проверка возможности изменения
        if not can_modify_order(target_date):
            await query.answer("ℹ️ Изменение невозможно после 9:30", show_alert=True)
            return await refresh_day_view(query, day_offset, context.user_data['user_db_id'], now)

        # Получаем ID пользователя
        db.cursor.execute("SELECT id FROM users WHERE telegram_id = ?", (user.id,))
        user_db_id = db.cursor.fetchone()[0]
        context.user_data['user_db_id'] = user_db_id
        context.user_data['current_day_offset'] = day_offset

        # Получаем текущее количество порций
        db.cursor.execute("""
            SELECT quantity FROM orders 
            WHERE user_id = ? AND target_date = ? AND is_cancelled = FALSE
        """, (user_db_id, target_date.isoformat()))
        current_qty = db.cursor.fetchone()[0]

        # Формируем текст сообщения
        menu_text = (
            f"🍽 Меню на {day_name} ({target_date.strftime('%d.%m')}):\n"
            f"1. 🍲 Первое: {menu['first']}\n"
            f"2. 🍛 Основное блюдо: {menu['main']}\n"
            f"3. 🥗 Салат: {menu['salad']}\n\n"
            f"🛒 Текущий заказ: {current_qty} порции"
        )

        # Создаем клавиатуру
        keyboard = [
            [
                InlineKeyboardButton("➖ Уменьшить", callback_data=f"dec_{day_offset}"),
                InlineKeyboardButton("➕ Увеличить", callback_data=f"inc_{day_offset}")
            ],
            [InlineKeyboardButton("✔️ Подтвердить", callback_data=f"confirm_{day_offset}")],
            [InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_{day_offset}")]
        ]

        # Обновляем сообщение
        await query.edit_message_text(
            text=menu_text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        await query.answer()

    except Exception as e:
        logger.error(f"Ошибка в handle_change_callback: {e}", exc_info=True)
        await query.answer("⚠️ Ошибка изменения", show_alert=True)
        
async def handle_quantity_change(query, now, user, context):
    """Увеличение/уменьшение порций с проверкой времени и максимума"""
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
async def handle_cancel_callback(query, now, user, context):
    """Отмена заказа с улучшенной обработкой ошибок и безопасностью"""
    try:
        # Проверяем формат callback данных
        if not query.data or '_' not in query.data:
            logger.warning(f"Некорректный callback: {query.data}")
            await query.answer("⚠️ Ошибка в запросе")
            return

        # Разбираем данные callback
        _, date_part = query.data.split("_", 1)
        
        # Определяем дату заказа
        if '-' in date_part:  # Формат YYYY-MM-DD
            try:
                if len(date_part.split('-')) != 3:
                    raise ValueError
                    
                target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
                day_offset = (target_date - now.date()).days
            except ValueError:
                logger.error(f"Неверный формат даты в callback: {date_part}")
                await query.answer("⚠️ Ошибка в дате")
                return
                
        elif date_part.isdigit():  # Смещение дней
            day_offset = int(date_part)
            target_date = (now + timedelta(days=day_offset)).date()
        else:
            logger.error(f"Неизвестный формат даты: {query.data}")
            await query.answer("⚠️ Ошибка в запросе")
            return

        # Проверяем можно ли отменять заказ
        if not can_modify_order(target_date):
            await query.answer("ℹ️ Отмена невозможна после 9:30", show_alert=True)
            return

        # Получаем ID пользователя из БД
        db.cursor.execute(
            "SELECT id FROM users WHERE telegram_id = ? AND is_verified = TRUE",
            (user.id,)
        )
        user_record = db.cursor.fetchone()
        
        if not user_record:
            await query.answer("❌ Пользователь не найден", show_alert=True)
            return
            
        user_db_id = user_record[0]

        # Выполняем отмену заказа в транзакции
        with db.conn:
            db.cursor.execute("""
                UPDATE orders
                SET is_cancelled = TRUE,
                    order_time = ?
                WHERE user_id = ?
                  AND target_date = ?
                  AND is_cancelled = FALSE
                RETURNING id
            """, (now.strftime("%H:%M:%S"), user_db_id, target_date.isoformat()))
            
            # Проверяем что заказ был найден и отменен
            if not db.cursor.fetchone():
                await query.answer("❌ Заказ не найден", show_alert=True)
                return

        # Логируем отмену
        logger.info(
            f"Пользователь {user.id} отменил заказ на {target_date}"
        )

        # Обновляем интерфейс
        try:
            await refresh_day_view(query, day_offset, user_db_id, now)
            await query.answer("✅ Заказ отменён")
        except Exception as e:
            logger.error(f"Ошибка обновления интерфейса: {e}")
            await query.answer("⚠️ Заказ отменён, но возникла ошибка отображения")

    except Exception as e:
        logger.error(f"Критическая ошибка в handle_cancel_callback: {e}", exc_info=True)
        await query.answer("⚠️ Произошла ошибка. Попробуйте снова.", show_alert=True)

async def refresh_orders_view(query, context, user_id, now, days_ru):
    """Обновляет список заказов после изменения количества"""
    try:
        db.cursor.execute("""
            SELECT o.target_date, o.quantity, o.is_preliminary
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE u.telegram_id = ?
              AND o.is_cancelled = FALSE
              AND o.target_date >= ?
            ORDER BY o.target_date
        """, (user_id, now.date().isoformat()))

        active_orders = db.cursor.fetchall()

        if not active_orders:
            await query.edit_message_text("ℹ️ У вас нет активных заказов.")
            return await show_main_menu(query.message, user_id)

        response = "📦 Ваши активные заказы:\n"
        keyboard = []

        for order in active_orders:
            target_date = datetime.strptime(order[0], "%Y-%m-%d").date()
            day_name = days_ru[target_date.weekday()]
            date_str = target_date.strftime('%d.%m')
            qty = order[1]
            status = " (предварительный)" if order[2] else ""

            response += f"📅 {day_name} ({date_str}) - {qty} порций{status}\n"
            keyboard.append([
                InlineKeyboardButton(f"✏️ Изменить {date_str}", callback_data=f"change_{target_date.strftime('%Y-%m-%d')}"),
                InlineKeyboardButton(f"✕ Отменить {date_str}", callback_data=f"cancel_{target_date.strftime('%Y-%m-%d')}")
            ])

        keyboard.append([InlineKeyboardButton("✔ В главное меню", callback_data="back_to_menu")])

        await query.edit_message_text(
            response,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка обновления списка: {e}")
        await query.edit_message_text("⚠️ Ошибка загрузки заказов")

async def refresh_day_view(query, day_offset, user_db_id, now, is_order=False):
    """Обновляет меню дня с информацией о заказе"""
    try:
        days_ru = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        target_date = (now + timedelta(days=day_offset)).date()
        day_name = days_ru[target_date.weekday()]
        date_str = target_date.strftime("%d.%m")
        menu = MENU.get(day_name)

        # Формируем текст сообщения
        if not menu:
            response_text = f"📅 {day_name} ({date_str}) - выходной! Меню не предусмотрено."
        else:
            response_text = (
                f"🍽 Меню на {day_name} ({date_str}):\n"
                f"1. 🍲 Первое: {menu['first']}\n"
                f"2. 🍛 Основное блюдо: {menu['main']}\n"
                f"3. 🥗 Салат: {menu['salad']}"
            )

        # Проверяем заказ пользователя
        db.cursor.execute("""
            SELECT quantity, is_preliminary 
            FROM orders 
            WHERE user_id = ? 
              AND target_date = ?
              AND is_cancelled = FALSE
        """, (user_db_id, target_date.isoformat()))
        order = db.cursor.fetchone()

        # Добавляем информацию о заказе
        keyboard = []
        if order:
            qty, is_preliminary = order
            order_type = "Предзаказ" if is_preliminary else "Заказ"
            response_text += f"\n\n✅ {order_type}: {qty} порции"
            
            if can_modify_order(target_date):
                keyboard.append([InlineKeyboardButton("✏️ Изменить", callback_data=f"change_{day_offset}")])
                keyboard.append([InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_{day_offset}")])
            else:
                response_text += "\n⏳ Изменение невозможно (время истекло)"
        elif can_modify_order(target_date):
            keyboard.append([InlineKeyboardButton("✅ Заказать", callback_data=f"order_{day_offset}")])
        else:
            response_text += "\n⏳ Приём заказов завершён"

        # Отправляем обновлённое сообщение
        await query.edit_message_text(
            text=response_text,
            reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
            parse_mode="Markdown"
        )

    except Exception as e:
        logger.error(f"Ошибка обновления дня: {e}", exc_info=True)
        await query.answer("⚠️ Ошибка обновления. Попробуйте позже", show_alert=True)

async def modify_portion_count(query, now, user, context, delta):
    """Изменение количества порций"""
    try:
        day_offset = context.user_data['current_day_offset']
        target_date = (now + timedelta(days=day_offset)).date()
        user_db_id = context.user_data['user_db_id']
        
        # Получаем текущее количество
        db.cursor.execute("""
            SELECT quantity FROM orders 
            WHERE user_id = ? AND target_date = ? AND is_cancelled = FALSE
        """, (user_db_id, target_date.isoformat()))
        current_qty = db.cursor.fetchone()[0]
        new_qty = current_qty + delta

        # Проверка границ
        if new_qty < 1:
            return await handle_cancel_callback(query, now, user, context)
        if new_qty > 3:
            await query.answer("ℹ️ Максимум 3 порции")
            return

        # Обновляем количество
        with db.conn:
            db.cursor.execute("""
                UPDATE orders SET quantity = ? 
                WHERE user_id = ? AND target_date = ? AND is_cancelled = FALSE
            """, (new_qty, user_db_id, target_date.isoformat()))

        # Обновляем интерфейс без возврата в меню
        await handle_change_callback(query, now, user, context)
        await query.answer(f"Установлено: {new_qty} порции")

    except Exception as e:
        logger.error(f"Ошибка изменения количества: {e}")
        await query.answer("⚠️ Ошибка изменения", show_alert=True)

async def handle_confirm_callback(query, now, user, context):
    """Подтверждение заказа"""
    try:
        day_offset = context.user_data['current_day_offset']
        await refresh_day_view(query, day_offset, context.user_data['user_db_id'], now)
        await query.answer("✅ Заказ подтверждён")
    except Exception as e:
        logger.error(f"Ошибка подтверждения: {e}")
        await query.answer("⚠️ Ошибка подтверждения", show_alert=True)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    
async def handle_cancel_order(query, target_date_str):
    if not can_modify_order(target_date_str):  # Используем ВАШУ проверку
        await query.answer("ℹ️ Отмена заказа невозможна после 9:30", show_alert=True)
        return
    
    """Обработка отмены заказа по конкретной дате"""
    user_id = query.from_user.id
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    now = datetime.now(TIMEZONE)
    
    if not can_modify_order(target_date):
        await query.answer("ℹ️ Отмена невозможна (после 9:30)", show_alert=True)
        return False

    db.cursor.execute(
        "DELETE FROM orders WHERE user_id = "
        "(SELECT id FROM users WHERE telegram_id = ?) AND target_date = ?",
        (user_id, target_date_str)
    )
    db.conn.commit()
    
    return db.cursor.rowcount > 0
    
async def handle_back_callback(query, now, user, context):
    """Обработчик кнопки 'Назад'"""
    try:
        _, day_offset_str = query.data.split("_", 1)
        day_offset = int(day_offset_str)
        await refresh_day_view(query, day_offset, context.user_data['user_db_id'], now)
        await query.answer("Возврат к меню")
    except Exception as e:
        logger.error(f"Ошибка в handle_back_callback: {e}")
        await query.answer("⚠️ Ошибка возврата", show_alert=True)
