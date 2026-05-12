import asyncio
import html
import io
import json
import logging
import os
import sys
import time
from collections import defaultdict, deque
from aiohttp import web

import qrcode
from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import NetworkError, TelegramError, TimedOut
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database
from keyboards import (
    get_admin_keyboard,
    get_approval_keyboard,
    get_subscription_keyboard,
    get_user_action_keyboard,
    get_user_list_keyboard,
    get_user_menu_keyboard,
    get_welcome_keyboard,
)
from xui_client import XUIClient

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@entixxxx")
SITE_URL = os.getenv("SITE_URL", "https://shawtyvpn.online")
SUB_URL = os.getenv("SUB_URL", "")
WELCOME_IMAGE_PATH = os.getenv("WELCOME_IMAGE_PATH", "welcome_image.jpg")
DEVICE_LIMIT = int(os.getenv("DEVICE_LIMIT", "3"))
HEALTH_CHECK_PORT = int(os.getenv("HEALTH_CHECK_PORT", "8080"))
HEALTH_CHECK_ENABLED = os.getenv("HEALTH_CHECK_ENABLED", "true").lower() == "true"

INBOUND_REALITY = int(os.getenv("INBOUND_REALITY", "1"))
INBOUND_CF = int(os.getenv("INBOUND_CF", "2"))
INBOUND_WORKERS = int(os.getenv("INBOUND_WORKERS", "3"))
INBOUND_RU_REALITY = int(os.getenv("INBOUND_RU_REALITY", "4"))
INBOUND_SS = int(os.getenv("INBOUND_SS", "5"))

USER_TELEGRAM_ID = 1
USER_USERNAME = 2
USER_EMAIL = 3
USER_UUID = 4
USER_SUB_ID = 5
USER_STATUS = 6
USER_CREATED_AT = 7
USER_DEVICE_LIMIT = 9

REQUEST_ID = 0
REQUEST_TELEGRAM_ID = 1
REQUEST_USERNAME = 2
REQUEST_STATUS = 3

INBOUND_FLOW = {
    INBOUND_REALITY: "xtls-rprx-vision",
    INBOUND_CF: "",
    INBOUND_WORKERS: "",
    INBOUND_RU_REALITY: "xtls-rprx-vision",
    INBOUND_SS: None,
}
INBOUND_IDS = list(INBOUND_FLOW.keys())

RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "30"))
RATE_LIMIT_MAX_EVENTS = int(os.getenv("RATE_LIMIT_MAX_EVENTS", "8"))
REQUEST_COOLDOWN_SECONDS = int(os.getenv("REQUEST_COOLDOWN_SECONDS", "20"))

db = Database()
xui_client = XUIClient()
rate_buckets: dict[int, deque[float]] = defaultdict(deque)
request_cooldowns: dict[int, float] = {}
processing_requests: set[int] = set()
callback_debounce: dict[int, float] = {}
suspicious_activity: dict[int, dict] = defaultdict(lambda: {"count": 0, "last_activity": 0})


