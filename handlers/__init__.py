from datetime import datetime, timedelta
from telegram import Update
from config import CONFIG
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,  # Добавлен этот импорт
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# Импорты локальных модулей
from .common import show_main_menu
from .message_handlers import setup_message_handlers, start_user_to_admin_message, handle_user_message, handle_user_selection, handle_admin_message
from .base_handlers import (
    start,
    error_handler,
    test_connection,
    main_menu,
    handle_text_message,
    handle_registered_user
)
from .registration_handlers import (
    get_phone,
    get_full_name,
    get_location
)
from .menu_handlers import (
    show_today_menu,
    show_week_menu,
    view_orders,
    monthly_stats,
    handle_order_confirmation,
    order_action,
    monthly_stats_selected
)
from .callback_handlers import (
    callback_handler,
    handle_order_callback,
    handle_change_callback,
    handle_cancel_callback
)
from .admin_handlers import (
    handle_admin_choice,
    handle_broadcast_command,
    process_broadcast_message
)
from .report_handlers import select_month_range

# Состояния диалога
from .states import (
    PHONE,
    FULL_NAME,
    LOCATION,
    MAIN_MENU,
    ORDER_ACTION,
    ORDER_CONFIRMATION,
    SELECT_MONTH_RANGE,
    BROADCAST_MESSAGE,
    AWAIT_MESSAGE_TEXT,
    AWAIT_USER_SELECTION
)

# Константы для новых состояний
SELECT_MONTH_RANGE_STATS = 'select_month_range_stats'
AWAIT_USER_SELECTION = 'handle_user_selection'

def setup_handlers(application):
    """Настройка обработчиков сообщений"""
    # 1. Основные обработчики
    setup_message_handlers(application)
    
    # 2. Обработчик команды рассылки
    application.add_handler(MessageHandler(
        filters.Regex("^📢 Сделать рассылку$") & 
        filters.User(user_id=CONFIG['admin_ids']),
        handle_broadcast_command
    ))
    
    # 3. Основной ConversationHandler (без BROADCAST_MESSAGE в states)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex("^Статистика за месяц$"), monthly_stats),
            MessageHandler(filters.Regex("^Админ-панель$"), handle_admin_choice),
            MessageHandler(filters.Regex("^Написать администратору$"), start_user_to_admin_message),
        ],
        states={
            SELECT_MONTH_RANGE_STATS: [
                MessageHandler(
                    filters.Regex("^(Текущий месяц|Прошлый месяц|Вернуться в главное меню)$"),
                    monthly_stats_selected
                )
            ],
            PHONE: [MessageHandler(filters.CONTACT, get_phone)],
            FULL_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_full_name)],
            LOCATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_location)],
            MAIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu)],
            ORDER_ACTION: [CallbackQueryHandler(callback_handler)],
            ORDER_CONFIRMATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order_confirmation)],
            SELECT_MONTH_RANGE: [
                MessageHandler(filters.Regex(r'^(Текущий месяц|Прошлый месяц)$'), select_month_range),
                MessageHandler(filters.Regex(r'^Вернуться в главное меню$'), show_main_menu)
            ]
        },
        fallbacks=[
            CommandHandler('cancel', lambda u, c: show_main_menu(u, u.effective_user.id)),
            MessageHandler(filters.Regex(r'^(❌ Отмена|Отмена|Вернуться в главное меню|🏠 Главное меню)$'), 
                         lambda u, c: show_main_menu(u, u.effective_user.id))
        ],
        per_chat=True,
        per_user=True,
        allow_reentry=True
    )

    application.add_handler(conv_handler)

    # 4. Обработчик для зарегистрированных пользователей
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.Regex(
            r'^(Меню на сегодня|Меню на неделю|Просмотреть заказы|Статистика за месяц|'
            r'💰 Бухгалтерский отчет|📦 Отчет поставщика|'
            r'📊 Отчет за день|📅 Отчет за месяц|Обновить меню|Вернуться в главное меню)$'
        ),
        handle_registered_user
    ))

    # 5. CallbackQueryHandler
    application.add_handler(CallbackQueryHandler(callback_handler))

    # 6. Обработчик всех текстовых сообщений (кроме команд)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_message
        )
    )

    # 7. Обработчик ошибок
    application.add_error_handler(error_handler)
