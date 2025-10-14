import asyncio
import logging
from datetime import datetime, timedelta
from pathlib import Path
from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, LOG_LEVEL
)
from bot.services import TelegramService
from bot.utils import ChartGenerator
from bot.handlers import commands
from services.mexc import OptimizedPairMonitor, MexcClient

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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
            # Fallback на кэш из файла
            self.cached_pairs = self._load_from_file()
            return self.cached_pairs


class MexcSignalBot:
    """Основной класс бота с оптимизацией"""

    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id
        self.monitor = OptimizedPairMonitor(
            signal_cooldown=300,  # 5 минут между повторными сигналами
            max_concurrent=5,  # Увеличено до 5 параллельных проверок
            requests_per_second=2  # 2 запроса в секунду
        )
        self.is_running = False
        self.signals_found = 0
        self.pair_manager = CachedPairManager(cache_duration_hours=24)

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

            self.signals_found += 1
            return True

        except Exception as e:
            logger.error(f"Ошибка обработки сигнала: {e}", exc_info=True)
            return False

    async def monitoring_loop(self):
        """Главный цикл мониторинга всех пар"""
        logger.info("🚀 Запуск цикла мониторинга...")
        self.is_running = True

        cycle_num = 0

        while self.is_running:
            try:
                cycle_num += 1
                start_time = datetime.now()

                logger.info(f"\n{'=' * 60}")
                logger.info(f"🔄 ЦИКЛ #{cycle_num} | {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(f"{'=' * 60}")

                # Получаем список пар (из кэша если возможно)
                symbols_to_check = await self.pair_manager.get_pairs()

                if not symbols_to_check:
                    logger.error("❌ Не удалось получить список пар!")
                    await asyncio.sleep(60)
                    continue

                logger.info(f"📊 Мониторинг {len(symbols_to_check)} пар с MEXC")

                # Мониторим все пары
                signals = await self.monitor.monitor_specific_symbols(symbols_to_check)

                # Обрабатываем найденные сигналы
                for signal in signals:
                    await self.process_signal(signal)

                # Статистика цикла
                elapsed = (datetime.now() - start_time).total_seconds()
                stats = await self.monitor.get_statistics()

                logger.info(f"\n{'=' * 60}")
                logger.info(f"📊 ЦИКЛ #{cycle_num} ЗАВЕРШЁН")
                logger.info(f"{'=' * 60}")
                logger.info(f"⏱️  Время выполнения: {elapsed:.1f}s")
                logger.info(f"🎯 Найдено сигналов: {len(signals)} (всего: {self.signals_found})")
                logger.info(f"📡 API запросов: {stats['total_requests']}")
                logger.info(f"✅ Процент успеха: {stats['success_rate']}")
                logger.info(f"⚠️  Rate limits: {stats['rate_limit_hits']}")
                logger.info(f"{'=' * 60}\n")

                # Ждём перед следующей проверкой
                wait_time = max(CHECK_INTERVAL - elapsed, 10)
                logger.info(f"💤 Ожидание {wait_time:.0f}s перед следующим циклом...")
                await asyncio.sleep(wait_time)

            except KeyboardInterrupt:
                logger.info("⚠️  Прерывание пользователем")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле мониторинга: {e}", exc_info=True)
                await asyncio.sleep(60)

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
                f"  2️⃣ RSI 1h: >70 или <30\n"
                f"  3️⃣ RSI 15m: >70 или <30\n\n"
                f"✅ Мониторинг начался..."
            )

            # Запускаем цикл мониторинга
            await self.monitoring_loop()

        except KeyboardInterrupt:
            logger.info("⚠️  Бот прерван пользователем")
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}", exc_info=True)
        finally:
            await self.stop()

    async def stop(self):
        """Остановить бота"""
        logger.info("🛑 Остановка MEXC Signal Bot...")
        self.is_running = False

        try:
            await self.telegram.send_message(
                self.chat_id,
                f"🛑 <b>Bot остановлен</b>\n\n"
                f"📊 Найдено сигналов: {self.signals_found}"
            )
        except:
            pass

        await self.telegram.close()
        logger.info("✅ Bot остановлен")


async def main():
    """Главная функция"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть установлены в .env")
        return

    bot = MexcSignalBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 До свидания!")