def validate_env():
    required = ["BOT_TOKEN", "ADMIN_ID", "SUB_URL", "XUI_URL", "XUI_PATH", "XUI_BEARER_TOKEN"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise EnvironmentError(f"Missing required environment variables: {', '.join(missing)}")


def is_rate_limited(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return False

    now = time.monotonic()
    bucket = rate_buckets[user_id]
    while bucket and now - bucket[0] > RATE_LIMIT_WINDOW:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_EVENTS:
        return True
    bucket.append(now)
    return False


async def check_rate_limit_and_report(user_id: int, context: ContextTypes.DEFAULT_TYPE = None) -> bool:
    """Check rate limit and report suspicious activity if exceeded"""
    if is_rate_limited(user_id):
        await report_suspicious_activity(user_id, "rate_limit_exceeded", context)
        return True
    return False


async def report_suspicious_activity(user_id: int, activity_type: str, context: ContextTypes.DEFAULT_TYPE = None):
    """Report suspicious activity to admin"""
    now = time.monotonic()
    activity = suspicious_activity[user_id]
    activity["count"] += 1
    activity["last_activity"] = now

    # Log the suspicious activity
    logger.warning(f"Suspicious activity detected: user_id={user_id}, type={activity_type}, count={activity['count']}")

    # Notify admin if this is the first time or if count is high
    if activity["count"] == 1 or activity["count"] % 5 == 0:
        try:
            message = f"⚠️ Подозрительная активность!\n\n"
            message += f"👤 User ID: {user_id}\n"
            message += f"🔍 Тип: {activity_type}\n"
            message += f"📊 Количество: {activity['count']}\n"
            message += f"⏰ Время: {time.strftime('%Y-%m-%d %H:%M:%S')}"

            if context:
                await safe_send_message(context, ADMIN_ID, message)
        except Exception as e:
            logger.error(f"Failed to notify admin about suspicious activity: {e}")


def is_request_on_cooldown(user_id: int) -> bool:
    if user_id == ADMIN_ID:
        return False

    now = time.monotonic()
    last = request_cooldowns.get(user_id, 0)
    if now - last < REQUEST_COOLDOWN_SECONDS:
        return True
    request_cooldowns[user_id] = now
    return False


async def telegram_retry(action, description: str, attempts: int = 2):
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            return await action()
        except (NetworkError, TimedOut) as e:
            last_error = e
            logger.warning("%s failed on attempt %s/%s: %s", description, attempt, attempts, e)
            if attempt < attempts:
                await asyncio.sleep(0.7)
    raise last_error


async def safe_reply(update: Update, text: str, **kwargs):
    return await telegram_retry(lambda: update.message.reply_text(text=text, **kwargs), "reply_text")


async def safe_edit(query, text: str, **kwargs):
    return await telegram_retry(lambda: query.edit_message_text(text=text, **kwargs), "edit_message_text")


async def safe_send_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs):
    return await telegram_retry(lambda: context.bot.send_message(chat_id=chat_id, text=text, **kwargs), "send_message")


async def safe_send_photo(context: ContextTypes.DEFAULT_TYPE, chat_id: int, caption: str, **kwargs):
    async def action():
        with open(WELCOME_IMAGE_PATH, "rb") as photo:
            return await context.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, **kwargs)

    return await telegram_retry(action, "send_photo")


async def answer_callback(query, text: str | None = None, show_alert: bool = False):
    try:
        await query.answer(text=text, show_alert=show_alert)
    except TelegramError as e:
        logger.warning("Failed to answer callback: %s", e)


def username_from_update(update_or_query, fallback_id: int) -> str:
    user = getattr(update_or_query, "effective_user", None) or getattr(update_or_query, "from_user", None)
    username = getattr(user, "username", None)
    return username or str(fallback_id)


def validate_username(username: str | None) -> str | None:
    """Validate and sanitize username"""
    if not username:
        return None
    # Remove @ prefix and strip whitespace
    clean = username.lstrip("@").strip()
    # Check if username is too long or contains invalid characters
    if len(clean) > 32:
        return None
    # Allow only alphanumeric, underscore, hyphen, dot
    if not all(ch.isalnum() or ch in "._-" for ch in clean):
        return None
    return clean


def validate_text_input(text: str | None, max_length: int = 1000) -> str | None:
    """Validate and sanitize text input"""
    if not text:
        return None
    # Strip whitespace
    clean = text.strip()
    # Check length
    if len(clean) > max_length or len(clean) == 0:
        return None
    # Remove potentially dangerous characters
    dangerous_chars = ['<', '>', '&', '"', "'", '`', '|', ';', '$', '(', ')']
    if any(char in clean for char in dangerous_chars):
        return None
    return clean


def validate_telegram_id(telegram_id: int) -> bool:
    """Validate Telegram ID"""
    # Telegram IDs are positive integers
    if not isinstance(telegram_id, int):
        return False
    if telegram_id <= 0:
        return False
    # Check reasonable range (Telegram IDs are typically 7-10 digits)
    if telegram_id < 1000000 or telegram_id > 9999999999:
        return False
    return True


