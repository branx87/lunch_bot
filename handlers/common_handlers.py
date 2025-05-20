# ##handlers/common_handlers.py
from asyncio.log import logger
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from config import TIMEZONE
from db import db
from handlers.common import show_main_menu

# --- Просмотр заказов ---
async def view_orders(update: Update, context: ContextTypes.DEFAULT_TYPE, is_cancellation=False):
    """
    Отображает список активных заказов пользователя с возможностью отмены.
    Параметры:
    - update: Объект Update от Telegram
    - context: Контекст обработчика
    - is_cancellation: Флаг, указывающий что вызов произошел после отмены заказа
    
    Функционал:
    - Получает активные заказы из БД (не отмененные и на будущие даты)
    - Формирует интерактивное сообщение с кнопками отмены для каждого заказа
    - Обрабатывает случаи отсутствия заказов
    - Поддерживает как вызов из сообщения, так и из callback-запроса
    - Обновляет интерфейс после отмены заказа (при is_cancellation=True)
    """
    try:
        query = update.callback_query if hasattr(update, 'callback_query') else None
        message = query.message if query else update.message
        user = query.from_user if query else update.effective_user
        
        if not message or not user:
            logger.error("Не удалось определить сообщение или пользователя")
            return

        user_id = user.id
        today_str = datetime.now(TIMEZONE).date().isoformat()

        # Получаем активные заказы
        with db.conn:
            db.cursor.execute("""
                SELECT target_date, quantity, is_preliminary
                FROM orders 
                WHERE user_id = (SELECT id FROM users WHERE telegram_id = ?)
                AND is_cancelled = FALSE
                AND target_date >= ?
                ORDER BY target_date
            """, (user_id, today_str))
            active_orders = db.cursor.fetchall()

        # Обработка случая, когда заказов нет
        if not active_orders:
            if is_cancellation:
                text = "✅ Все заказы отменены."
                if query:
                    await query.edit_message_text(text)
                else:
                    await message.reply_text(text)
            else:
                await message.reply_text("ℹ️ У вас нет активных заказов.")
            return await show_main_menu(message, user_id)

        # Формируем сообщение с кнопками
        response = "📦 Ваши активные заказы:\n"
        keyboard = []
        days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

        for order in active_orders:
            target_date = datetime.strptime(order[0], "%Y-%m-%d").date()
            day_name = days_ru[target_date.weekday()]
            date_str = target_date.strftime('%d.%m')
            qty = order[1]
            status = " (предв.)" if order[2] else ""

            keyboard.append([
                InlineKeyboardButton(
                    f"{day_name} {date_str} - {qty} порц.{status}",
                    callback_data="no_action"
                ),
                InlineKeyboardButton(
                    "❌ Отменить",
                    callback_data=f"cancel_{target_date.strftime('%Y-%m-%d')}"
                )
            ])

        # Добавляем кнопку "В главное меню" (исправлено)
        keyboard.append([InlineKeyboardButton("🔙 В главное меню", callback_data="main_menu")])

        # Отправляем или редактируем сообщение
        if query and is_cancellation:
            try:
                await query.edit_message_text(
                    text=response,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Ошибка редактирования: {e}")
                await query.message.reply_text(
                    text=response,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        else:
            await message.reply_text(
                text=response,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

    except Exception as e:
        logger.error(f"Ошибка в view_orders: {e}")
        error_msg = "⚠️ Ошибка загрузки заказов"
        if query:
            await query.message.reply_text(error_msg)
        else:
            await message.reply_text(error_msg)
        return await show_main_menu(message, user_id)