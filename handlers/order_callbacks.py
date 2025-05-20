# ##handlers/order_callbacks.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CallbackQueryHandler
from telegram.ext import ContextTypes
from datetime import datetime, date, time, timedelta
import logging

from config import MENU, TIMEZONE
from db import db
from utils import can_modify_order
from view_utils import refresh_day_view

logger = logging.getLogger(__name__)
    
async def handle_order_callback(query, now, user, context):
    """
    Обработчик оформления нового заказа. Выполняет:
    - Проверку допустимости заказа (выходные, временные ограничения)
    - Создание записи заказа в базе данных
    - Обновление интерфейса через refresh_day_view
    - Обработку всех возможных ошибок
    """
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
    """
    Обработчик изменения существующего заказа. Предоставляет:
    - Интерфейс изменения количества порций (+/-)
    - Кнопки подтверждения/отмены заказа
    - Сохранение контекста меню при изменении
    - Проверку временных ограничений на изменения
    """
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
        
async def handle_cancel_callback(query, now, user, context):
    """
    Обработчик отмены заказа с улучшенной безопасностью:
    - Проверка формата и валидности callback-данных
    - Проверка временных ограничений на отмену
    - Надежное обновление статуса в базе данных
    - Логирование действий и обработка ошибок интерфейса
    """
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
                
                target_date_str = query.data.split('_')[1]    
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
        
async def handle_confirm_callback(query, now, user, context):
    """
    Обработчик подтверждения изменений заказа:
    - Обновляет интерфейс через refresh_day_view
    - Сохраняет контекст текущего дня из user_data
    - Обрабатывает возможные ошибки подтверждения
    """
    try:
        day_offset = context.user_data['current_day_offset']
        await refresh_day_view(query, day_offset, context.user_data['user_db_id'], now)
        await query.answer("✅ Заказ подтверждён")
    except Exception as e:
        logger.error(f"Ошибка подтверждения: {e}")
        await query.answer("⚠️ Ошибка подтверждения", show_alert=True)
        
async def modify_portion_count(query, now, user, context, delta):
    """
    Изменяет количество порций в заказе:
    - Обрабатывает увеличение/уменьшение количества
    - Проверяет граничные значения (1-3 порции)
    - При уменьшении до 0 автоматически отменяет заказ
    - Обновляет интерфейс через handle_change_callback
    """
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
        
def setup_order_callbacks(application):
    """
    Настраивает и добавляет обработчики callback-запросов:
    - Оформление заказов (order_*)
    - Изменение количества порций (inc_*, dec_*)
    - Изменение заказа (change_*)
    - Отмена заказа (cancel_*)
    - Подтверждение заказа (confirm_*)
    """
    application.add_handler(CallbackQueryHandler(
        callback_handler,
        pattern=r'^(order|inc|dec|change|cancel|confirm)_'
    ))
    
    # Альтернативный вариант с раздельными обработчиками для каждого типа callback:
    # handlers = [
    #     CallbackQueryHandler(handle_order_callback, pattern=r'^order_'),
    #     CallbackQueryHandler(modify_portion_count, pattern=r'^inc_'),
    #     CallbackQueryHandler(modify_portion_count, pattern=r'^dec_'),
    #     CallbackQueryHandler(handle_change_callback, pattern=r'^change_'),
    #     CallbackQueryHandler(handle_cancel_callback, pattern=r'^cancel_'),
    #     CallbackQueryHandler(handle_confirm_callback, pattern=r'^confirm_')
    # ]
    # for handler in handlers:
    #     application.add_handler(handler)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Центральный обработчик всех callback-запросов"""
    query = update.callback_query
    await query.answer()
    now = datetime.now(TIMEZONE)
    user = update.effective_user
    
    try:
        if query.data.startswith("order_"):
            await handle_order_callback(query, now, user, context)
        elif query.data.startswith("inc_"):
            await modify_portion_count(query, now, user, context, +1)
        elif query.data.startswith("dec_"):
            await modify_portion_count(query, now, user, context, -1)
        elif query.data.startswith("change_"):
            await handle_change_callback(query, now, user, context)
        elif query.data.startswith("cancel_"):
            await handle_cancel_callback(query, now, user, context)
        elif query.data.startswith("confirm_"):
            await handle_confirm_callback(query, now, user, context)
        else:
            logger.warning(f"Неизвестный callback: {query.data}")
            await query.answer("⚠️ Неизвестная команда")
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}", exc_info=True)
        await query.answer("⚠️ Произошла ошибка. Попробуйте позже")