"""
Telegram Service - Production Version
Асинхронный сервис для отправки сообщений и уведомлений
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from aiogram import Bot
from aiogram.types import FSInputFile
from aiogram.exceptions import (
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramUnauthorizedError
)

logger = logging.getLogger(__name__)


class TelegramMetrics:
    """Метрики отправки сообщений"""

    def __init__(self):
        self.total_messages = 0
        self.successful_messages = 0
        self.failed_messages = 0
        self.retries = 0
        self.rate_limit_hits = 0
        self.photos_sent = 0
        self.errors_by_type: Dict[str, int] = {}

    def message_sent(self):
        self.total_messages += 1
        self.successful_messages += 1

    def photo_sent(self):
        self.photos_sent += 1

    def message_failed(self):
        self.total_messages += 1
        self.failed_messages += 1

    def retry_attempted(self):
        self.retries += 1

    def rate_limit_hit(self):
        self.rate_limit_hits += 1

    def error_occurred(self, error_type: str):
        self.errors_by_type[error_type] = self.errors_by_type.get(error_type, 0) + 1

    def get_stats(self) -> Dict:
        success_rate = (
            self.successful_messages / self.total_messages * 100
            if self.total_messages > 0
            else 0
        )

        return {
            'total_messages': self.total_messages,
            'successful': self.successful_messages,
            'failed': self.failed_messages,
            'photos_sent': self.photos_sent,
            'retries': self.retries,
            'rate_limit_hits': self.rate_limit_hits,
            'success_rate': f"{success_rate:.1f}%",
            'errors_by_type': self.errors_by_type
        }


class TelegramService:
    """
    Production Telegram сервис

    Features:
    - Автоматические повторы с exponential backoff
    - Обработка Telegram flood control
    - Валидация файлов
    - Метрики отправки
    - Graceful error handling
    """

    MAX_FILE_SIZE = 19_000_000  # 19 MB (лимит Telegram для фото)
    MAX_CAPTION_LENGTH = 1024  # Лимит подписи

    def __init__(
            self,
            bot_token: str,
            max_retries: int = 3,
            retry_delay: int = 2
    ):
        if not bot_token or bot_token == "YOUR_BOT_TOKEN_HERE":
            raise ValueError("Невалидный TELEGRAM_BOT_TOKEN")

        self.bot = Bot(token=bot_token, default_parse_mode="HTML")
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.metrics = TelegramMetrics()

        logger.info("Telegram сервис инициализирован")

    async def _retry_send(
            self,
            func,
            *args,
            **kwargs
    ) -> bool:
        """
        Внутренний метод с retry и обработкой Telegram ошибок

        Args:
            func: Функция отправки (send_message, send_photo, etc.)
            *args, **kwargs: Аргументы функции

        Returns:
            True если успешно, False при ошибке
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                await func(*args, **kwargs)
                return True

            except TelegramRetryAfter as e:
                # Telegram flood control
                wait_time = int(e.retry_after) + 1
                self.metrics.rate_limit_hit()

                logger.warning(
                    f"Telegram flood control: ждём {wait_time}s "
                    f"(попытка {attempt}/{self.max_retries})"
                )

                if attempt < self.max_retries:
                    await asyncio.sleep(wait_time)
                    self.metrics.retry_attempted()
                else:
                    self.metrics.message_failed()
                    self.metrics.error_occurred("TelegramRetryAfter")
                    return False

            except TelegramNetworkError as e:
                # Сетевые ошибки Telegram API
                self.metrics.error_occurred("TelegramNetworkError")

                logger.warning(
                    f"Сетевая ошибка Telegram: {e} "
                    f"(попытка {attempt}/{self.max_retries})"
                )

                if attempt < self.max_retries:
                    wait_time = self.retry_delay * attempt
                    await asyncio.sleep(wait_time)
                    self.metrics.retry_attempted()
                else:
                    self.metrics.message_failed()
                    return False

            except TelegramBadRequest as e:
                # Неправильный запрос (не повторяем)
                self.metrics.message_failed()
                self.metrics.error_occurred("TelegramBadRequest")

                logger.error(
                    f"Неправильный запрос к Telegram: {e}",
                    exc_info=True
                )
                return False

            except TelegramForbiddenError as e:
                # Бот заблокирован пользователем
                self.metrics.message_failed()
                self.metrics.error_occurred("TelegramForbiddenError")

                logger.error(f"Бот заблокирован: {e}")
                return False

            except TelegramUnauthorizedError as e:
                # Невалидный токен (критическая ошибка)
                self.metrics.message_failed()
                self.metrics.error_occurred("TelegramUnauthorizedError")

                logger.critical(f"Невалидный токен Telegram: {e}")
                return False

            except Exception as e:
                # Неожиданные ошибки
                self.metrics.message_failed()
                self.metrics.error_occurred("UnexpectedException")

                logger.error(
                    f"Неожиданная ошибка Telegram: {e}",
                    exc_info=True
                )

                if attempt < self.max_retries:
                    wait_time = self.retry_delay * attempt
                    await asyncio.sleep(wait_time)
                    self.metrics.retry_attempted()
                else:
                    return False

        return False

    async def send_message(
            self,
            chat_id: int | str,
            text: str,
            parse_mode: Optional[str] = None
    ) -> bool:
        """
        Отправить текстовое сообщение

        Args:
            chat_id: ID чата
            text: Текст сообщения
            parse_mode: Режим парсинга (HTML/Markdown)

        Returns:
            True если успешно
        """
        if not text or not text.strip():
            logger.warning("Попытка отправить пустое сообщение")
            return False

        # Обрезаем слишком длинные сообщения
        if len(text) > 4096:
            logger.warning(
                f"Сообщение слишком длинное ({len(text)} символов), "
                "обрезаю до 4096"
            )
            text = text[:4093] + "..."

        logger.debug(f"Отправка сообщения ({len(text)} символов)")

        result = await self._retry_send(
            self.bot.send_message,
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode
        )

        if result:
            self.metrics.message_sent()
            logger.debug("✅ Сообщение отправлено")

        return result

    async def send_photo(
            self,
            chat_id: int | str,
            photo_path: str,
            caption: str = "",
            parse_mode: str = "HTML"
    ) -> bool:
        """
        Отправить фото с подписью

        Args:
            chat_id: ID чата
            photo_path: Путь к файлу
            caption: Подпись к фото
            parse_mode: Режим парсинга подписи

        Returns:
            True если успешно
        """
        # Валидация файла
        if not os.path.exists(photo_path):
            logger.warning(f"Фото не найдено: {photo_path}")
            self.metrics.message_failed()
            return False

        # Проверка размера
        try:
            file_size = os.path.getsize(photo_path)
            if file_size > self.MAX_FILE_SIZE:
                logger.warning(
                    f"Фото слишком большое: {file_size / 1024 / 1024:.1f}MB "
                    f"(макс {self.MAX_FILE_SIZE / 1024 / 1024:.1f}MB)"
                )
                self.metrics.message_failed()
                return False

            if file_size == 0:
                logger.warning(f"Пустой файл: {photo_path}")
                self.metrics.message_failed()
                return False

        except Exception as e:
            logger.error(f"Ошибка проверки файла {photo_path}: {e}")
            self.metrics.message_failed()
            return False

        # Обрезаем подпись если нужно
        if len(caption) > self.MAX_CAPTION_LENGTH:
            logger.warning(
                f"Подпись слишком длинная ({len(caption)} символов), "
                f"обрезаю до {self.MAX_CAPTION_LENGTH}"
            )
            caption = caption[:self.MAX_CAPTION_LENGTH - 3] + "..."

        logger.debug(f"Отправка фото: {photo_path} ({file_size / 1024:.1f}KB)")

        photo = FSInputFile(photo_path)

        result = await self._retry_send(
            self.bot.send_photo,
            chat_id=chat_id,
            photo=photo,
            caption=caption,
            parse_mode=parse_mode
        )

        if result:
            self.metrics.message_sent()
            self.metrics.photo_sent()
            logger.debug("✅ Фото отправлено")

        return result

    async def send_signal_alert(
            self,
            chat_id: int | str,
            symbol: str,
            analysis: Dict[str, Any]
    ) -> bool:
        """
        Отправить структурированное уведомление о сигнале

        Args:
            chat_id: ID чата
            symbol: Символ (BTC_USDT)
            analysis: Результаты анализа

        Returns:
            True если успешно
        """
        try:
            # Извлекаем данные
            f1_passed, f1_change = analysis.get("filter_1_price", (False, 0))
            f2_passed, f2_rsi = analysis.get("filter_2_rsi_1h", (False, 0))
            f3_passed, f3_rsi = analysis.get("filter_3_rsi_15m", (False, 0))
            signal_ready = analysis.get("signal_triggered", False)

            # Форматируем сообщение
            msg = (
                f"🚨 <b>СИГНАЛ ОБНАРУЖЕН!</b>\n\n"
                f"📊 Символ: <b>{symbol}</b>\n\n"
                f"1️⃣ Цена (15м): {'✅ PASSED' if f1_passed else '❌ FAILED'}\n"
                f"   Изменение: {f1_change:+.2f}%\n\n"
                f"2️⃣ RSI 1h: {'✅ PASSED' if f2_passed else '❌ FAILED'}\n"
                f"   RSI: {f2_rsi:.2f}\n\n"
                f"3️⃣ RSI 15m: {'✅ PASSED' if f3_passed else '❌ FAILED'}\n"
                f"   RSI: {f3_rsi:.2f}\n\n"
                f"🎯 Итог: {'<b>СИГНАЛ ГОТОВ ✅</b>' if signal_ready else 'Условия не выполнены ❌'}"
            )

            logger.info(f"Отправка сигнала для {symbol}")
            return await self.send_message(chat_id, msg)

        except Exception as e:
            logger.error(
                f"Ошибка формирования сигнала для {symbol}: {e}",
                exc_info=True
            )
            self.metrics.message_failed()
            return False

    async def close(self):
        """Корректно закрыть сессию Telegram API"""
        try:
            await self.bot.session.close()
            logger.info("✅ Telegram сессия закрыта")
        except Exception as e:
            logger.warning(f"Ошибка закрытия Telegram сессии: {e}")

    def get_metrics(self) -> Dict:
        """Получить метрики отправки"""
        return self.metrics.get_stats()


# === Пример использования ===
async def example():
    """Пример использования production сервиса"""

    # Создаём сервис
    telegram = TelegramService(
        bot_token="YOUR_BOT_TOKEN",
        max_retries=3,
        retry_delay=2
    )

    try:
        # Отправляем текст
        await telegram.send_message(
            chat_id="YOUR_CHAT_ID",
            text="🧪 <b>Тестовое сообщение</b>"
        )

        # Отправляем фото
        await telegram.send_photo(
            chat_id="YOUR_CHAT_ID",
            photo_path="test.png",
            caption="📊 Тестовый график"
        )

        # Отправляем сигнал
        analysis = {
            'signal_triggered': True,
            'filter_1_price': (True, 8.5),
            'filter_2_rsi_1h': (True, 72.3),
            'filter_3_rsi_15m': (True, 75.8),
        }

        await telegram.send_signal_alert(
            chat_id="YOUR_CHAT_ID",
            symbol="BTC_USDT",
            analysis=analysis
        )

        # Метрики
        logger.info(f"Метрики: {telegram.get_metrics()}")

    finally:
        await telegram.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())