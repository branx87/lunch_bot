# ##handlers/message_handlers.py
import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ConversationHandler, MessageHandler, filters, CommandHandler
from telegram.ext import ContextTypes
import asyncio

from config import CONFIG
from constants import AWAIT_MESSAGE_TEXT, AWAIT_USER_SELECTION
from db import db
from keyboards import create_admin_keyboard, create_main_menu_keyboard


logger = logging.getLogger(__name__)

async def start_user_to_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Инициирует процесс отправки сообщения от пользователя администратору.
    Проверяет регистрацию пользователя и переводит в состояние ожидания текста сообщения.
    """
    user = update.effective_user
    
    # Проверяем регистрацию пользователя
    db.cursor.execute(
        "SELECT full_name FROM users WHERE telegram_id = ? AND is_verified = TRUE",
        (user.id,)
    )
    user_data = db.cursor.fetchone()
    
    if not user_data:
        await update.message.reply_text(
            "❌ Вы не завершили регистрацию. Пожалуйста, используйте /start",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    
    context.user_data['user_name'] = user_data[0]
    await update.message.reply_text(
        "✍️ Введите ваше сообщение администратору:",
        reply_markup=ReplyKeyboardMarkup([["❌ Отменить"]], resize_keyboard=True)
    )
    return AWAIT_MESSAGE_TEXT

async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает текст сообщения от пользователя администраторам.
    Сохраняет сообщение в БД и рассылает всем администраторам.
    Форматирует сообщение с информацией о пользователе (имя, username, ID).
    """
    try:
        user = update.effective_user
        message_text = update.message.text
        
        if message_text.strip().lower() == "отменить":
            await update.message.reply_text(
                "❌ Отправка отменена",
                reply_markup=create_main_menu_keyboard(user.id)
            )
            return ConversationHandler.END

        # Получаем полное имя пользователя из базы данных
        db.cursor.execute(
            "SELECT full_name FROM users WHERE telegram_id = ?",
            (user.id,)
        )
        user_data = db.cursor.fetchone()
        full_name = user_data[0] if user_data else "Неизвестный пользователь"

        # Сохраняем сообщение в БД
        db.cursor.execute(
            "INSERT INTO admin_messages (user_id, message_text) "
            "VALUES ((SELECT id FROM users WHERE telegram_id = ?), ?)",
            (user.id, message_text)
        )
        db.conn.commit()

        # Формируем сообщение для админов в новом формате
        admin_message = (
            "✉️ Сообщение от пользователя:\n"
            f"👤 Имя: {full_name}\n"
            f"👤 Телеграм: @{user.username if user.username else 'нет'}\n"
            f"🆔 ID: {user.id}\n"
            f"📝 Текст: {message_text}"
        )

        # Отправляем всем админам
        sent_count = 0
        for admin_id in CONFIG['admin_ids']:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_message
                )
                sent_count += 1
            except Exception as e:
                logger.error(f"Ошибка отправки админу {admin_id}: {e}")

        await update.message.reply_text(
            f"✅ Сообщение отправлено {sent_count} администраторам",
            reply_markup=create_main_menu_keyboard(user.id)
        )
        
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка обработки сообщения: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при отправке. Попробуйте позже.",
            reply_markup=create_main_menu_keyboard(update.effective_user.id)
        )
        return ConversationHandler.END

