from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def get_welcome_keyboard(site_url: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Получить доступ", callback_data="request_access")],
        [InlineKeyboardButton("Узнать больше", url=site_url)],
    ])


def get_user_menu_keyboard():
    keyboard = [
        [KeyboardButton("Моя подписка")],
        [KeyboardButton("Информация")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_approval_keyboard(request_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Одобрить", callback_data=f"approve_{request_id}"),
            InlineKeyboardButton("Отклонить", callback_data=f"reject_{request_id}"),
        ]
    ])


def get_user_list_keyboard(users):
    keyboard = []
    for user in users:
        keyboard.append([
            InlineKeyboardButton(f"{user[2]} ({user[1]})", callback_data=f"user_{user[1]}")
        ])
    keyboard.append([InlineKeyboardButton("Назад", callback_data="back_to_admin")])
    return InlineKeyboardMarkup(keyboard)


def get_admin_keyboard():
    keyboard = [
        [KeyboardButton("Заявки")],
        [KeyboardButton("Пользователи")],
        [KeyboardButton("Удалить пользователя")],
        [KeyboardButton("Информация")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


def get_subscription_keyboard(user_id: int, sub_link: str | None = None):
    keyboard = [[InlineKeyboardButton("QR", callback_data=f"qr_{user_id}")]]
    if sub_link:
        keyboard.insert(0, [InlineKeyboardButton("Открыть подписку", url=sub_link)])
    return InlineKeyboardMarkup(keyboard)


def get_user_action_keyboard(telegram_id: int):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Удалить", callback_data=f"delete_{telegram_id}"),
            InlineKeyboardButton("Назад", callback_data="back_to_users"),
        ]
    ])
