# Состояния диалога (для ConversationHandler)
(
    PHONE, FULL_NAME, LOCATION, MAIN_MENU,
    ORDER_ACTION, ORDER_CONFIRMATION, SELECT_MONTH_RANGE,
    BROADCAST_MESSAGE, AWAIT_MESSAGE_TEXT, AWAIT_USER_SELECTION
) = range(10)

# Константы для состояний
SELECT_MONTH_RANGE_STATS = 'select_month_range_stats'
ORDER_ACTION = "ORDER_ACTION"
BROADCAST_MESSAGE = 'broadcast_message'