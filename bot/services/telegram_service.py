import asyncio
import logging
import os
from typing import Optional
from aiogram import Bot
from aiogram.types import FSInputFile

logger = logging.getLogger(__name__)


class TelegramService:
    """
    Асинхронный сервис для отправки сообщений и уведомлений в Telegram.
    Включает автоматический retry при временных ошибках сети.
    """

    def __init__(self, bot_token: str, max_retries: int = 3, retry_delay: int = 2):
        self.bot = Bot(token=bot_token)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def _retry_send(self, func, *args, **kwargs) -> bool:
        """
        Внутренний метод с retry-механизмом.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                await func(*args, **kwargs)
                return True
            except Exception as e:
                logger.warning(f"⚠️ Ошибка Telegram API (попытка {attempt}/{self.max_retries}): {e}")
                if attempt < self.max_retries:
                    await asyncio.sleep(self.retry_delay * attempt)
                else:
                    logger.error(f"❌ Не удалось отправить после {self.max_retries} попыток: {e}", exc_info=True)
                    return False

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML"
    ) -> bool:
        """Отправить текстовое сообщение"""
        return await self._retry_send(
            self.bot.send_message,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )

    async def send_photo(
        self,
        chat_id: str,
        photo_path: str,
        caption: str = "",
        parse_mode: str = "HTML"
    ) -> bool:
        """Отправить фото с подписью"""
        if not os.path.exists(photo_path):
            logger.warning(f"Фото не найдено: {photo_path}")
            return False

        photo = FSInputFile(photo_path)
        return await self._retry_send(
            self.bot.send_photo,
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode
        )

    async def send_signal_alert(
        self,
        chat_id: str,
        symbol: str,
        analysis: dict
    ) -> bool:
        """Отправить структурированное уведомление о сигнале"""
        try:
            f1_passed, f1_change = analysis.get('filter_1_price', (False, 0))
            f2_passed, f2_rsi = analysis.get('filter_2_rsi_1h', (False, 0))
            f3_passed, f3_rsi = analysis.get('filter_3_rsi_15m', (False, 0))

            message = (
                f"🚨 <b>СИГНАЛ ОБНАРУЖЕН!</b>\n\n"
                f"📊 Символ: <b>{symbol}</b>\n\n"
                f"✅ <b>Фильтр 1 (Цена 15м):</b> {'✓ PASSED' if f1_passed else '✗ FAILED'}\n"
                f"   Изменение: {f1_change:.2f}%\n\n"
                f"✅ <b>Фильтр 2 (RSI 1h):</b> {'✓ PASSED' if f2_passed else '✗ FAILED'}\n"
                f"   RSI: {f2_rsi:.2f}\n\n"
                f"✅ <b>Фильтр 3 (RSI 15m):</b> {'✓ PASSED' if f3_passed else '✗ FAILED'}\n"
                f"   RSI: {f3_rsi:.2f}\n\n"
                f"🎯 <b>Итог:</b> {'СИГНАЛ ГОТОВ!' if analysis.get('signal_triggered') else 'Условия не выполнены'}"
            )

            return await self.send_message(chat_id, message)

        except Exception as e:
            logger.error(f"Ошибка при формировании сообщения сигнала: {e}", exc_info=True)
            return False

    async def close(self):
        """Закрыть сессию Telegram бота"""
        try:
            await self.bot.session.close()
            logger.info("✅ Telegram сессия закрыта")
        except Exception as e:
            logger.warning(f"⚠️ Ошибка при закрытии сессии: {e}")
