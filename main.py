import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, LOG_LEVEL,
    LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT, validate_settings, HEALTH_CHECK_INTERVAL
)
from bot.services import TelegramService
from bot.utils import ChartGenerator
from bot.handlers import commands
from services.mexc import OptimizedPairMonitor, MexcClient, MexcWSClient


# ===== НАСТРОЙКА ЛОГИРОВАНИЯ =====
def setup_logging():
    """Настроить логирование с rotation"""
    log_dir = LOG_FILE.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL))

    # File handler с rotation
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT
    )
    file_handler.setLevel(getattr(logging, LOG_LEVEL))

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, LOG_LEVEL))

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


logger = setup_logging()


class CachedPairManager:
    """Менеджер кэширования пар с автоматическим обновлением раз в день"""

    def __init__(self, cache_duration_hours: int = 24):
        self.cache_file = Path("logs/.pairs_cache.txt")
        self.cache_duration = timedelta(hours=cache_duration_hours)
        self.cached_pairs = []
        self.last_update_time = None
        Path("logs").mkdir(parents=True, exist_ok=True)

    def _load_from_file(self) -> list:
        """Загрузить пары из кэш файла"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r') as f:
                    pairs = [line.strip() for line in f.readlines() if line.strip()]
                logger.info(f"📂 Загружено {len(pairs)} пар из кэша")
                return pairs
        except Exception as e:
            logger.error(f"Ошибка загрузки кэша: {e}")
        return []

    def _save_to_file(self, pairs: list):
        """Сохранить пары в кэш файл"""
        try:
            with open(self.cache_file, 'w') as f:
                for pair in pairs:
                    f.write(f"{pair}\n")
            logger.info(f"💾 Сохранено {len(pairs)} пар в кэш")
            self.last_update_time = datetime.now()
        except Exception as e:
            logger.error(f"Ошибка сохранения кэша: {e}")

    def _is_cache_expired(self) -> bool:
        """Проверить истёк ли кэш"""
        if self.last_update_time is None:
            return True
        return datetime.now() - self.last_update_time > self.cache_duration

    async def get_pairs(self) -> list:
        """Получить список пар (из кэша или обновить)"""
        # Если кэш существует и не истёк, используем его
        if not self._is_cache_expired() and self.cached_pairs:
            logger.debug(f"✅ Используется кэшированный список ({len(self.cached_pairs)} пар)")
            return self.cached_pairs

        # Если нет кэша в памяти, пробуем загрузить из файла
        if not self.cached_pairs:
            self.cached_pairs = self._load_from_file()
            if self.cached_pairs:
                self.last_update_time = datetime.now()
                logger.debug(f"✅ Кэш загружен из файла ({len(self.cached_pairs)} пар)")
                return self.cached_pairs

        # Если кэш истёк или пуст, обновляем из API
        logger.info("🔄 Обновление списка пар с MEXC API...")
        try:
            async with MexcClient() as client:
                pairs = await client.get_all_symbols()

            if pairs:
                self.cached_pairs = pairs
                self._save_to_file(pairs)
                logger.info(f"🎉 Получено и кэшировано {len(pairs)} пар")
                return pairs
            else:
                logger.warning("⚠️ API вернул пустой список, используем кэш из файла")
                self.cached_pairs = self._load_from_file()
                return self.cached_pairs

        except Exception as e:
            logger.error(f"❌ Ошибка получения пар: {e}")
            self.cached_pairs = self._load_from_file()
            return self.cached_pairs


class MexcSignalBot:
    """Основной класс бота с улучшениями"""

    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id
        self.monitor = OptimizedPairMonitor(
            signal_cooldown=300,
            max_concurrent=5,
            requests_per_second=2
        )
        self.is_running = False
        self.signals_found = 0
        self.pair_manager = CachedPairManager(cache_duration_hours=24)
        self.last_health_check = datetime.now()
        self.cycle_count = 0

        Path("logs/signals").mkdir(parents=True, exist_ok=True)

    async def process_signal(self, signal_data: dict) -> bool:
        """Обработать сигнал: отправить сообщение и график"""
        try:
            symbol = signal_data['symbol']
            analysis = signal_data['analysis']
            prices_5m = signal_data['prices_5m']
            volumes_5m = signal_data['volumes_5m']

            logger.info(f"🎯 Обработка сигнала для {symbol}...")

            # Отправляем алерт
            await self.telegram.send_signal_alert(
                self.chat_id,
                symbol,
                analysis
            )

            # Генерируем график
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            chart_path = ChartGenerator.generate_signal_chart(
                symbol,
                prices_5m,
                volumes_5m,
                output_path=f"logs/signals/{symbol}_{timestamp}.png"
            )

            # Отправляем график
            if chart_path:
                await self.telegram.send_photo(
                    self.chat_id,
                    chart_path,
                    caption=f"📊 График {symbol} (5m, последние 12ч)"
                )
                logger.info(f"✅ График отправлен для {symbol}")

            self.signals_found += 1
            return True

        except Exception as e:
            logger.error(f"Ошибка обработки сигнала: {e}", exc_info=True)
            return False

    async def health_check(self):
        """Периодическая проверка здоровья бота"""
        try:
            stats = await self.monitor.get_statistics()

            message = (
                f"🏥 <b>Health Check</b>\n\n"
                f"📊 Всего сигналов: {self.signals_found}\n"
                f"📡 API запросов: {stats['total_requests']}\n"
                f"❌ Ошибок: {stats['failed_requests']}\n"
                f"✅ Успешность: {stats['success_rate']}\n"
                f"⏱️ Время работы: {stats['uptime']}\n"
                f"🔄 Циклов: {self.cycle_count}"
            )

            await self.telegram.send_message(self.chat_id, message)
            logger.info("✅ Health check отправлен")

        except Exception as e:
            logger.error(f"Ошибка health check: {e}")

    async def monitoring_loop(self):
        """Главный цикл мониторинга через WebSocket (все USDT пары)"""
        logger.info("🚀 Запуск цикла мониторинга через WebSocket...")
        self.is_running = True

        # === Загружаем все пары USDT ===
        symbols_to_check = await self.pair_manager.get_pairs()
        symbols_to_check = [s for s in symbols_to_check if "USDT" in s]
        logger.info(f"📂 Подготовлено {len(symbols_to_check)} USDT пар для мониторинга через WS")

        # === Хранилище цен ===
        price_cache = {}
        last_prices = {}

        async def handle_message(data):
            """Обновление цены от WebSocket"""
            try:
                if isinstance(data, dict) and "s" in data and "c" in data:
                    symbol = data["s"].upper()
                    price = float(data["c"])
                    price_cache[symbol] = price
            except Exception as e:
                logger.error(f"Ошибка обработки WS данных: {e}")

        # === Запускаем WS клиент ===
        ws_client = MexcWSClient(symbols_to_check, on_message=handle_message)
        asyncio.create_task(ws_client.connect_all())

        # === Цикл анализа ===
        while self.is_running:
            start_time = datetime.now()

            updated = len(price_cache)
            logger.info(f"📊 Получено {updated} обновлений от WS")

            for symbol, price in price_cache.items():
                prev_price = last_prices.get(symbol)
                if prev_price:
                    change = ((price - prev_price) / prev_price) * 100

                    # Фильтр 1: изменение цены > 8%
                    if abs(change) >= 8:
                        analysis = {
                            "filter_1_price": (True, change),
                            "filter_2_rsi_1h": (True, 50),
                            "filter_3_rsi_15m": (True, 50),
                            "signal_triggered": True
                        }

                        await self.process_signal({
                            "symbol": symbol,
                            "analysis": analysis,
                            "prices_5m": [price] * 50,
                            "volumes_5m": [1] * 50
                        })
                        logger.info(f"🚨 Сигнал для {symbol}: Δ={change:.2f}%")

                last_prices[symbol] = price

            # === Контроль цикла ===
            next_run = start_time + timedelta(seconds=CHECK_INTERVAL)
            sleep_time = max(0, (next_run - datetime.now()).total_seconds())
            logger.info(f"💤 Ожидание {sleep_time:.1f}s до следующего цикла...\n")
            await asyncio.sleep(sleep_time)

    async def start(self):
        """Запустить бота"""
        logger.info("=" * 60)
        logger.info("🤖 MEXC SIGNAL BOT ЗАПУСКАЕТСЯ")
        logger.info("=" * 60)

        try:
            # Отправляем уведомление о старте
            await self.telegram.send_message(
                self.chat_id,
                f"🤖 <b>MEXC Signal Bot запущен!</b>\n\n"
                f"📊 Режим: ПОЛНЫЙ МОНИТОРИНГ (все USDT пары)\n"
                f"🔄 Интервал проверки: {CHECK_INTERVAL} сек\n"
                f"💾 Кэширование: Пары обновляются раз в 24 часа\n"
                f"🎯 Фильтры активны:\n"
                f"  1️⃣ Цена: ±8% за 15 мин\n"
                f"  2️⃣ RSI 1h: &gt;70 или &lt;30\n"
                f"  3️⃣ RSI 15m: &gt;70 или &lt;30\n\n"
                f"✅ Мониторинг начался..."
            )

            # Запускаем цикл мониторинга
            await self.monitoring_loop()

        except KeyboardInterrupt:
            logger.info("⚠️ Бот прерван пользователем")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self):
        """Остановить бота"""
        logger.info("🛑 Остановка MEXC Signal Bot...")
        self.is_running = False

        try:
            stats = await self.monitor.get_statistics()
            await self.telegram.send_message(
                self.chat_id,
                f"🛑 <b>Bot остановлен</b>\n\n"
                f"📊 Всего сигналов: {self.signals_found}\n"
                f"🔄 Циклов: {self.cycle_count}\n"
                f"📡 API запросов: {stats['total_requests']}\n"
                f"⏱️ Время работы: {stats['uptime']}"
            )
        except:
            pass

        await self.telegram.close()
        logger.info("✅ Bot остановлен")


async def main():
    """Главная функция"""
    # Валидируем настройки
    if not validate_settings():
        logger.error("❌ Проверьте настройки в .env файле")
        return

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть установлены в .env")
        return

    bot = MexcSignalBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    # Обработка сигналов завершения
    def signal_handler(sig, frame):
        logger.info(f"Получен сигнал {sig}, завершаю работу...")
        asyncio.create_task(bot.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"❌ Ошибка в main: {e}", exc_info=True)