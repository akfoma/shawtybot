<div align="center">

# 🔐 SHAWTY VPN Bot

<img src="welcome_image.jpg" alt="SHAWTY VPN" width="200"/>

**Telegram-бот для управления доступом к VPN-сервису через 3X-UI панель**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![python-telegram-bot](https://img.shields.io/badge/python--telegram--bot-v21+-26A5E4?style=for-the-badge&logo=telegram&logoColor=white)](https://github.com/python-telegram-bot/python-telegram-bot)
[![SQLite](https://img.shields.io/badge/SQLite-aiosqlite-003B57?style=for-the-badge&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)
[![VPS](https://img.shields.io/badge/Deploy-VPS%20%2F%20systemd-orange?style=for-the-badge&logo=linux&logoColor=white)]()

</div>

---

## ✨ Возможности

| Для пользователей | Для администратора |
|---|---|
| 📩 Отправка заявки на доступ | ✅ Одобрение / отклонение заявок |
| 🔗 Получение subscription-ссылки | 👥 Просмотр всех пользователей |
| 📱 QR-код для подключения | 🗑 Удаление пользователей |
| 📋 Просмотр своей подписки | 📊 Статистика через health check |
| — | ⚠️ Уведомления о подозрительной активности |

---

## 🛡 Протоколы

Бот управляет клиентами сразу на **5 inbound-ах** 3X-UI:

- **REALITY** — VLESS + Reality + TCP, порт `443` (основной)
- **CF** — VLESS + WebSocket + Cloudflare, порт `8050`
- **WORKERS** — VLESS + WebSocket + Workers, порт `8080`
- **RU REALITY** — VLESS + Reality + TCP, порт `8443` (для РФ)
- **Shadowsocks** — SS 2022, порт `2052`

---

## 🗂 Структура проекта

```
shawtybot/
├── bot.py              # Основная логика бота, хендлеры
├── xui_client.py       # HTTP-клиент для 3X-UI API
├── database.py         # Работа с SQLite (aiosqlite)
├── keyboards.py        # Inline и Reply клавиатуры
├── requirements.txt    # Зависимости
├── shawtybot.service   # systemd unit-файл
├── run_bot.sh          # Скрипт запуска
├── .env.example        # Пример конфигурации
├── DEPLOY_VPS.md       # Инструкция по деплою
└── README.md
```

---

## ⚙️ Установка

### 1. Клонировать репозиторий

```bash
git clone https://github.com/akfoma/shawtybot.git
cd shawtybot
```

### 2. Создать виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Настроить `.env`

```bash
cp .env.example .env
nano .env
```

---

## 🔧 Конфигурация

```env
# Telegram
BOT_TOKEN=your_bot_token_from_botfather
ADMIN_ID=your_telegram_id
ADMIN_USERNAME=@your_username

# Сайт
SITE_URL=https://your-vpn-site.com
WELCOME_IMAGE_PATH=welcome_image.jpg

# 3X-UI Panel
XUI_URL=https://your-panel-domain:port
XUI_PATH=/your-secret-path
XUI_BEARER_TOKEN=your_bearer_token

# Подписка
SUB_URL=https://your-sub-domain/sub/

# Inbound IDs (соответствуют вашей 3X-UI панели)
INBOUND_REALITY=1
INBOUND_CF=2
INBOUND_WORKERS=3
INBOUND_RU_REALITY=4
INBOUND_SS=5

# Лимиты
DEVICE_LIMIT=3
RATE_LIMIT_WINDOW=30
RATE_LIMIT_MAX_EVENTS=8
REQUEST_COOLDOWN_SECONDS=20

# Health Check
HEALTH_CHECK_PORT=8588
HEALTH_CHECK_ENABLED=true
```

> **Получить Bearer Token:** 3X-UI панель → Settings → Security → API Token

---

## 🚀 Деплой на VPS (systemd)

```bash
# Скопировать unit-файл
sudo cp shawtybot.service /etc/systemd/system/

# Включить и запустить
sudo systemctl daemon-reload
sudo systemctl enable shawtybot
sudo systemctl start shawtybot

# Проверить статус
sudo systemctl status shawtybot
```

### Обновление бота

```bash
cd ~/shawtybot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart shawtybot
```

### Просмотр логов

```bash
# Через journalctl
sudo journalctl -u shawtybot -f

# Через файл логов
tail -f ~/shawtybot/bot.log
```

---

## 🔒 Безопасность

- Все токены хранятся только в `.env` (добавлен в `.gitignore`)
- `html.escape()` на всех пользовательских данных
- Валидация Telegram ID, username, текстового ввода
- Rate limiting: скользящее окно + cooldown на заявки + debounce на кнопки
- Уведомления администратору при подозрительной активности
- Защита от параллельной обработки дублирующих заявок
- Подключение к XUI API только через HTTPS с Bearer-токеном

---

## 🏥 Health Check

Бот поднимает HTTP-эндпоинт для мониторинга:

```
GET http://your-server:8588/health
```

Пример ответа:
```json
{
  "status": "healthy",
  "users_count": 42,
  "pending_requests": 3,
  "timestamp": 1715000000
}
```

---

## 🛠 Технологии

| Библиотека | Назначение |
|---|---|
| `python-telegram-bot` v21+ | Telegram Bot API |
| `aiohttp` | Async HTTP клиент для 3X-UI |
| `aiosqlite` | Async SQLite база данных |
| `python-dotenv` | Загрузка переменных окружения |
| `qrcode` + `Pillow` | Генерация QR-кодов |

---

## 📄 Лицензия

MIT License — используй свободно.

---

<div align="center">

Made with 💗 for **SHAWTY VPN**

</div>
