# SHAWTY VPN Bot

Telegram бот для управления доступом к VPN сервису SHAWTY VPN через 3X-UI панель.

## Технологии

- Python 3
- python-telegram-bot v21+
- aiohttp
- aiosqlite
- python-dotenv
- qrcode + Pillow

## Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd shawtybot
```

2. Создайте виртуальное окружение и установите зависимости:
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# или: venv\Scripts\activate  # Windows
pip install -r requirements.txt
```

3. Скопируйте и настройте `.env` файл:
```bash
cp .env.example .env
```

Отредактируйте `.env`:
- `BOT_TOKEN` — токен вашего Telegram бота от @BotFather
- `ADMIN_ID` — ваш Telegram ID (для админ-функций)
- `ADMIN_USERNAME` — ваш Telegram username (для отображения в сообщениях)
- `SUB_URL` — URL вашей subscription ссылки
- `XUI_URL` — URL 3X-UI панели
- `XUI_PATH` — путь до API 3X-UI панели
- `XUI_BEARER_TOKEN` — Bearer токен из 3X-UI панели (Settings → Security → API Token)

## Конфигурация

### 3X-UI Панель
- URL: https://proxy.shawtyvpn.online:51756
- Path: /aVPl6vylEXefnfzmxY/
- API Base: https://proxy.shawtyvpn.online:51756/panel/api

### Inbound IDs
- ID 1 — SHAWTY VPN REALITY (VLESS+Reality+TCP, порт 443)
- ID 2 — SHAWTY VPN CF (VLESS+WS+Cloudflare, порт 8050)
- ID 3 — SHAWTY VPN WORKERS (VLESS+WS+Workers, порт 8080)
- ID 4 — SHAWTY VPN RU REALITY (VLESS+Reality+TCP, порт 8443)
- ID 5 — SHAWTY VPN SS (Shadowsocks 2022, порт 2052)

### Subscription
- URL: https://sub.shawtyvpn.online:2096/sub/

## Запуск

```bash
python bot.py
```

## Функционал

### Для пользователей:
1. `/start` — отправка заявки на доступ
2. После одобрения получает subscription ссылку + QR код
3. Лимит устройств: 3

### Для админа:
1. Получает уведомления о новых заявках
2. Кнопки «Одобрить» / «Отклонить»
3. Просмотр списка пользователей
4. Удаление пользователей

## API Эндпоинты 3X-UI

- GET `/panel/api/inbounds/list` — список inbound
- GET `/panel/api/server/getNewUUID` — генерация UUID
- POST `/panel/api/inbounds/addClient` — добавление клиента
- POST `/panel/api/inbounds/:id/copyClients` — копирование клиента во все inbound
- POST `/panel/api/inbounds/:id/delClient/:clientId` — удаление клиента
- GET `/panel/api/inbounds/getSubLinks/:subId` — получение subscription ссылок
- GET `/panel/api/inbounds/getClientLinks/:id/:email` — получение ссылок клиента

## Структура проекта

```
shawtybot/
├── bot.py              # Основной файл бота
├── xui_client.py       # Клиент для 3X-UI API
├── database.py         # Модуль работы с базой данных
├── keyboards.py        # Клавиатуры и кнопки
├── requirements.txt    # Зависимости
├── .env               # Конфигурация (не коммитить!)
├── .env.example       # Пример конфигурации
├── .gitignore         # Игнорируемые файлы
├── temp/              # Временные файлы
└── README.md          # Документация
```

## Деплой на сервер

1. Скопируйте файлы на сервер
2. Установите Python 3 и зависимости
3. Настройте `.env` файл
4. Запустите бота:

```bash
python3 bot.py
```

Для работы в фоне используйте `systemd`, `screen` или `pm2`.

## Безопасность

- `.env` файл добавлен в `.gitignore`
- Bearer токен хранится в переменных окружения
- Пароли/токены никогда не захардкожены в коде
- Подключение к XUI API через HTTPS
- База данных SQLite хранится локально