def client_email(username: str, telegram_id: int) -> str:
    clean_username = validate_username(username)
    safe_username = clean_username if clean_username else str(telegram_id)
    safe_username = "".join(ch for ch in safe_username if ch.isalnum() or ch in "._-") or str(telegram_id)
    return f"{safe_username}_{telegram_id}@shawtyvpn.online"


def subscription_link(sub_id: str) -> str:
    return f"{SUB_URL.rstrip('/')}/{sub_id}" if not SUB_URL.endswith("/") else f"{SUB_URL}{sub_id}"


def format_username(username: str | None, telegram_id: int) -> str:
    if username and not username.isdigit():
        return f"@{username.lstrip('@')}"
    return str(telegram_id)


def welcome_text(username: str) -> str:
    return (
        f"💗 Привет, {html.escape(username)}!\n\n"
        "Добро пожаловать в SHAWTY VPN.\n"
        "Нажми «Получить доступ», и админ рассмотрит заявку.\n\n"
        f"💕 Админ: {html.escape(ADMIN_USERNAME)}"
    )


def pending_text() -> str:
    return (
        "💗 Заявка уже на рассмотрении.\n\n"
        "Я пришлю уведомление, когда админ её одобрит.\n"
        f"💕 Админ: {html.escape(ADMIN_USERNAME)}"
    )


def approved_caption(email: str, uuid: str, sub_link: str) -> str:
    return (
        "💗 <b>Доступ одобрен</b>\n\n"
        "Твоя SHAWTY VPN подписка готова.\n\n"
        "🔗 <b>Ссылка для подключения:</b>\n"
        f"<code>{html.escape(sub_link)}</code>\n\n"
        "Нажми на ссылку в блоке выше и удерживай, чтобы скопировать. QR можно получить отдельной кнопкой."
    )


async def send_welcome(update: Update):
    username = update.effective_user.username or update.effective_user.first_name or str(update.effective_user.id)
    await safe_reply(
        update,
        welcome_text(username),
        parse_mode=ParseMode.HTML,
        reply_markup=get_welcome_keyboard(SITE_URL),
    )


async def send_subscription_text(update_or_query, user):
    sub_link = subscription_link(user[USER_SUB_ID])
    text = (
        "💗 <b>Твоя подписка активна</b>\n\n"
        "🔗 <b>Ссылка для подключения:</b>\n"
        f"<code>{html.escape(sub_link)}</code>\n\n"
        "QR можно получить отдельной кнопкой."
    )
    markup = get_subscription_keyboard(user[USER_TELEGRAM_ID], sub_link)

    if hasattr(update_or_query, "edit_message_text"):
        await safe_edit(update_or_query, text, parse_mode=ParseMode.HTML, reply_markup=markup)
    else:
        await safe_reply(update_or_query, text, parse_mode=ParseMode.HTML, reply_markup=markup)


async def send_approved_subscription(context: ContextTypes.DEFAULT_TYPE, telegram_id: int, email: str, uuid: str, sub_id: str):
    sub_link = subscription_link(sub_id)
    await safe_send_photo(
        context,
        telegram_id,
        approved_caption(email, uuid, sub_link),
        parse_mode=ParseMode.HTML,
        reply_markup=get_subscription_keyboard(telegram_id, sub_link),
    )
    await safe_send_message(
        context,
        telegram_id,
        "Меню подключено. В любой момент можно нажать «Моя подписка».",
        reply_markup=get_user_menu_keyboard(),
    )


