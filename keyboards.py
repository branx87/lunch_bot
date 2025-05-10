from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup
from config import CONFIG, LOCATIONS

def create_unverified_user_keyboard():
    return ReplyKeyboardMarkup([
        ["Попробовать снова"],
        ["Написать администратору"]
    ], resize_keyboard=True)

def create_main_menu_keyboard(user_id=None):
    menu = [
        ["Меню на сегодня", "Меню на неделю"],
        ["Просмотреть заказы", "Статистика за месяц"],
        ["Написать администратору"]
    ]
    
    if user_id in CONFIG.get('admin_ids', []):
        menu.insert(0, ["📊 Отчет за день", "📅 Отчет за месяц"])
        menu.insert(0, ["✉️ Написать пользователю", "📢 Сделать рассылку"])
    
    if user_id in CONFIG.get('provider_ids', []):
        menu.append(["📦 Отчет поставщика"])
    
    if user_id in CONFIG.get('accounting_ids', []):
        menu.append(["💰 Бухгалтерский отчет"])

    menu.append(["Обновить меню"])

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
    return ReplyKeyboardMarkup([
        ["📊 Отчет за день", "📅 Отчет за месяц"],
        ["✉️ Написать пользователю", "📢 Сделать рассылку"],
        ["📜 История сообщений"],
        ["🏠 Главное меню"]
    ], resize_keyboard=True)
