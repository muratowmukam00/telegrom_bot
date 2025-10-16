import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from logging.handlers import RotatingFileHandler

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, LOG_LEVEL,
    LOG_FILE, LOG_MAX_BYTES, LOG_BACKUP_COUNT, validate_settings
)
from bot.services import TelegramService
from bot.utils import ChartGenerator
from services.analysis.signal_analyzer import SignalAnalyzer
from services.mexc.api_client import MexcClient
from services.mexc.ws_client import MexcWSClient
from services.mexc.ws_price_manager import WSPriceManager

# === Настройка логирования ===
def setup_logging():
    log_dir = LOG_FILE.parent
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    logger.setLevel(getattr(logging, LOG_LEVEL))

    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT)
    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger

logger = setup_logging()

class MexcSignalBot:
    """Основной WebSocket бот для MEXC"""

    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id
        self.price_manager = WSPriceManager(max_minutes=30)
        self.is_running = False
        self.signals_found = 0
        Path("logs/signals").mkdir(parents=True, exist_ok=True)

    async def process_signal(self, symbol: str, analysis: dict, prices_15m: list):
        """Отправить сообщение и график"""
        try:
            await self.telegram.send_signal_alert(self.chat_id, symbol, analysis)
            chart_path = ChartGenerator.generate_signal_chart(
                symbol,
                prices_5m=prices_15m[-50:],
                volumes_5m=[1]*min(50, len(prices_15m)),
                output_path=f"logs/signals/{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
            )
            if chart_path:
                await self.telegram.send_photo(self.chat_id, chart_path, caption=f"📊 {symbol} (последние 12ч)")
            logger.info(f"✅ Сигнал отправлен: {symbol}")
            self.signals_found += 1
        except Exception as e:
            logger.error(f"Ошибка process_signal: {e}", exc_info=True)

    async def monitoring_loop(self):
        """Основной цикл мониторинга всех USDT пар"""
        logger.info("🚀 Запуск WS мониторинга всех USDT пар...")
        self.is_running = True

        # Получаем список пар
        async with MexcClient() as client:
            all_pairs = await client.get_all_symbols()
        symbols = [s for s in all_pairs if s.endswith("_USDT")]
        logger.info(f"📈 Загружено {len(symbols)} USDT пар")

        # Запускаем WebSocket
        ws_client = MexcWSClient(symbols, on_message=self.price_manager.update_price)
        asyncio.create_task(ws_client.connect_all())

        while self.is_running:
            start = datetime.now()
            pairs_count = self.price_manager.count_pairs()
            logger.info(f"⏱ Проверка {pairs_count} пар ({datetime.now().strftime('%H:%M:%S')})")

            # Анализируем движение цены
            for symbol in symbols:
                prices_15m = self.price_manager.get_prices_last_n_minutes(symbol, 15)
                if len(prices_15m) < 2:
                    continue

                f1_passed, f1_change = SignalAnalyzer.check_price_change(prices_15m)
                if not f1_passed:
                    continue

                # Проверяем RSI только если есть движение
                async with MexcClient() as client:
                    klines_1h = await client.get_klines(symbol, "1h", 120)
                    klines_15m = await client.get_klines(symbol, "15m", 120)

                prices_1h = [float(k["close"]) for k in klines_1h if "close" in k]
                prices_15m_rsi = [float(k["close"]) for k in klines_15m if "close" in k]

                analysis = SignalAnalyzer.analyze_signal(prices_15m, prices_15m_rsi, prices_1h)
                if analysis["signal_triggered"]:
                    await self.process_signal(symbol, analysis, prices_15m)
                    logger.info(f"🚨 {symbol}: Δ={f1_change:.2f}%")

            # Подождать до следующего цикла
            elapsed = (datetime.now() - start).total_seconds()
            await asyncio.sleep(max(0, CHECK_INTERVAL - elapsed))

    async def start(self):
        logger.info("="*60)
        logger.info("🤖 MEXC SIGNAL BOT запущен (WS режим)")
        logger.info("="*60)
        try:
            await self.telegram.send_message(
                self.chat_id,
                "🤖 <b>MEXC WS Bot запущен!</b>\n"
                "🔄 Проверка каждые 60 секунд\n"
                "📊 Источник данных: WebSocket\n"
                "💰 Пары: все USDT фьючерсы"
            )
            await self.monitoring_loop()
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()

    async def stop(self):
        self.is_running = False
        await self.telegram.send_message(self.chat_id, f"🛑 Бот остановлен. Сигналов: {self.signals_found}")
        await self.telegram.close()
        logger.info("✅ Bot остановлен")

async def main():
    if not validate_settings():
        logger.error("❌ Проверь .env настройки")
        return

    bot = MexcSignalBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

    def handle_stop(sig, frame):
        logger.info(f"⚠️ Получен сигнал {sig} — завершаю работу...")
        asyncio.create_task(bot.stop())

    signal.signal(signal.SIGINT, handle_stop)
    signal.signal(signal.SIGTERM, handle_stop)
    await bot.start()

if __name__ == "__main__":
    asyncio.run(main())