async def notify_admin_new_request(user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
    request = await db.get_request_by_telegram_id(user_id)
    if not request:
        return

    request_id = request[REQUEST_ID]
    text = (
        "🆕 <b>Новая заявка на доступ</b>\n\n"
        f"👤 Пользователь: {html.escape(format_username(username, user_id))}\n"
        f"🆔 Telegram ID: <code>{user_id}</code>\n\n"
        "Одобрить создание клиента в XUI?"
    )
    try:
        await safe_send_message(
            context,
            ADMIN_ID,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=get_approval_keyboard(request_id),
        )
    except TelegramError as e:
        logger.warning("Failed to notify admin about request %s from user %s: %s", request_id, user_id, e)


def queue_admin_notification(user_id: int, username: str, context: ContextTypes.DEFAULT_TYPE):
    context.application.create_task(notify_admin_new_request(user_id, username, context))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info("/start from user_id=%s", user_id)

    if is_rate_limited(user_id):
        await safe_reply(update, "Слишком много команд подряд. Попробуй чуть позже.")
        return

    user = await db.get_user_by_telegram_id(user_id)
    if user and user[USER_STATUS] == "active":
        await send_subscription_text(update, user)
        return

    await send_welcome(update)


async def request_access(telegram_id: int, username: str, update_or_query, context: ContextTypes.DEFAULT_TYPE):
    if not validate_telegram_id(telegram_id):
        await report_suspicious_activity(telegram_id, "invalid_telegram_id", context)
        return

    if is_request_on_cooldown(telegram_id):
        await safe_reply(update_or_query, "Подождите перед повторным запросом.")
        return

    if telegram_id in processing_requests:
        await safe_reply(update_or_query, "Заявка уже обрабатывается.")
        return

    username = username or str(telegram_id)
    # Validate username
    clean_username = validate_username(username)
    if not clean_username and username != str(telegram_id):
        await report_suspicious_activity(telegram_id, "invalid_username", context)
        await safe_reply(update_or_query, "Некорректное имя пользователя.")
        return

    await db.add_request(telegram_id, username)
    queue_admin_notification(telegram_id, username, context)

    text = (
        "💗 <b>Заявка отправлена</b>\n\n"
        "Админ получил уведомление. После одобрения я пришлю тебе красивое сообщение с подпиской.\n\n"
        f"💕 Админ: {html.escape(ADMIN_USERNAME)}"
    )
    if hasattr(update_or_query, "edit_message_text"):
        await safe_edit(update_or_query, text, parse_mode=ParseMode.HTML)
    else:
        await safe_reply(update_or_query, text, parse_mode=ParseMode.HTML)


async def show_qr_code(user_id: int, query):
    if query.from_user.id != user_id and query.from_user.id != ADMIN_ID:
        await answer_callback(query, "Это не твоя подписка.", show_alert=True)
        return

    user = await db.get_user_by_telegram_id(user_id)
    if not user or user[USER_STATUS] != "active":
        await telegram_retry(lambda: query.message.reply_text("Активной подписки пока нет."), "reply_no_subscription")
        return

    sub_link = subscription_link(user[USER_SUB_ID])
    qr_code = generate_qr_code(sub_link)
    await telegram_retry(
        lambda: query.message.reply_photo(
            photo=qr_code,
            caption="💗 QR для подключения SHAWTY VPN",
            reply_markup=get_subscription_keyboard(user_id, sub_link),
        ),
        "send_qr",
    )


def generate_qr_code(text: str):
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=12,
        border=4,
    )
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#191014", back_color="#fff4f8")
    bio = io.BytesIO()
    bio.name = "shawty_vpn_qr.png"
    img.save(bio, "PNG", quality=95)
    bio.seek(0)
    return bio


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id
    logger.info("callback data=%s user_id=%s", data, user_id)

    if is_rate_limited(user_id):
        await answer_callback(query, "Слишком много действий. Попробуй чуть позже.", show_alert=True)
        return

    # Debounce for callback buttons (prevent rapid double-clicks)
    now = time.monotonic()
    last_callback = callback_debounce.get(user_id, 0)
    if now - last_callback < 1.0:  # 1 second debounce
        await answer_callback(query, "Подожди секунду перед следующим нажатием.", show_alert=True)
        return
    callback_debounce[user_id] = now

    await answer_callback(query)

    if data == "request_access":
        username = username_from_update(update, user_id)
        await request_access(user_id, username, query, context)
        return

    if data.startswith("qr_"):
        await show_qr_code(int(data.split("_", 1)[1]), query)
        return

    if data.startswith(("approve_", "reject_", "user_", "delete_")) or data in {
        "admin_requests",
        "admin_users",
        "admin_info",
        "admin_delete",
        "back_to_admin",
        "back_to_users",
    }:
        if user_id != ADMIN_ID:
            await answer_callback(query, "Нет прав.", show_alert=True)
            return

    if data.startswith("approve_"):
        await approve_user(int(data.split("_", 1)[1]), query, context)
        return

    if data.startswith("reject_"):
        await reject_user(int(data.split("_", 1)[1]), query, context)
        return

    if data == "admin_requests":
        await show_pending_requests(query)
        return

    if data == "admin_users":
        await show_users(query)
        return

    if data == "admin_info":
        await safe_edit(
            query,
            "ℹ️ Информация о боте\n\n"
            f"Админ: {html.escape(ADMIN_USERNAME)}\n"
            f"Сайт: {html.escape(SITE_URL)}\n"
            f"Subscription base: {html.escape(SUB_URL)}\n"
            f"Лимит устройств: {DEVICE_LIMIT}\n"
            f"Inbounds: {', '.join(str(inbound_id) for inbound_id in INBOUND_IDS)}",
            parse_mode=ParseMode.HTML,
        )
        return

    if data == "admin_delete":
        await safe_edit(query, "Для удаления открой «Пользователи» и выбери пользователя.")
        return

    if data == "back_to_admin":
        await safe_edit(query, "Админ панель")
        await telegram_retry(lambda: query.message.reply_text("Выберите действие:", reply_markup=get_admin_keyboard()), "admin_menu")
        return

    if data == "back_to_users":
        await show_users(query)
        return

    if data.startswith("user_"):
        await show_user_details(int(data.split("_", 1)[1]), query)
        return

    if data.startswith("delete_"):
        await delete_user(int(data.split("_", 1)[1]), query, context)
        return


