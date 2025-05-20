# ##keyboards.py
from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from config import CONFIG, LOCATIONS

def create_unverified_user_keyboard():
    return ReplyKeyboardMarkup([
        ["Попробовать снова"],
        ["Написать администратору"]
    ], resize_keyboard=True)

def create_main_menu_keyboard(user_id=None):
    # Базовое меню для всех пользователей
    menu = [
        ["Меню на сегодня", "Меню на неделю"],
        ["Просмотреть заказы", "Статистика за месяц"],
        ["Написать администратору"],
        ["Обновить меню"]
    ]
    
    # Кнопки отчетов для админов, поставщиков и бухгалтерии
    report_buttons = ["📊 Отчет за день", "📅 Отчет за месяц"]
    
    # Специальные кнопки только для админов
    admin_buttons = ["✉️ Написать пользователю", "📢 Сделать рассылку"]
    
    # Проверяем права пользователя
    is_admin = user_id in CONFIG.get('admin_ids', [])
    is_provider = user_id in CONFIG.get('provider_ids', [])
    is_accounting = user_id in CONFIG.get('accounting_ids', [])
    
    # Добавляем кнопки в зависимости от роли
    if is_admin or is_provider or is_accounting:
        menu.insert(0, report_buttons)
    
    if is_admin:
        menu.insert(0, admin_buttons)
    
    return ReplyKeyboardMarkup(menu, resize_keyboard=True)

def create_month_selection_keyboard():
    return ReplyKeyboardMarkup([
        ["Текущий месяц"],
        ["Прошлый месяц"],
        ["Вернуться в главное меню"]
    ], resize_keyboard=True)

def create_order_keyboard(has_order):
    if has_order:
        return [
            [InlineKeyboardButton("✏️ Изменить количество", callback_data="change")],
            [InlineKeyboardButton("❌ Отменить заказ", callback_data="cancel")]
        ]
    return [[InlineKeyboardButton("✅ Заказать", callback_data="order")]]

def create_admin_keyboard():
    """Основная клавиатура админа"""
    return ReplyKeyboardMarkup([
        ["⚙️ Управление конфигурацией", "📜 История сообщений"],
        ["✉️ Написать пользователю", "📢 Сделать рассылку"],
        ["🏠 Главное меню"]
    ], resize_keyboard=True)

def create_admin_config_keyboard():
    """Клавиатура управления конфигурацией"""
    return ReplyKeyboardMarkup([
        ["➕ Добавить администратора", "➕ Добавить поставщика"],
        ["➕ Добавить бухгалтера", "➕ Добавить сотрудника"],
        ["➕ Добавить праздник"],
        ["🏠 Главное меню"]
    ], resize_keyboard=True)

def create_provider_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["✏️ Изменить меню"],
        ["🏠 Главное меню"]
    ], resize_keyboard=True)