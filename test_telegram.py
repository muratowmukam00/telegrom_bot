# test_telegram.py
import asyncio
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.services.telegram_service import TelegramService

async def main():
    telegram = TelegramService(TELEGRAM_BOT_TOKEN)
    success = await telegram.send_message(
        TELEGRAM_CHAT_ID,
        "✅ <b>Telegram bağlantysy üstünlikli!</b>\nBu test habary MEXC Signal Bot tarapyndan ugradylan.",
    )
    await telegram.close()
    print("Result:", "OK" if success else "FAILED")

if __name__ == "__main__":
    asyncio.run(main())

