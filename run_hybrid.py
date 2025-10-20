#!/usr/bin/env python3
"""
run_hybrid_optimized.py - ИСПРАВЛЕННАЯ ВЕРСИЯ
Фиксы:
1. Cooldown проверяется ДО enqueue (не после RSI)
2. Добавлен tracking последней проверки (last_check_time)
3. Per-minute rescan учитывает последнюю проверку
4. Убрана дублирующая очередь задач
"""

import asyncio
import logging
import signal
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    """Настроить production logging"""
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    file_handler = logging.FileHandler(log_dir / "bot_production_optimized.log")
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
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    return logging.getLogger(__name__)


logger = setup_logging()


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


for name in logging.root.manager.loggerDict:
    try:
        logging.getLogger(name).addFilter(WSNoiseFilter())
    except Exception:
        pass


SYMBOLS_FILE = Path("data/symbols_usdt.txt")
STATS_INTERVAL = 300
KLINES_CACHE_TTL = 20
DEFAULT_WORKER_COUNT = 5
CHECK_COOLDOWN = 60  # ⚡ НОВОЕ: минимальное время между проверками одной монеты


class HybridMonitor:
    """Оптимизированный гибридный монитор с правильным cooldown"""

    def __init__(self, bot_token: str, chat_id: str, worker_count: int = DEFAULT_WORKER_COUNT):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id

        self.prices: Dict[str, List[float]] = defaultdict(list)
        self.timestamps: Dict[str, List[float]] = defaultdict(list)
        self.max_buffer = 1200

        # ⚡ ИСПРАВЛЕНО: Раздельный tracking для проверок и сигналов
        self.last_check_time: Dict[str, float] = {}  # Когда последний раз проверяли RSI
        self.last_signal_time: Dict[str, float] = {}  # Когда последний раз отправляли сигнал
        self.check_cooldown = CHECK_COOLDOWN  # 1 минута между проверками
        self.signal_cooldown = 300  # 5 минут между сигналами

        self.ticks_received = 0
        self.signals_found = 0
        self.price_alerts = 0
        self.errors_count = 0
        self.start_time = time.time()
        self.last_stats_time = time.time()

        self.is_running = False
        self.shutdown_event = asyncio.Event()
        self.ws_client: Optional[MexcWSClient] = None

        self.verify_queue: asyncio.Queue = asyncio.Queue()
        self.worker_count = worker_count
        self.verify_workers: List[asyncio.Task] = []
        self.verify_sem = asyncio.Semaphore(self.worker_count)

        self._klines_cache: Dict[Tuple[str, str], Tuple[float, List[dict]]] = {}
        self._rsi_durations: List[float] = []

    async def handle_ws_message(self, data: dict):
        """Обработка WebSocket сообщений"""
        try:
            symbol = data.get("s", "").upper()
            price_raw = data.get("c", data.get("price", None))
            if price_raw is None:
                return
            try:
                price = float(price_raw)
            except Exception:
                return

            if not symbol or price <= 0:
                return

            now = time.time()

            self.prices[symbol].append(price)
            self.timestamps[symbol].append(now)

            if len(self.prices[symbol]) > self.max_buffer:
                self.prices[symbol].pop(0)
                self.timestamps[symbol].pop(0)

            self.ticks_received += 1

            await self._maybe_enqueue_price_alert(symbol)

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка обработки WS: {e}", exc_info=True)

    async def _maybe_enqueue_price_alert(self, symbol: str):
        """Проверка движения цены с cooldown на ПРОВЕРКУ (не на сигнал)"""
        if len(self.prices[symbol]) < 2:
            return

        now = time.time()

        # ⚡ ИСПРАВЛЕНО: Проверяем cooldown на ПРОВЕРКУ (не на сигнал)
        last_check = self.last_check_time.get(symbol, 0)
        if now - last_check < self.check_cooldown:
            return  # Эту монету проверяли недавно

        cutoff_time = now - 900

        old_price = None
        ts = self.timestamps[symbol]
        pr = self.prices[symbol]
        for i, t in enumerate(ts):
            if t >= cutoff_time:
                if i > 0:
                    old_price = pr[i - 1]
                break

        if old_price is None or old_price <= 0:
            return

        new_price = pr[-1]
        price_change = abs((new_price - old_price) / old_price * 100)

        if price_change >= PRICE_CHANGE_THRESHOLD:
            self.price_alerts += 1
            # ⚡ ИСПРАВЛЕНО: Обновляем last_check_time СРАЗУ при enqueue
            self.last_check_time[symbol] = now
            logger.info(f"[PRICE ALERT] {symbol}: {price_change:.2f}% за 15 мин (enqueue)")
            await self.verify_queue.put((symbol, price_change, now))

    async def _verify_worker(self, worker_id: int):
        """Worker для проверки RSI"""
        logger.info(f"RSI worker #{worker_id} запущен")
        while self.is_running:
            try:
                item = await self.verify_queue.get()
                if item is None:
                    self.verify_queue.task_done()
                    break

                symbol, price_change, enqueued_at = item

                # ⚡ ИСПРАВЛЕНО: Проверяем signal cooldown (не check cooldown)
                now = time.time()
                last_signal = self.last_signal_time.get(symbol, 0)
                if now - last_signal < self.signal_cooldown:
                    logger.debug(f"Worker #{worker_id}: Signal cooldown for {symbol}, skipping")
                    self.verify_queue.task_done()
                    continue

                async with self.verify_sem:
                    t0 = time.time()
                    try:
                        await self.verify_with_rsi(symbol, price_change)
                    except Exception as e:
                        logger.error(f"Worker #{worker_id} error for {symbol}: {e}", exc_info=True)
                    duration = time.time() - t0
                    self._rsi_durations.append(duration)
                    if duration > 3.0:
                        logger.info(f"Slow RSI check for {symbol}: {duration:.2f}s")
                self.verify_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка в _verify_worker: {e}", exc_info=True)

        logger.info(f"RSI worker #{worker_id} завершён")

    async def verify_with_rsi(self, symbol: str, price_change: float):
        """Проверка RSI (сначала 1h, потом 15m только если 1h экстремальный)"""
        try:
            t_start = time.time()
            logger.info(f"[RSI CHECK] {symbol}")

            now = time.time()
            last_signal = self.last_signal_time.get(symbol, 0)
            if now - last_signal < self.signal_cooldown:
                logger.debug(f"verify_with_rsi: signal cooldown active for {symbol}")
                return

            klines_1h = await self._get_klines_cached(symbol, "1h", 100)
            if not klines_1h:
                logger.warning(f"Нет 1h данных для {symbol}")
                return

            prices_1h = [float(k.get("close", 0)) for k in klines_1h]
            if len(prices_1h) < 30:
                logger.debug(f"Недостаточно 1h данных для {symbol}")
                return

            rsi_1h = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
            rsi_1h_passed = rsi_1h > RSI_OVERBOUGHT or rsi_1h < RSI_OVERSOLD

            logger.info(f"  RSI 1h: {rsi_1h:.1f} ({'✓' if rsi_1h_passed else '✗'})")

            if not rsi_1h_passed:
                logger.debug(f"{symbol}: RSI 1h нейтральный ({rsi_1h:.1f}), пропускаем RSI 15m")
                return

            klines_15m = await self._get_klines_cached(symbol, "15m", 100)
            if not klines_15m:
                logger.warning(f"Нет 15m данных для {symbol}")
                return

            prices_15m = [float(k.get("close", 0)) for k in klines_15m]
            if len(prices_15m) < 30:
                logger.debug(f"Недостаточно 15m данных для {symbol}")
                return

            rsi_15m = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)
            rsi_15m_passed = rsi_15m > RSI_OVERBOUGHT or rsi_15m < RSI_OVERSOLD

            logger.info(f"  RSI 15m: {rsi_15m:.1f} ({'✓' if rsi_15m_passed else '✗'})")

            if rsi_1h_passed and rsi_15m_passed:
                await self.send_signal(symbol, price_change, rsi_1h, rsi_15m)
            else:
                logger.debug(f"{symbol}: RSI filters not passed (1h {rsi_1h:.1f}, 15m {rsi_15m:.1f})")

            logger.info(f"RSI check {symbol} done in {time.time() - t_start:.2f}s")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка RSI для {symbol}: {e}", exc_info=True)

    async def _get_klines_cached(self, symbol: str, interval: str, limit: int):
        """Возвращает klines из cache или делает REST-запрос"""
        key = (symbol, interval)
        now = time.time()
        cached = self._klines_cache.get(key)
        if cached:
            ts, data = cached
            if now - ts < KLINES_CACHE_TTL:
                return data

        try:
            async with MexcClient(timeout=30) as client:
                data = await client.get_klines(symbol, interval, limit)
            if data:
                self._klines_cache[key] = (now, data)
            return data
        except Exception as e:
            logger.error(f"Error fetching klines {symbol} {interval}: {e}")
            return None

    async def send_signal(self, symbol: str, price_change: float, rsi_1h: float, rsi_15m: float):
        """Отправка сигнала в Telegram"""
        try:
            self.signals_found += 1
            # ⚡ ИСПРАВЛЕНО: Обновляем SIGNAL cooldown
            self.last_signal_time[symbol] = time.time()
            logger.warning(f"🚨 SIGNAL FOUND: {symbol}!")

            candles_5m = await self._get_klines_cached(symbol, "5m", 144)
            if not candles_5m:
                try:
                    async with MexcClient(timeout=30) as client:
                        candles_5m = await client.get_klines(symbol, "5m", 144)
                except Exception as e:
                    logger.error(f"Не удалось получить 5m для графика {symbol}: {e}")

            try:
                async with MexcClient(timeout=30) as client:
                    ticker_data = await client.get_full_ticker(symbol)

                if ticker_data:
                    volume_24h = ticker_data["quoteVolume"] / 1_000_000
                    change_24h = ticker_data["priceChangePercent"]
                    last_price = ticker_data["lastPrice"]
                    open_price = ticker_data["openPrice"]
                    high_price = ticker_data["highPrice"]
                    low_price = ticker_data["lowPrice"]
                else:
                    volume_24h = change_24h = last_price = open_price = high_price = low_price = 0
            except Exception as e:
                logger.error(f"Ошибка получения full ticker для {symbol}: {e}")
                volume_24h = change_24h = last_price = open_price = high_price = low_price = 0

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
                    price_change_for_caption = price_change if last_price >= open_price else -price_change
                    color_emoji = "🟩" if price_change_for_caption > 0 else "🟥"
                    caption = (
                        f"#{symbol}  <b>{symbol}</b>\n\n"
                        f"{color_emoji} <b>{price_change_for_caption:+.2f}%</b> за 15 мин\n"
                        f"{open_price:.6f} → {last_price:.6f} USDT\n"
                        f"High/Low 24h: {high_price:.6f} / {low_price:.6f}\n\n"
                        f"RSI 1h: <b>{rsi_1h:.2f}</b>\n"
                        f"RSI 15m: <b>{rsi_15m:.2f}</b>\n"
                        f"Объём 24h: <b>{volume_24h:.2f}M</b>\n"
                        f"Изменение 24h: <b>{change_24h:+.2f}%</b>"
                    )

                    await self.telegram.send_photo(
                        chat_id=self.chat_id,
                        photo_path=chart_path,
                        caption=caption,
                        parse_mode="HTML"
                    )
                    logger.info(f"✅ Сигнал отправлен для {symbol}")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка отправки сигнала {symbol}: {e}", exc_info=True)

    async def per_minute_rescan(self, symbols: List[str]):
        """Каждую минуту rescan с учётом last_check_time"""
        logger.info("per_minute_rescan started")
        while self.is_running:
            try:
                await asyncio.sleep(60)
                if not self.is_running:
                    break
                now = time.time()
                cutoff_time = now - 900

                for symbol in symbols:
                    # ⚡ ИСПРАВЛЕНО: Проверяем check cooldown
                    last_check = self.last_check_time.get(symbol, 0)
                    if now - last_check < self.check_cooldown:
                        continue

                    if len(self.prices[symbol]) < 2:
                        continue

                    ts = self.timestamps[symbol]
                    pr = self.prices[symbol]
                    old_price = None
                    for i, t in enumerate(ts):
                        if t >= cutoff_time:
                            if i > 0:
                                old_price = pr[i - 1]
                            break
                    if old_price is None or old_price <= 0:
                        continue

                    new_price = pr[-1]
                    price_change = abs((new_price - old_price) / old_price * 100)
                    if price_change >= PRICE_CHANGE_THRESHOLD:
                        # ⚡ ИСПРАВЛЕНО: Обновляем last_check_time
                        self.last_check_time[symbol] = now
                        await self.verify_queue.put((symbol, price_change, time.time()))

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка per_minute_rescan: {e}", exc_info=True)

        logger.info("per_minute_rescan stopped")

    async def stats_loop(self):
        """Периодическая статистика"""
        while self.is_running:
            try:
                await asyncio.sleep(STATS_INTERVAL)
                if not self.is_running:
                    break

                uptime = time.time() - self.start_time
                rate = self.ticks_received / uptime if uptime > 0 else 0

                avg_rsi = (sum(self._rsi_durations) / len(self._rsi_durations)) if self._rsi_durations else 0
                p95_rsi = sorted(self._rsi_durations)[int(len(self._rsi_durations) * 0.95)] if self._rsi_durations else 0

                logger.info(
                    f"\n{'=' * 70}\n"
                    f"📊 СТАТИСТИКА (uptime: {uptime / 60:.1f} мин)\n"
                    f"  • Тиков получено: {self.ticks_received} ({rate:.1f}/сек)\n"
                    f"  • Price alerts (enqueued): {self.price_alerts}\n"
                    f"  • Сигналов: {self.signals_found}\n"
                    f"  • Ошибок: {self.errors_count}\n"
                    f"  • Активных пар в буфере: {len(self.prices)}\n"
                    f"  • RSI avg time: {avg_rsi:.2f}s, p95: {p95_rsi:.2f}s\n"
                    f"{'=' * 70}\n"
                )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка stats_loop: {e}", exc_info=True)

    async def start(self):
        """Запуск монитора"""
        self.is_running = True

        logger.info("=" * 70)
        logger.info("🚀 MEXC SIGNAL BOT (Fixed Cooldown Version)")
        logger.info("=" * 70)

        try:
            if not SYMBOLS_FILE.exists():
                raise FileNotFoundError(
                    f"Файл {SYMBOLS_FILE} не найден. Запустите: python tools/update_symbols.py"
                )

            symbols = [
                line.strip()
                for line in SYMBOLS_FILE.read_text().splitlines()
                if line.strip()
            ]

            logger.info(f"📊 Загружено {len(symbols)} USDT пар")

            startup_message = (
                f"👋 Привет! <b>MEXC Signal Bot</b> запущен 🎉\n\n"
                f"📊 Сейчас мониторим <b>{len(symbols)}</b> пар\n"
                f"🔍 Используемые фильтры:\n"
                f"  • Изменение цены: ±<b>{PRICE_CHANGE_THRESHOLD}%</b> за 15 минут\n"
                f"  • RSI 1h: &gt;<b>{RSI_OVERBOUGHT}</b> или &lt;<b>{RSI_OVERSOLD}</b> \n"
                f"  • RSI 15m: &gt;<b>{RSI_OVERBOUGHT}</b> или &lt;<b>{RSI_OVERSOLD}</b> \n\n"
                f"⏱ Cooldown между проверками: <b>{self.check_cooldown}s</b>\n"
                f"⏱ Cooldown между сигналами: <b>{self.signal_cooldown}s</b>\n\n"
                f"🌐 Источник данных: https://contract.mexc.com \n\n"
                f"🟢 Бот готов! Когда появится новый сигнал, вы получите уведомление 🚀\n\n"
                f"💰 Удачной торговли и прибыльных сделок!"
            )

            await self.telegram.send_message(
                self.chat_id,
                startup_message,
                parse_mode="HTML"
            )

            self.ws_client = MexcWSClient(symbols, on_message=self.handle_ws_message)

            for i in range(self.worker_count):
                t = asyncio.create_task(self._verify_worker(i + 1), name=f"rsi_worker_{i+1}")
                self.verify_workers.append(t)

            tasks = [
                asyncio.create_task(self.ws_client.connect_all(), name="websocket"),
                asyncio.create_task(self.stats_loop(), name="stats"),
                asyncio.create_task(self.per_minute_rescan(symbols), name="per_minute_rescan"),
            ]

            await self.shutdown_event.wait()
            logger.info("🛑 Получен сигнал остановки, завершаю задачи...")

            if self.ws_client:
                await self.ws_client.stop()

            for _ in self.verify_workers:
                await self.verify_queue.put(None)

            for task in tasks:
                if not task.done():
                    task.cancel()

            for t in self.verify_workers:
                if not t.done():
                    t.cancel()

            await asyncio.gather(*tasks, *self.verify_workers, return_exceptions=True)

        except Exception as e:
            logger.error(f"Критическая ошибка: {e}", exc_info=True)
            try:
                await self.telegram.send_message(
                    self.chat_id,
                    f"❌ <b>Критическая ошибка бота</b>\n\n"
                    f"<code>{str(e)[:500]}</code>"
                )
            except Exception:
                pass
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

        try:
            await self.telegram.close()
        except Exception:
            pass

        logger.info("✅ Бот остановлен")


async def main():
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть установлены!")
        sys.exit(1)

    monitor = HybridMonitor(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, worker_count=DEFAULT_WORKER_COUNT)

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