async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    # Validate text input
    if not validate_text_input(text, max_length=100):
        await report_suspicious_activity(update.effective_user.id, "invalid_text_input", context)
        await safe_reply(update, "Некорректный ввод.")
        return

    user_id = update.effective_user.id
    logger.info("text message user_id=%s text=%s", user_id, text)

    if await check_rate_limit_and_report(user_id, context):
        await safe_reply(update, "Слишком много команд подряд. Попробуй чуть позже.")
        return

    if text in {"Получить доступ", "💖 Получить доступ"}:
        await request_access(user_id, username_from_update(update, user_id), update, context)
        return

    if text in {"Узнать больше", "💕 Узнать больше"}:
        await safe_reply(update, f"Сайт SHAWTY VPN: {SITE_URL}")
        return

    if text in {"Моя подписка", "📱 Моя подписка"}:
        user = await db.get_user_by_telegram_id(user_id)
        if user and user[USER_STATUS] == "active":
            await send_subscription_text(update, user)
        else:
            await safe_reply(update, "Активной подписки пока нет. Нажми /start и отправь заявку.")
        return

    if text in {"Информация", "ℹ️ Информация"}:
        await safe_reply(
            update,
            "💗 SHAWTY VPN\n\n"
            "Быстрый приватный доступ через VLESS и Shadowsocks.\n"
            f"Лимит устройств: {DEVICE_LIMIT}\n"
            f"Сайт: {SITE_URL}\n"
            f"Админ: {ADMIN_USERNAME}",
        )
        return

    if user_id == ADMIN_ID:
        if text in {"Заявки", "📋 Заявки"}:
            await show_pending_requests_message(update)
        elif text in {"Пользователи", "👥 Пользователи"}:
            users = await db.get_all_users()
            if users:
                await safe_reply(update, "Пользователи:", reply_markup=get_user_list_keyboard(users))
            else:
                await safe_reply(update, "Пользователей нет.")
        elif text in {"Удалить пользователя", "🗑 Удалить пользователя"}:
            await safe_reply(update, "Открой «Пользователи» и выбери пользователя.")
        elif text in {"Информация", "ℹ️ Информация"}:
            await safe_reply(update, "Бот работает. Для управления используй /admin.")


async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await safe_reply(update, "Нет прав администратора.")
        return
    await safe_reply(update, "Админ панель", reply_markup=get_admin_keyboard())


