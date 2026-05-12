# Развертывание SHAWTY VPN Bot на VPS

## Подготовка VPS

### 1. Обновить систему
```bash
sudo apt update && sudo apt upgrade -y
```

### 2. Установить Python и зависимости
```bash
sudo apt install python3 python3-pip python3-venv git -y
```

### 3. Клонировать или загрузить файлы бота
```bash
# Если через git
git clone <your-repo-url> shawtybot
cd shawtybot

# Или через scp с локальной машины
scp -r /Users/foma/Documents/shawtybot user@your-vps-ip:~/shawtybot
```

### 4. Создать виртуальное окружение
```bash
cd ~/shawtybot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 5. Создать .env файл
```bash
nano .env
```

Скопируй содержимое из `.env.example` и заполни реальные значения:
```
BOT_TOKEN=your_bot_token
ADMIN_ID=your_telegram_id
ADMIN_USERNAME=@your_username
SITE_URL=https://shawtyvpn.online
SUB_URL=https://sub.shawtyvpn.online:2096/sub/
WELCOME_IMAGE_PATH=welcome_image.jpg
DEVICE_LIMIT=3
HEALTH_CHECK_PORT=8080
HEALTH_CHECK_ENABLED=true

INBOUND_REALITY=1
INBOUND_CF=2
INBOUND_WORKERS=3
INBOUND_RU_REALITY=4
INBOUND_SS=5

XUI_URL=https://proxy.shawtyvpn.online:51756
XUI_PATH=/aVPl6vylEXefnfzmxY
XUI_BEARER_TOKEN=your_bearer_token
```

### 6. Настроить systemd сервис
```bash
# Скопировать файл сервиса
sudo cp shawtybot.service /etc/systemd/system/

# Замени YOUR_USERNAME на твоё имя пользователя
sudo nano /etc/systemd/system/shawtybot.service

# Замени пути:
# User=твоё_имя_пользователя
# WorkingDirectory=/home/твоё_имя/shawtybot
# ExecStart=/home/твоё_имя/shawtybot/venv/bin/python /home/твоё_имя/shawtybot/bot.py
# Environment=PATH=/home/твоё_имя/shawtybot/venv/bin
# StandardOutput=append:/home/твоё_имя/shawtybot/bot.log
# StandardError=append:/home/твоё_имя/shawtybot/bot.log
```

### 7. Запустить сервис
```bash
sudo systemctl daemon-reload
sudo systemctl enable shawtybot
sudo systemctl start shawtybot
```

### 8. Проверить статус
```bash
sudo systemctl status shawtybot
```

### 9. Просмотреть логи
```bash
sudo journalctl -u shawtybot -f
# или
tail -f bot.log
```

## Управление сервисом

```bash
# Остановить
sudo systemctl stop shawtybot

# Запустить
sudo systemctl start shawtybot

# Перезапустить
sudo systemctl restart shawtybot

# Просмотреть логи
sudo journalctl -u shawtybot -n 100
```

## Firewall (опционально)

Если нужно открыть порт для health check:
```bash
sudo ufw allow 8080/tcp
sudo ufw reload
```

## Автоматический деплой (опционально)

Создай скрипт `deploy.sh`:
```bash
#!/bin/bash
cd ~/shawtybot
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart shawtybot
```

Сделай исполняемым:
```bash
chmod +x deploy.sh
```
