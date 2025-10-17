#!/usr/bin/env python3
"""
run_hybrid_optimized.py
Оптимизированная версия run_hybrid.py
- очередь проверки RSI (asyncio.Queue)
- worker pool (по умолчанию 5)
- per-minute full rescan (failsafe)
- ограничение параллелизма через asyncio.Semaphore
- простое кэширование klines (TTL)
- логирование duration RSI checks
- "умная" логика: сначала RSI 1h, 15m только если 1h экстремальный
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


# === Настройка логирования ===
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


# === Фильтр WS шума (по желанию) ===
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
        # некоторые логгеры могут быть не настроены для фильтрации
        pass


# === Константы ===
SYMBOLS_FILE = Path("data/symbols_usdt.txt")
STATS_INTERVAL = 300  # Статистика каждые 5 минут
KLINES_CACHE_TTL = 20  # seconds cache for klines to reduce REST calls
DEFAULT_WORKER_COUNT = 5  # agreed value


class HybridMonitor:
    """
    Оптимизированный гибридный монитор
    """

    def __init__(self, bot_token: str, chat_id: str, worker_count: int = DEFAULT_WORKER_COUNT):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id

        # Буферы цен и времён
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
        self.ws_client: Optional[MexcWSClient] = None

        # Очередь и воркеры для верификации RSI
        self.verify_queue: asyncio.Queue = asyncio.Queue()
        self.worker_count = worker_count
        self.verify_workers: List[asyncio.Task] = []
        self.verify_sem = asyncio.Semaphore(self.worker_count)

        # Кеш klines: key -> (timestamp, data)
        self._klines_cache: Dict[Tuple[str, str], Tuple[float, List[dict]]] = {}

        # Профилинг времени RSI
        self._rsi_durations: List[float] = []

    # -----------------------
    # WS message handler
    # -----------------------
    async def handle_ws_message(self, data: dict):
        """Обработка WebSocket сообщений — lightweight: сохраняем цену и помещаем задачу в очередь при триггере"""
        try:
            symbol = data.get("s", "").upper()
            # поддержка разных форматов: price может быть 'c' или 'price'
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

            # Обновляем буферы
            self.prices[symbol].append(price)
            self.timestamps[symbol].append(now)

            if len(self.prices[symbol]) > self.max_buffer:
                self.prices[symbol].pop(0)
                self.timestamps[symbol].pop(0)

            self.ticks_received += 1

            # Быстрая проверка изменения цены — только enqueue
            await self._maybe_enqueue_price_alert(symbol)

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка обработки WS: {e}", exc_info=True)

    async def _maybe_enqueue_price_alert(self, symbol: str):
        """Лёгкая проверка движения за 15 минут — если превышает порог, кладём в очередь"""
        if len(self.prices[symbol]) < 2:
            return

        now = time.time()
        cutoff_time = now - 900  # 15 минут

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
            logger.info(f"[PRICE ALERT] {symbol}: {price_change:.2f}% за 15 мин (enqueue)")
            # быстрое пропускное решение: проверка cooldown перед enqueue не обязательна,
            # но можно проверить, чтобы не захламлять очередь
            last_signal = self.last_signal_time.get(symbol, 0)
            if time.time() - last_signal < self.cooldown:
                logger.debug(f"Cooldown active for {symbol}, skipping enqueue")
                return
            await self.verify_queue.put((symbol, price_change, time.time()))

    # -----------------------
    # Worker & verification
    # -----------------------
    async def _verify_worker(self, worker_id: int):
        logger.info(f"RSI worker #{worker_id} запущен")
        while self.is_running:
            try:
                item = await self.verify_queue.get()
                if item is None:
                    # sentinel для завершения
                    self.verify_queue.task_done()
                    break

                symbol, price_change, enqueued_at = item

                now = time.time()
                last_signal = self.last_signal_time.get(symbol, 0)
                if now - last_signal < self.cooldown:
                    logger.debug(f"Worker #{worker_id}: Cooldown for {symbol}, skipping")
                    self.verify_queue.task_done()
                    continue

                # Ограничение параллелизма REST-ов
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
        """
        Проверка RSI.
        Оптимизация: сначала запрашиваем 1h, если он экстремальный (за пределами), только тогда запрашиваем 15m.
        Используем кэширование klines чтобы снизить количество REST-запросов.
        """
        try:
            t_start = time.time()
            logger.info(f"[RSI CHECK] {symbol}")

            # Проверка cooldown ещё раз (безопасность)
            now = time.time()
            last_signal = self.last_signal_time.get(symbol, 0)
            if now - last_signal < self.cooldown:
                logger.debug(f"verify_with_rsi: cooldown active for {symbol}")
                return

            # Получаем 1h klines (из кеша при возможности)
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

            # Если 1h не экстремальный — не выполняем 15m (экономим запросы)
            if not rsi_1h_passed:
                logger.debug(f"{symbol}: RSI 1h нейтральный ({rsi_1h:.1f}), пропускаем RSI 15m")
                return

            # Только если 1h экстремальный — запрашиваем 15m
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

            # Если оба подтверждают — отправляем сигнал
            if rsi_1h_passed and rsi_15m_passed:
                await self.send_signal(symbol, price_change, rsi_1h, rsi_15m)
            else:
                logger.debug(f"{symbol}: RSI filters not passed (1h {rsi_1h:.1f}, 15m {rsi_15m:.1f})")

            logger.info(f"RSI check {symbol} done in {time.time() - t_start:.2f}s")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка RSI для {symbol}: {e}", exc_info=True)

    # -----------------------
    # Klines cache helper
    # -----------------------
    async def _get_klines_cached(self, symbol: str, interval: str, limit: int):
        """Возвращает klines либо из cache, либо делает REST-запрос"""
        key = (symbol, interval)
        now = time.time()
        cached = self._klines_cache.get(key)
        if cached:
            ts, data = cached
            if now - ts < KLINES_CACHE_TTL:
                return data

        # Если нет cache или просрочен — запросим
        try:
            async with MexcClient(timeout=30) as client:
                data = await client.get_klines(symbol, interval, limit)
            if data:
                self._klines_cache[key] = (now, data)
            return data
        except Exception as e:
            logger.error(f"Error fetching klines {symbol} {interval}: {e}")
            return None

    # -----------------------
    # Send signal (telegram + chart)
    # -----------------------
    async def send_signal(
            self,
            symbol: str,
            price_change: float,
            rsi_1h: float,
            rsi_15m: float
    ):
        """Отправка сигнала в Telegram (в одном сообщении с графиком и подробным caption)"""
        try:
            self.signals_found += 1
            self.last_signal_time[symbol] = time.time()
            logger.warning(f"🚨 SIGNAL FOUND: {symbol}!")

            # Получаем данные для графика (5m)
            candles_5m = await self._get_klines_cached(symbol, "5m", 144)
            if not candles_5m:
                try:
                    async with MexcClient(timeout=30) as client:
                        candles_5m = await client.get_klines(symbol, "5m", 144)
                except Exception as e:
                    logger.error(f"Не удалось получить 5m для графика {symbol}: {e}")

            # === Дополнительные данные (24h volume, change) ===
            try:
                async with MexcClient(timeout=30) as client:
                    ticker_data = await client.get_ticker(symbol)
                volume_24h = float(ticker_data.get("quoteVolume", 0)) / 1_000_000  # млн
                change_24h = float(ticker_data.get("priceChangePercent", 0))
                last_price = float(ticker_data.get("lastPrice", 0))
                open_price = float(ticker_data.get("openPrice", 0))
            except Exception as e:
                logger.error(f"Ошибка получения 24h данных для {symbol}: {e}")
                volume_24h, change_24h, last_price, open_price = 0, 0, 0, 0

            # === Генерация графика ===
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
                    # === Формируем Telegram caption ===
                    caption = (
                        f"#{symbol}  <b>{symbol}</b>\n\n"
                        f"🟩 <b>{price_change:+.2f}%</b>\n"
                        f"{open_price:.6f} → {last_price:.6f} USDT (за 15 мин)\n\n"
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
                    logger.info(f"✅ Сигнал (в одном сообщении) отправлен для {symbol}")

        except Exception as e:
            self.errors_count += 1
            logger.error(f"Ошибка отправки сигнала {symbol}: {e}", exc_info=True)


    # -----------------------
    # Per-minute full rescan (failsafe)
    # -----------------------
    async def per_minute_rescan(self, symbols: List[str]):
        """Каждую минуту проходим по всем символам и ставим в очередь те, у которых price_change >= threshold"""
        logger.info("per_minute_rescan started")
        while self.is_running:
            try:
                await asyncio.sleep(60)
                if not self.is_running:
                    break
                now = time.time()
                cutoff_time = now - 900  # 15 минут

                for symbol in symbols:
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
                        # дополнительная проверка cooldown перед enqueue
                        last_signal = self.last_signal_time.get(symbol, 0)
                        if time.time() - last_signal < self.cooldown:
                            continue
                        await self.verify_queue.put((symbol, price_change, time.time()))
                # конец for
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Ошибка per_minute_rescan: {e}", exc_info=True)

        logger.info("per_minute_rescan stopped")

    # -----------------------
    # stats loop
    # -----------------------
    async def stats_loop(self):
        """Периодическая статистика"""
        while self.is_running:
            try:
                await asyncio.sleep(STATS_INTERVAL)
                if not self.is_running:
                    break

                uptime = time.time() - self.start_time
                rate = self.ticks_received / uptime if uptime > 0 else 0

                # profiling RSI durations
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

    # -----------------------
    # Start / Stop
    # -----------------------
    async def start(self):
        """Запуск монитора"""
        self.is_running = True

        logger.info("=" * 70)
        logger.info("🚀 MEXC SIGNAL BOT (Optimized Production Mode)")
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

            await self.telegram.send_message(
                self.chat_id,
                f"✅ <b>MEXC Signal Bot (optimized) запущен</b>\n\n"
                f"📊 Пар в мониторинге: {len(symbols)}\n"
                f"🔍 Фильтры:\n"
                f"  • Цена: ±{PRICE_CHANGE_THRESHOLD}% за 15 мин\n"
                f"  • RSI 1h: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD} (первично)\n"
                f"  • RSI 15m: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD} (подтверждение)\n"
                f"  • Cooldown: {self.cooldown} сек\n\n"
                f"🌐 Источник: WebSocket + REST API (workers={self.worker_count})"
            )

            # Создаём WebSocket клиент
            self.ws_client = MexcWSClient(symbols, on_message=self.handle_ws_message)

            # Запускаем воркеры проверки RSI
            for i in range(self.worker_count):
                t = asyncio.create_task(self._verify_worker(i + 1), name=f"rsi_worker_{i+1}")
                self.verify_workers.append(t)

            # Запускаем основные задачи: WS, stats, per_minute_rescan
            tasks = [
                asyncio.create_task(self.ws_client.connect_all(), name="websocket"),
                asyncio.create_task(self.stats_loop(), name="stats"),
                asyncio.create_task(self.per_minute_rescan(symbols), name="per_minute_rescan"),
            ]

            # Ждём shutdown_event
            await self.shutdown_event.wait()
            logger.info("🛑 Получен сигнал остановки, завершаю задачи...")

            # Останавливаем WebSocket
            if self.ws_client:
                await self.ws_client.stop()

            # Посылаем sentinel None для завершения воркеров
            for _ in self.verify_workers:
                await self.verify_queue.put(None)

            # Отменяем все задачи (stats, per_minute_rescan, websocket)
            for task in tasks:
                if not task.done():
                    task.cancel()

            # Отменяем/ожидаем воркеров
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

# -----------------------
# main()
# -----------------------
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