async def show_pending_requests(query):
    requests = await db.get_pending_requests()
    if not requests:
        await safe_edit(query, "Заявок на рассмотрении нет.")
        return

    text = "Заявки на рассмотрении:\n\n"
    for request in requests[:25]:
        text += (
            f"ID {request[REQUEST_ID]} | "
            f"{format_username(request[REQUEST_USERNAME], request[REQUEST_TELEGRAM_ID])} | "
            f"TG {request[REQUEST_TELEGRAM_ID]}\n"
        )
    await safe_edit(query, text)


async def show_pending_requests_message(update: Update):
    requests = await db.get_pending_requests()
    if not requests:
        await safe_reply(update, "Заявок на рассмотрении нет.")
        return

    text = "Заявки на рассмотрении:\n\n"
    for request in requests[:25]:
        text += f"ID {request[REQUEST_ID]} | {format_username(request[REQUEST_USERNAME], request[REQUEST_TELEGRAM_ID])}\n"
    await safe_reply(update, text)


async def show_users(query):
    users = await db.get_all_users()
    if users:
        await safe_edit(query, "Пользователи:", reply_markup=get_user_list_keyboard(users))
    else:
        await safe_edit(query, "Пользователей нет.")


async def show_user_details(telegram_id: int, query):
    user = await db.get_user_by_telegram_id(telegram_id)
    if not user:
        await safe_edit(query, "Пользователь не найден.")
        return

    text = (
        "Пользователь\n\n"
        f"Telegram ID: <code>{user[USER_TELEGRAM_ID]}</code>\n"
        f"Username: {html.escape(str(user[USER_USERNAME]))}\n"
        f"Email: <code>{html.escape(user[USER_EMAIL])}</code>\n"
        f"UUID: <code>{html.escape(user[USER_UUID])}</code>\n"
        f"Sub ID: <code>{html.escape(user[USER_SUB_ID])}</code>\n"
        f"Статус: {html.escape(user[USER_STATUS])}\n"
        f"Создан: {html.escape(str(user[USER_CREATED_AT]))}\n"
        f"Лимит устройств: {user[USER_DEVICE_LIMIT]}"
    )
    await safe_edit(query, text, parse_mode=ParseMode.HTML, reply_markup=get_user_action_keyboard(telegram_id))


async def approve_user(request_id: int, query, context: ContextTypes.DEFAULT_TYPE):
    if request_id in processing_requests:
        await answer_callback(query, "Эта заявка уже обрабатывается.", show_alert=True)
        return

    request = await db.get_request_by_id(request_id)
    if not request or request[REQUEST_STATUS] != "pending":
        await safe_edit(query, "Заявка уже обработана или не найдена.")
        return

    telegram_id = request[REQUEST_TELEGRAM_ID]
    username = request[REQUEST_USERNAME] or str(telegram_id)
    email = client_email(username, telegram_id)

    # Log admin action
    logger.info(f"ADMIN ACTION: Approved user {telegram_id} ({username}) by admin {query.from_user.id}")

    processing_requests.add(request_id)
    await safe_edit(query, f"Создаю подписку для {format_username(username, telegram_id)}...")

    try:
        await process_user_approval(request_id, telegram_id, username, email, context)
    except Exception as e:
        logger.exception("Error approving request %s", request_id)
        await safe_edit(
            query,
            f"Не удалось создать подписку для {telegram_id}:\n{e}",
            reply_markup=get_approval_keyboard(request_id),
        )
    else:
        await safe_edit(query, f"Готово. Пользователь {telegram_id} одобрен.")
    finally:
        processing_requests.discard(request_id)