async def start_admin_to_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Инициирует процесс отправки сообщения администратором пользователю.
    Проверяет права администратора и запрашивает данные получателя (ID, username или ФИО).
    """
    if update.effective_user.id not in CONFIG['admin_ids']:
        await update.message.reply_text("❌ У вас нет прав для этой операции")
        return ConversationHandler.END

    # Очищаем предыдущие данные
    context.user_data.pop('recipient_id', None)
    context.user_data.pop('recipient_name', None)
    
    await update.message.reply_text(
        "Введите ID пользователя, @username или ФИО:\n"
        "(ФИО должно точно совпадать с указанным при регистрации)\n\n"
        "Для отмены нажмите кнопку 'Отмена'",
        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
    )
    return AWAIT_USER_SELECTION

async def handle_user_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обрабатывает выбор пользователя администратором.
    Поддерживает поиск по ID, username или ФИО (точное или частичное совпадение).
    При множественных результатах предлагает выбор из списка.
    """
    user_input = update.message.text.strip()
    
    # Проверка на отмену
    if user_input.lower() in ["отмена", "❌ отмена"]:
        await update.message.reply_text(
            "❌ Отправка отменена",
            reply_markup=create_admin_keyboard()
        )
        return ConversationHandler.END

    try:
        # Если есть список найденных пользователей (после выбора из нескольких)
        if 'found_users' in context.user_data:
            # Пытаемся найти выбранного пользователя в списке
            for user_id, full_name in context.user_data['found_users']:
                if user_input == f"{full_name} (ID: {user_id})":
                    context.user_data['recipient_id'] = user_id
                    context.user_data['recipient_name'] = full_name
                    del context.user_data['found_users']  # Очищаем временные данные
                    
                    await update.message.reply_text(
                        f"Выбран пользователь: {full_name}\n"
                        "Введите сообщение или нажмите 'Отмена':",
                        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
                    )
                    return AWAIT_MESSAGE_TEXT
            
            # Если не нашли совпадение
            await update.message.reply_text(
                "❌ Пользователь не найден. Выберите из списка или нажмите 'Отмена'",
                reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
            )
            return AWAIT_USER_SELECTION

        # Поиск пользователя в БД (первоначальный ввод)
        query = """
            SELECT telegram_id, full_name 
            FROM users 
            WHERE is_verified = TRUE AND (
                telegram_id = ? OR 
                username = ? OR 
                full_name LIKE ?
            )
        """
        
        # Подготавливаем параметры для поиска
        if user_input.isdigit():  # По ID
            params = (int(user_input), None, None)
        elif user_input.startswith('@'):  # По username
            params = (None, user_input[1:], None)
        else:  # По ФИО
            params = (None, None, f"%{user_input}%")
        
        db.cursor.execute(query, params)
        recipients = db.cursor.fetchall()

        if not recipients:
            await update.message.reply_text(
                "❌ Пользователь не найден. Проверьте ввод или нажмите 'Отмена'",
                reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
            )
            return AWAIT_USER_SELECTION

        # Если нашли несколько пользователей
        if len(recipients) > 1:
            keyboard = []
            for user_id, full_name in recipients[:10]:  # Ограничим 10 результатами
                keyboard.append([f"{full_name} (ID: {user_id})"])
            
            keyboard.append(["❌ Отмена"])
            
            await update.message.reply_text(
                "Найдено несколько пользователей. Выберите одного:",
                reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
            )
            context.user_data['found_users'] = recipients
            return AWAIT_USER_SELECTION

        # Если нашли одного пользователя
        recipient = recipients[0]
        context.user_data['recipient_id'] = recipient[0]
        context.user_data['recipient_name'] = recipient[1]
        
        await update.message.reply_text(
            f"Выбран пользователь: {recipient[1]}\n"
            "Введите сообщение или нажмите 'Отмена':",
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return AWAIT_MESSAGE_TEXT

    except Exception as e:
        logger.error(f"Ошибка выбора пользователя: {e}")
        await update.message.reply_text(
            "❌ Ошибка при поиске пользователя. Попробуйте снова или нажмите 'Отмена'",
            reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
        )
        return AWAIT_USER_SELECTION

async def handle_admin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отправляет сообщение от администратора выбранному пользователю.
    Сохраняет сообщение в БД и уведомляет администратора о результате отправки.
    """
    try:
        text = update.message.text.strip()
        
        # Проверка на отмену
        if text.lower() in ["отмена", "❌ отмена"]:
            await update.message.reply_text(
                "❌ Отправка отменена",
                reply_markup=create_admin_keyboard()
            )
            return ConversationHandler.END

        recipient_id = context.user_data.get('recipient_id')
        recipient_name = context.user_data.get('recipient_name')

        if not recipient_id:
            await update.message.reply_text(
                "❌ Получатель не выбран",
                reply_markup=create_admin_keyboard()
            )
            return ConversationHandler.END

        # Форматируем сообщение
        message = (
            "✉️ Сообщение от администратора:\n"
            f"📝 Текст: {text}\n\n"
        )

        try:
            await context.bot.send_message(
                chat_id=recipient_id,
                text=message
            )
            
            # Сохраняем в БД
            db.cursor.execute(
                "INSERT INTO admin_messages (admin_id, user_id, message_text) "
                "VALUES (?, ?, ?)",
                (update.effective_user.id, recipient_id, text)
            )
            db.conn.commit()

            await update.message.reply_text(
                f"✅ Сообщение отправлено пользователю {recipient_name}",
                reply_markup=create_admin_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка отправки пользователю {recipient_id}: {e}")
            await update.message.reply_text(
                f"❌ Не удалось отправить сообщение пользователю {recipient_name}",
                reply_markup=create_admin_keyboard()
            )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка отправки сообщения админа: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при отправке",
            reply_markup=create_admin_keyboard()
        )
        return ConversationHandler.END

async def handle_broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Инициирует процесс массовой рассылки сообщений.
    Проверяет права администратора и переводит в состояние ожидания текста рассылки.
    """
    if update.effective_user.id not in CONFIG['admin_ids']:
        logger.warning(f"Попытка рассылки от неадмина: {update.effective_user.id}")
        await update.message.reply_text("❌ У вас нет прав для этой команды")
        return ConversationHandler.END
    
    logger.info(f"Начало рассылки админом {update.effective_user.id}")
    await update.message.reply_text(
        "Введите сообщение для рассылки:",
        reply_markup=ReplyKeyboardMarkup([["❌ Отмена"]], resize_keyboard=True)
    )
    return AWAIT_MESSAGE_TEXT

async def process_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Выполняет массовую рассылку сообщения всем верифицированным пользователям.
    Формирует отчет об успешных/неудачных отправках.
    Обрабатывает отмену рассылки.
    """
    text = update.message.text
    logger.info(f"Получен текст для рассылки: {text}")
    
    if text.lower() in ["отмена", "❌ отмена"]:
        logger.info("Рассылка отменена")
        await update.message.reply_text(
            "❌ Рассылка отменена",
            reply_markup=create_admin_keyboard()
        )
        return ConversationHandler.END
    
    try:
        db.cursor.execute("SELECT telegram_id, full_name FROM users WHERE is_verified = TRUE")
        users = db.cursor.fetchall()
        
        if not users:
            logger.warning("Нет верифицированных пользователей для рассылки")
            await update.message.reply_text("❌ Нет пользователей для рассылки")
            return ConversationHandler.END
        
        logger.info(f"Начало рассылки для {len(users)} пользователей")
        msg = await update.message.reply_text(f"⏳ Рассылка для {len(users)} пользователей...")
        
        success = 0
        failed = []
        
        for user_id, full_name in users:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"📢 Сообщение от администратора:\n\n{text}"
                )
                success += 1
                await asyncio.sleep(0.1)
            except Exception as e:
                failed.append(f"{full_name} (ID: {user_id})")
                logger.error(f"Ошибка отправки {user_id}: {e}")
        
        try:
            await msg.delete()
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения: {e}")
        
        report = f"✅ Успешно: {success}/{len(users)}"
        if failed:
            report += f"\n❌ Ошибки: {len(failed)}"
        
        logger.info(f"Результат рассылки: {report}")
        await update.message.reply_text(
            report,
            reply_markup=create_admin_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Ошибка рассылки: {e}", exc_info=True)
        await update.message.reply_text("❌ Ошибка при рассылке")
    
    return ConversationHandler.END

def setup_message_handlers(application):
    """
    Настраивает и добавляет обработчики сообщений в приложение:
    - Диалог пользователя с администраторами
    - Диалог администратора с пользователями
    Обеспечивает обработку отмены и повторного входа в диалог.
    """
    # Диалог пользователя с админами
    user_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Regex("^Написать администратору$") & filters.TEXT,
            start_user_to_admin_message
        )],
        states={
            AWAIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT, handle_user_message)]
        },
        fallbacks=[
            CommandHandler('cancel', lambda u, c: ConversationHandler.END),
            MessageHandler(filters.Regex("^❌ Отменить$"), lambda u, c: ConversationHandler.END)
        ],
        allow_reentry=True
    )

    # Диалог админа с пользователем
    admin_conv = ConversationHandler(
        entry_points=[MessageHandler(
            filters.Regex("^✉️ Написать пользователю$") & filters.TEXT,
            start_admin_to_user_message
        )],
        states={
            AWAIT_USER_SELECTION: [MessageHandler(filters.TEXT, handle_user_selection)],
            AWAIT_MESSAGE_TEXT: [MessageHandler(filters.TEXT, handle_admin_message)]
        },
        fallbacks=[
            CommandHandler('cancel', lambda u, c: ConversationHandler.END),
            MessageHandler(filters.Regex("^❌ Отменить$"), lambda u, c: ConversationHandler.END)
        ],
        allow_reentry=True
    )

    application.add_handler(user_conv)
    application.add_handler(admin_conv)