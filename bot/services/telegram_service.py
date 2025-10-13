from aiogram import Bot
from aiogram.types import FSInputFile
from typing import Optional
import os

class TelegramService:
    """Сервис для работы с Telegram"""
    
    def __init__(self, bot_token: str):
        self.bot = Bot(token=bot_token)
    
    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML"
    ) -> bool:
        """Отправить текстовое сообщение"""
        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            print(f"Error sending message: {e}")
            return False
    
    async def send_photo(
        self,
        chat_id: str,
        photo_path: str,
        caption: str = ""
    ) -> bool:
        """Отправить фото с подписью"""
        try:
            if not os.path.exists(photo_path):
                print(f"Photo not found: {photo_path}")
                return False
            
            photo = FSInputFile(photo_path)
            await self.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=caption,
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            print(f"Error sending photo: {e}")
            return False
    
    async def send_signal_alert(
        self,
        chat_id: str,
        symbol: str,
        analysis: dict
    ) -> bool:
        """Отправить алерт о сигнале"""
        try:
            f1_passed, f1_change = analysis['filter_1_price']
            f2_passed, f2_rsi = analysis['filter_2_rsi_1h']
            f3_passed, f3_rsi = analysis['filter_3_rsi_15m']
            
            message = f"""
🚨 <b>СИГНАЛ ОБНАРУЖЕН!</b>

📊 Символ: <b>{symbol}</b>

✅ <b>Фильтр 1 (Цена 15м):</b> {"✓ PASSED" if f1_passed else "✗ FAILED"}
   Изменение: {f1_change:.2f}%

✅ <b>Фильтр 2 (RSI 1h):</b> {"✓ PASSED" if f2_passed else "✗ FAILED"}
   RSI: {f2_rsi:.2f}

✅ <b>Фильтр 3 (RSI 15m):</b> {"✓ PASSED" if f3_passed else "✗ FAILED"}
   RSI: {f3_rsi:.2f}

🎯 <b>Итог: {"СИГНАЛ ГОТОВ!" if analysis['signal_triggered'] else "Условия не выполнены"}</b>
            """
            
            await self.send_message(chat_id, message)
            return True
        except Exception as e:
            print(f"Error sending signal alert: {e}")
            return False
    
    async def close(self):
        """Закрыть сессию бота"""
        await self.bot.session.close()