async def process_user_approval(request_id: int, telegram_id: int, username: str, email: str, context: ContextTypes.DEFAULT_TYPE):
    uuid = await xui_client.get_new_uuid()
    await delete_existing_xui_clients(email)

    # No expiry time (unlimited subscription)
    expiry_time = 0
    # Total GB in bytes (0 = unlimited)
    total_gb = 0

    logger.info(f"Adding client to inbound {INBOUND_REALITY} with email {email}, expiry: {expiry_time}, total_gb: {total_gb}")
    await xui_client.add_client(INBOUND_REALITY, email, uuid, DEVICE_LIMIT, expiry_time=expiry_time, total_gb=total_gb, flow=INBOUND_FLOW[INBOUND_REALITY])

    created_inbounds = [INBOUND_REALITY]
    copy_errors = []
    try:
        for inbound_id in INBOUND_IDS:
            if inbound_id == INBOUND_REALITY:
                continue
            logger.info(f"Copying client from inbound {INBOUND_REALITY} to {inbound_id} with flow {INBOUND_FLOW[inbound_id]}")
            try:
                await xui_client.copy_client_to_inbound(
                    inbound_id,
                    INBOUND_REALITY,
                    email,
                    flow=INBOUND_FLOW[inbound_id],
                )
                created_inbounds.append(inbound_id)
                logger.info(f"Successfully copied to inbound {inbound_id}")
            except Exception as e:
                copy_errors.append(f"inbound {inbound_id}: {e}")
                logger.error(f"Failed to copy to inbound {inbound_id}: {e}")
    except Exception:
        for inbound_id in created_inbounds:
            try:
                await xui_client.delete_client(inbound_id, uuid)
            except Exception:
                logger.warning("Rollback failed for inbound %s email=%s", inbound_id, email)
        raise

    if copy_errors:
        logger.warning(f"Client copied to {len(created_inbounds)}/{len(INBOUND_IDS)} inbounds. Errors: {copy_errors}")
    else:
        logger.info(f"Client successfully copied to all {len(INBOUND_IDS)} inbounds")

    sub_id = await get_sub_id(email, uuid)
    await db.add_user(telegram_id, username, email, uuid, sub_id, expiry_time=expiry_time, total_gb=total_gb)
    await db.update_request_status(request_id, "approved")
    await send_approved_subscription(context, telegram_id, email, uuid, sub_id)


async def delete_existing_xui_clients(email: str):
    for inbound_id in INBOUND_IDS:
        try:
            # Try email first, then email pattern as fallback
            client_id = await xui_client.get_client_id_by_email(inbound_id, email)
            if not client_id or client_id == "None":
                client_id = await xui_client.get_client_id_by_email_pattern(inbound_id, email)
            if client_id and client_id != "None":
                await xui_client.delete_client(inbound_id, client_id)
        except Exception as e:
            logger.warning("Could not delete old client from inbound %s email=%s: %s", inbound_id, email, e)


async def get_sub_id(email: str, fallback_uuid: str) -> str:
    inbound_config = await xui_client.get_inbound_config(INBOUND_REALITY)
    if not inbound_config.get("success") or not inbound_config.get("obj"):
        return fallback_uuid

    settings_raw = inbound_config["obj"].get("settings")
    settings = json.loads(settings_raw) if isinstance(settings_raw, str) else settings_raw
    for client in settings.get("clients", []):
        if client.get("email") == email:
            return client.get("subId") or fallback_uuid
    return fallback_uuid


async def reject_user(request_id: int, query, context: ContextTypes.DEFAULT_TYPE):
    request = await db.get_request_by_id(request_id)
    if not request or request[REQUEST_STATUS] != "pending":
        await safe_edit(query, "Заявка уже обработана или не найдена.")
        return

    telegram_id = request[REQUEST_TELEGRAM_ID]
    username = request[REQUEST_USERNAME] or str(telegram_id)

    # Log admin action
    logger.info(f"ADMIN ACTION: Rejected user {telegram_id} ({username}) by admin {query.from_user.id}")

    await db.update_request_status(request_id, "rejected")
    await safe_send_message(context, telegram_id, "Заявка отклонена. По вопросам можно написать админу.")
    await safe_edit(query, f"Пользователь {telegram_id} отклонён.")


