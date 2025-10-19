#!/usr/bin/env python3
"""
MEXC Signal Bot - Production Version (FIXED)
Гибридный мониторинг (WebSocket + REST API)
✅ Правильная обработка Ctrl+C
"""

import asyncio
import logging
import signal
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

from bot.services import TelegramService
from bot.utils.chart_generator import ChartGenerator
from config.settings import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    PRICE_CHANGE_THRESHOLD,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD
)
from services.analysis import RSICalculator
from services.mexc.api_client import MexcClient
from services.mexc.ws_client import MexcWSClient


# === Настройка логирования ===
def setup_logging():
    """Настроить production logging"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Основной лог
    file_handler = logging.FileHandler(log_dir / "bot_production.log")
    file_handler.setLevel(logging.INFO)

    # Консоль (только важное)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Формат
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)


logger = setup_logging()


# === Фильтр WS шума ===
class WSNoiseFilter(logging.Filter):
    """Убирает лишние WS сообщения из логов"""

    def filter(self, record):
        msg = record.getMessage()
        noise_patterns = [
            "Неизвестный формат сообщения",
            "'data': 'success'",
            "Подтверждение подписки"
        ]
        return not any(pattern in msg for pattern in noise_patterns)


# Применяем фильтр ко всем логгерам
for name in logging.root.manager.loggerDict:
    logging.getLogger(name).addFilter(WSNoiseFilter())

# === Константы ===
SYMBOLS_FILE = Path("data/symbols_usdt.txt")
STATS_INTERVAL = 300  # Статистика каждые 5 минут


class HybridMonitor:
    """
    Production версия гибридного монитора
    ✅ С правильной обработкой остановки
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id

        # Буферы цен
        self.prices: Dict[str, List[float]] = defaultdict(list)
        self.timestamps: Dict[str, List[float]] = defaultdict(list)
        self.max_buffer = 1200

        # Контроль сигналов
        self.last_signal_time: Dict[str, float] = {}
        self.cooldown = 300  # 5 минут

        # Статистика
        self.ticks_received = 0
        self.signals_found = 0
        self.price_alerts = 0
        self.errors_count = 0
        self.start_time = time.time()
        self.last_stats_time = time.time()

        # Флаг остановки
        self.is_running = False
        self.shutdown_event = asyncio.Event()

        # WebSocket клиент
        self.ws_client = None

    async def handle_ws_message(self, data: dict):
        """Обработка WebSocket сообщений"""
        try:
            symbol = data.get("s", "").upper()
            price = float(data.get("c", 0))

            if not symbol or price <= 0:
                return

            now = time.time()

            # Обновляем буферы
            self.prices[symbol].append(price)
            self.timestamps[symbol].append(now)

            # Ограничиваем размер
            if len(self.prices[symbol]) > self.max_buffer:
                self.prices[symbol].pop(0)
                self.timestamps[symbol].pop(0)

            self.ticks_received += 1

            # Проверяем цену
            await self.check_price_alert(symbol)

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка обработки WS: {e}", exc_info=True)

    async def check_price_alert(self, symbol: str):
        """Проверка движения цены за 15 минут"""
        if len(self.prices[symbol]) < 2:
            return

        now = time.time()
        cutoff_time = now - 900  # 15 минут

        # Находим старую цену
        old_price = None
        for i, timestamp in enumerate(self.timestamps[symbol]):
            if timestamp >= cutoff_time:
                if i > 0:
                    old_price = self.prices[symbol][i - 1]
                break

        if old_price is None or old_price <= 0:
            return

        new_price = self.prices[symbol][-1]
        price_change = abs((new_price - old_price) / old_price * 100)

        # Проверяем порог
        if price_change >= PRICE_CHANGE_THRESHOLD:
            self.price_alerts += 1
            logger.info(f"[PRICE ALERT] {symbol}: {price_change:.2f}% за 15 мин")

            # Cooldown
            last_signal = self.last_signal_time.get(symbol, 0)
            if now - last_signal < self.cooldown:
                return

            # Проверяем RSI
            await self.verify_with_rsi(symbol, price_change)

    async def verify_with_rsi(self, symbol: str, price_change: float):
        """Проверка RSI фильтров"""
        try:
            logger.info(f"[RSI CHECK] {symbol}")

            # Получаем данные
            async with MexcClient(timeout=30) as client:
                klines_1h = await client.get_klines(symbol, "1h", 100)
                klines_15m = await client.get_klines(symbol, "15m", 100)

            if not klines_1h or not klines_15m:
                logger.warning(f"Нет данных для {symbol}")
                return

            prices_1h = [float(k.get("close", 0)) for k in klines_1h]
            prices_15m = [float(k.get("close", 0)) for k in klines_15m]

            if len(prices_1h) < 30 or len(prices_15m) < 30:
                return

            # Расчёт RSI
            rsi_1h = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
            rsi_15m = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)

            rsi_1h_passed = rsi_1h > RSI_OVERBOUGHT or rsi_1h < RSI_OVERSOLD
            rsi_15m_passed = rsi_15m > RSI_OVERBOUGHT or rsi_15m < RSI_OVERSOLD

            logger.info(f"  RSI 1h: {rsi_1h:.1f} ({'✓' if rsi_1h_passed else '✗'})")
            logger.info(f"  RSI 15m: {rsi_15m:.1f} ({'✓' if rsi_15m_passed else '✗'})")

            # Все условия выполнены?
            if rsi_1h_passed and rsi_15m_passed:
                await self.send_signal(symbol, price_change, rsi_1h, rsi_15m)

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка RSI для {symbol}: {e}", exc_info=True)

    async def send_signal(
            self,
            symbol: str,
            price_change: float,
            rsi_1h: float,
            rsi_15m: float
    ):
        """Отправка сигнала в Telegram"""
        try:
            self.signals_found += 1
            self.last_signal_time[symbol] = time.time()

            logger.warning(f"🚨 SIGNAL FOUND: {symbol}!")

            # Получаем данные для графика
            async with MexcClient(timeout=30) as client:
                candles_5m = await client.get_klines(symbol, "5m", 144)

            # Формируем анализ
            analysis = {
                'signal_triggered': True,
                'filter_1_price': (True, price_change),
                'filter_2_rsi_1h': (True, rsi_1h),
                'filter_3_rsi_15m': (True, rsi_15m),
            }

            # Отправляем текстовый сигнал
            await self.telegram.send_signal_alert(
                self.chat_id,
                symbol,
                analysis
            )

            # Генерируем и отправляем график
            if candles_5m and len(candles_5m) > 0:
                Path("charts").mkdir(exist_ok=True)
                timestamp = time.strftime("%Y%m%d_%H%M%S")
                chart_path = f"charts/{symbol}_{timestamp}_signal.png"

                chart_path = ChartGenerator.generate_signal_chart(
                    symbol=symbol,
                    candles=candles_5m,
                    output_path=chart_path
                )

                if chart_path and Path(chart_path).exists():
                    caption = (
                        f"📊 <b>{symbol}</b> — Сигнал по RSI\n\n"
                        f"📈 Цена: {price_change:+.2f}%\n"
                        f"🔴 RSI 1h: {rsi_1h:.1f}\n"
                        f"🔴 RSI 15m: {rsi_15m:.1f}"
                    )

                    await self.telegram.send_photo(
                        chat_id=self.chat_id,
                        photo_path=chart_path,
                        caption=caption
                    )
                    logger.info(f"✅ График отправлен для {symbol}")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка отправки сигнала {symbol}: {e}", exc_info=True)

    async def stats_loop(self):
        """Периодическая статистика"""
        while self.is_running:
            try:
                await asyncio.sleep(STATS_INTERVAL)

                if not self.is_running:
                    break

                uptime = time.time() - self.start_time
                rate = self.ticks_received / uptime if uptime > 0 else 0

                logger.info(
                    f"\n{'=' * 70}\n"
                    f"📊 СТАТИСТИКА (uptime: {uptime / 60:.1f} мин)\n"
                    f"  • Тиков получено: {self.ticks_received} ({rate:.1f}/сек)\n"
                    f"  • Price alerts: {self.price_alerts}\n"
                    f"  • Сигналов: {self.signals_found}\n"
                    f"  • Ошибок: {self.errors_count}\n"
                    f"  • Активных пар: {len(self.prices)}\n"
                    f"{'=' * 70}\n"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка stats_loop: {e}")

    async def start(self):
        """Запуск монитора"""
        self.is_running = True

        logger.info("=" * 70)
        logger.info("🚀 MEXC SIGNAL BOT (Production Mode)")
        logger.info("=" * 70)

        try:
            # Загружаем символы
            if not SYMBOLS_FILE.exists():
                raise FileNotFoundError(
                    f"Файл {SYMBOLS_FILE} не найден. "
                    "Запустите: python tools/update_symbols.py"
                )

            symbols = [
                line.strip()
                for line in SYMBOLS_FILE.read_text().splitlines()
                if line.strip()
            ]

            logger.info(f"📊 Загружено {len(symbols)} USDT пар")

            # Отправляем уведомление о старте
            await self.telegram.send_message(
                self.chat_id,
                f"✅ <b>MEXC Signal Bot запущен</b>\n\n"
                f"📊 Пар в мониторинге: {len(symbols)}\n"
                f"🔍 Фильтры:\n"
                f"  • Цена: ±{PRICE_CHANGE_THRESHOLD}% за 15 мин\n"
                f"  • RSI 1h: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD}\n"
                f"  • RSI 15m: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD}\n"
                f"  • Cooldown: 5 мин\n\n"
                f"🌐 Источник: WebSocket + REST API"
            )

            # Создаём WebSocket клиент
            self.ws_client = MexcWSClient(symbols, on_message=self.handle_ws_message)

            # Запускаем задачи
            tasks = [
                asyncio.create_task(self.ws_client.connect_all(), name="websocket"),
                asyncio.create_task(self.stats_loop(), name="stats"),
            ]

            # Ждём сигнала остановки
            await self.shutdown_event.wait()

            logger.info("🛑 Получен сигнал остановки, завершаю задачи...")

            # Останавливаем WebSocket
            if self.ws_client:
                await self.ws_client.stop()

            # Отменяем все задачи
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Ждём завершения всех задач
            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            await self.telegram.send_message(
                self.chat_id,
                f"❌ <b>Критическая ошибка бота</b>\n\n"
                f"<code>{str(e)[:500]}</code>"
            )
        finally:
            await self.stop()

    async def stop(self):
        """Корректная остановка"""
        if not self.is_running:
            return

        logger.info("🛑 Остановка бота...")
        self.is_running = False
        self.shutdown_event.set()

        uptime = time.time() - self.start_time

        try:
            await self.telegram.send_message(
                self.chat_id,
                f"🛑 <b>Бот остановлен</b>\n\n"
                f"⏱ Время работы: {uptime / 3600:.1f}h\n"
                f"📊 Всего сигналов: {self.signals_found}\n"
                f"📈 Обработано тиков: {self.ticks_received}\n"
                f"⚠️ Ошибок: {self.errors_count}"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления об остановке: {e}")

        await self.telegram.close()
        logger.info("✅ Бот остановлен")


async def main():
    """
    Главная функция с правильной обработкой Ctrl+C
    ✅ ИСПРАВЛЕНО: Корректное завершение при SIGINT/SIGTERM
    """

    # Валидация настроек
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть установлены!")
        sys.exit(1)

    # Создаём монитор
    monitor = HybridMonitor(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    # ✅ ПРАВИЛЬНАЯ обработка сигналов
    def signal_handler(signum, frame):
        """Обработчик SIGINT/SIGTERM"""
        signame = signal.Signals(signum).name
        logger.info(f"\n⚠️ Получен сигнал {signame} — инициирую остановку...")

        # Устанавливаем флаг остановки
        monitor.is_running = False

        # Сигнализируем через event
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(monitor.shutdown_event.set)
        except Exception as e:
            logger.error(f"Ошибка установки shutdown_event: {e}")
            # Fallback: force exit
            sys.exit(0)

    # Регистрируем обработчики (работает в главном потоке)
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill

    # Запускаем
    try:
        logger.info("🚀 Запуск бота... (Нажмите Ctrl+C для остановки)")
        await monitor.start()
    except KeyboardInterrupt:
        logger.info("\n⚠️ KeyboardInterrupt — останавливаю...")
        await monitor.stop()
    except Exception as e:
        logger.error(f"❌ Неожиданная ошибка: {e}", exc_info=True)
        await monitor.stop()
        sys.exit(1)


if __name__ == "__main__":
    try:
        # ✅ Запускаем с правильной обработкой Ctrl+C
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Выход")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)