# python
#!/usr/bin/env python3
"""
MEXC Signal Bot - Production Version (Memory optimized)
Гибридный мониторинг (WebSocket + REST API)
Меньшее потребление RAM: использует deque для буферов и агрессивную очистку старых записей
"""

import asyncio
import logging
import signal
import sys
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Dict, Deque, Tuple, List

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


def setup_logging():
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(log_dir / "bot_production.log")
    file_handler.setLevel(logging.INFO)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)


logger = setup_logging()


class WSNoiseFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        noise_patterns = [
            "Неизвестный формат сообщения",
            "'data': 'success'",
            "Подтверждение подписки"
        ]
        return not any(pattern in msg for pattern in noise_patterns)


for name in logging.root.manager.loggerDict:
    logging.getLogger(name).addFilter(WSNoiseFilter())


SYMBOLS_FILE = Path("data/symbols_usdt.txt")
STATS_INTERVAL = 300  # 5 minutes


class HybridMonitor:
    """
    Memory-optimized HybridMonitor
    - uses deque of (timestamp, price) per symbol
    - trims very old data proactively
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id

        # Буферы: deque[(timestamp, price)]
        self.buffers: Dict[str, Deque[Tuple[float, float]]] = {}

        # Максимальный размер буфера по умолчанию - уменьшён для экономии RAM
        self.max_buffer = 300  # previously 1200

        # Контроль сигналов
        self.last_signal_time: Dict[str, float] = {}
        self.cooldown = 300  # 5 minutes

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
        try:
            symbol = data.get("s", "").upper()
            price = float(data.get("c", 0))

            if not symbol or price <= 0:
                return

            now = time.time()

            # Получаем / создаём deque для символа
            buf = self.buffers.get(symbol)
            if buf is None:
                buf = deque(maxlen=self.max_buffer)
                self.buffers[symbol] = buf

            # Добавляем запись (ts, price)
            buf.append((now, price))
            self.ticks_received += 1

            # Агрессивная очистка: удаляем записи старше 1 часа (очень редко нужны)
            # Оставляем минимум данных для расчёта RSI/графиков; выбор порога можно настроить
            one_hour_ago = now - 3600
            while buf and buf[0][0] < one_hour_ago:
                buf.popleft()

            await self.check_price_alert(symbol)

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка обработки WS: {e}", exc_info=True)

    async def check_price_alert(self, symbol: str):
        buf = self.buffers.get(symbol)
        if not buf or len(buf) < 2:
            return

        now = time.time()
        cutoff_time = now - 900  # 15 minutes

        # Находим старую цену: первое значение с timestamp >= cutoff -> берем предыдущий элемент
        old_price = None
        for i, (ts, p) in enumerate(buf):
            if ts >= cutoff_time:
                if i > 0:
                    old_price = buf[i - 1][1]
                break

        if old_price is None or old_price <= 0:
            return

        new_price = buf[-1][1]
        price_change = abs((new_price - old_price) / old_price * 100)

        if price_change >= PRICE_CHANGE_THRESHOLD:
            self.price_alerts += 1
            logger.info(f"[PRICE ALERT] {symbol}: {price_change:.2f}% за 15 мин")

            last_signal = self.last_signal_time.get(symbol, 0)
            if now - last_signal < self.cooldown:
                return

            await self.verify_with_rsi(symbol, price_change)

    async def verify_with_rsi(self, symbol: str, price_change: float):
        try:
            logger.info(f"[RSI CHECK] {symbol}")

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

            rsi_1h = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
            rsi_15m = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)

            rsi_1h_passed = rsi_1h > RSI_OVERBOUGHT or rsi_1h < RSI_OVERSOLD
            rsi_15m_passed = rsi_15m > RSI_OVERBOUGHT or rsi_15m < RSI_OVERSOLD

            logger.info(f"  RSI 1h: {rsi_1h:.1f} ({'✓' if rsi_1h_passed else '✗'})")
            logger.info(f"  RSI 15m: {rsi_15m:.1f} ({'✓' if rsi_15m_passed else '✗'})")

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
                # Получаем текущую цену и 24h изменение
                ticker = await client.get_24h_price_change(symbol)

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
                    # Извлекаем имя монеты (BTC_USDT -> BTC)
                    coin_name = symbol.replace("_USDT", "")

                    # Формируем caption для графика
                    caption = (
                        f"📊 <b>{symbol}</b> — Сигнал по RSI\n\n"
                        f"📈 Цена (15мин): {price_change:+.2f}%\n"
                        f"🔴 RSI 1h: {rsi_1h:.1f}\n"
                        f"🔴 RSI 15m: {rsi_15m:.1f}"
                    )

                    # Отправляем график
                    await self.telegram.send_photo(
                        chat_id=self.chat_id,
                        photo_path=chart_path,
                        caption=caption
                    )

                    # Получаем текущую цену из последней свечи
                    current_price = float(candles_5m[-1].get("close", 0))

                    # Объем 24h (если есть)
                    volume_24h = sum([float(c.get("vol", 0)) for c in candles_5m[-288:]]) if len(
                        candles_5m) >= 288 else 0
                    volume_24h_str = f"{volume_24h / 1_000_000:.2f}m" if volume_24h > 0 else "N/A"

                    # Изменение 24h
                    change_24h = ticker if ticker else price_change
                    change_24h_str = f"{change_24h:+.1f}%"

                    # Формируем текстовое сообщение после графика
                    text_message = (
                        f"<a href='https://www.mexc.com/futures/perpetual/{coin_name}_USDT'>#{coin_name}</a>  {symbol}\n"
                        f"{'🟢' if price_change > 0 else '🔴'} {price_change:+.2f}%\n"
                        f"{current_price:.6f} USDT\n"
                        f"RSI 1h: {rsi_1h:.2f}\n"
                        f"RSI 15m: {rsi_15m:.2f}\n"
                        f"Объем 24h: {volume_24h_str}\n"
                        f"Изменение 24h: {change_24h_str}"
                    )

                    # Отправляем текстовое сообщение
                    await self.telegram.send_message(
                        chat_id=self.chat_id,
                        text=text_message
                    )

                    logger.info(f"✅ График и информация отправлены для {symbol}")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка отправки сигнала {symbol}: {e}", exc_info=True)


    async def stats_loop(self):
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
                    f"  • Активных пар: {len(self.buffers)}\n"
                    f"{'=' * 70}\n"
                )
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка stats_loop: {e}")

    async def start(self):
        self.is_running = True

        logger.info("=" * 70)
        logger.info("🚀 MEXC SIGNAL BOT (Production Mode)")
        logger.info("=" * 70)

        try:
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

            self.ws_client = MexcWSClient(symbols, on_message=self.handle_ws_message)

            tasks = [
                asyncio.create_task(self.ws_client.connect_all(), name="websocket"),
                asyncio.create_task(self.stats_loop(), name="stats"),
            ]

            await self.shutdown_event.wait()

            logger.info("🛑 Получен сигнал остановки, завершаю задачи...")

            if self.ws_client:
                await self.ws_client.stop()

            for task in tasks:
                if not task.done():
                    task.cancel()

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
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть установлены!")
        sys.exit(1)

    monitor = HybridMonitor(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    def signal_handler(signum, frame):
        signame = signal.Signals(signum).name
        logger.info(f"\n⚠️ Получен сигнал {signame} — инициирую остановку...")
        monitor.is_running = False
        try:
            loop = asyncio.get_event_loop()
            loop.call_soon_threadsafe(monitor.shutdown_event.set)
        except Exception as e:
            logger.error(f"Ошибка установки shutdown_event: {e}")
            sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

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
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Выход")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