async def delete_user(telegram_id: int, query, context: ContextTypes.DEFAULT_TYPE):
    user = await db.get_user_by_telegram_id(telegram_id)
    if not user:
        await safe_edit(query, "Пользователь не найден.")
        return

    email = user[USER_EMAIL]
    uuid = user[USER_UUID]
    username = user[USER_USERNAME]

    # Log admin action
    logger.info(f"ADMIN ACTION: Deleted user {telegram_id} ({username}) by admin {query.from_user.id}")

    errors = []
    deleted_count = 0
    not_found_count = 0

    logger.info(f"Deleting user {telegram_id} with email {email} and UUID {uuid} from all inbounds")

    for inbound_id in INBOUND_IDS:
        try:
            # Try UUID first, then email pattern as fallback
            client_id = await xui_client.get_client_id_by_uuid(inbound_id, uuid)
            if not client_id:
                # Fallback to email pattern search (e.g., "user@domain" matches "user@domain_2")
                client_id = await xui_client.get_client_id_by_email_pattern(inbound_id, email)

            if client_id:
                logger.info(f"Found client {client_id} in inbound {inbound_id}, deleting...")
                await xui_client.delete_client(inbound_id, client_id)
                deleted_count += 1
                logger.info(f"Successfully deleted client from inbound {inbound_id}")
            else:
                not_found_count += 1
                logger.warning(f"Client not found in inbound {inbound_id} (tried UUID and email pattern)")
        except Exception as e:
            error_msg = f"inbound {inbound_id}: {e}"
            errors.append(error_msg)
            logger.error(f"Error deleting from inbound {inbound_id}: {e}")

    await db.delete_user(telegram_id)
    try:
        await safe_send_message(context, telegram_id, "Твоя подписка была удалена администратором.")
    except TelegramError:
        pass

    status_msg = f"Удалено из {deleted_count} инбаундов, не найдено в {not_found_count}."
    if errors:
        await safe_edit(query, f"{status_msg}\nОшибки XUI:\n" + "\n".join(errors))
    else:
        await safe_edit(query, f"Пользователь удалён. {status_msg}")


async def post_init(application: Application):
    await db.init_db()
    logger.info("Database initialized")


async def post_shutdown(application: Application):
    await xui_client.close()
    logger.info("XUI client closed")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error = context.error
    if isinstance(error, TelegramError):
        logger.warning("Telegram API error while processing update: %s", error)
        return
    logger.exception("Unhandled error while processing update", exc_info=error)


async def health_check_handler(request):
    """Health check endpoint for monitoring"""
    try:
        # Check database connection
        users = await db.get_all_users()
        pending_requests = await db.get_pending_requests()
        
        return web.json_response({
            "status": "healthy",
            "users_count": len(users),
            "pending_requests": len(pending_requests),
            "timestamp": int(time.time())
        })
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return web.json_response({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": int(time.time())
        }, status=503)


async def start_health_check_server():
    """Start health check web server"""
    if not HEALTH_CHECK_ENABLED:
        logger.info("Health check server disabled")
        return

    app = web.Application()
    app.router.add_get('/health', health_check_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_CHECK_PORT)
    await site.start()
    logger.info(f"Health check server started on port {HEALTH_CHECK_PORT}")


async def cleanup_old_requests():
    """Delete requests older than 12 hours"""
    while True:
        try:
            await asyncio.sleep(3600)  # Check every hour
            await db.delete_old_requests(12)
        except Exception as e:
            logger.error(f"Error cleaning up old requests: {e}")


async def backup_database_task():
    """Automatic database backup every 24 hours"""
    while True:
        try:
            await asyncio.sleep(24 * 3600)  # Every 24 hours
            await db.backup_database()
        except Exception as e:
            logger.error(f"Error backing up database: {e}")


def main():
    validate_env()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(10)
        .read_timeout(20)
        .write_timeout(20)
        .pool_timeout(10)
        .get_updates_connect_timeout(10)
        .get_updates_read_timeout(45)
        .get_updates_write_timeout(20)
        .get_updates_pool_timeout(10)
        .media_write_timeout(60)
        .concurrent_updates(4)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_error_handler(error_handler)

    logger.info("Bot starting")

    # Start health check server and cleanup task using post_init
    async def start_background_tasks(app):
        await post_init(app)  # Call original post_init first
        await start_health_check_server()
        asyncio.create_task(cleanup_old_requests())
        asyncio.create_task(backup_database_task())

    application.post_init = start_background_tasks

    application.run_polling(drop_pending_updates=True, close_loop=False)


if __name__ == "__main__":
    main()
