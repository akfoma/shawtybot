import os, asyncio, logging
from dotenv import load_dotenv
load_dotenv()

from telegram import Bot

async def test():
    bot = Bot(token=os.getenv('BOT_TOKEN'))
    # Отправить /start боту самому себе (чтобы проверить реакцию)
    admin_id = int(os.getenv('ADMIN_ID'))

    # Проверяем getUpdates
    updates = await bot.get_updates()
    print(f"Pending updates: {len(updates)}")

    # Отправляем тестовое текстовое сообщение
    await bot.send_message(chat_id=admin_id, text="💖 Получить доступ")
    print("Sent emoji button text")

asyncio.run(test())