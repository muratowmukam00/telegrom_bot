import asyncio
import logging
from aiogram import Dispatcher, types
from aiogram.filters import Command

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL, LOG_LEVEL
)
from bot.services import TelegramService
from bot.utils import ChartGenerator
from bot.handlers import commands
from services.mexc import PairMonitor

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

class MexcSignalBot:
    """Основной класс бота"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id
        self.monitor = PairMonitor()
        self.is_running = False
    
    async def process_signal(self, signal_data: dict) -> bool:
        """Обработать сигнал: отправить сообщение и график"""
        try:
            symbol = signal_data['symbol']
            analysis = signal_data['analysis']
            prices_5m = signal_data['prices_5m']
            volumes_5m = signal_data['volumes_5m']
            
            logger.info(f"Processing signal for {symbol}...")
            
            # Отправляем алерт
            await self.telegram.send_signal_alert(
                self.chat_id,
                symbol,
                analysis
            )
            
            # Генерируем график
            chart_path = ChartGenerator.generate_signal_chart(
                symbol,
                prices_5m,
                volumes_5m,
                output_path=f"logs/{symbol}_signal.png"
            )
            
            # Отправляем график
            if chart_path:
                await self.telegram.send_photo(
                    self.chat_id,
                    chart_path,
                    caption=f"📊 График {symbol} (5m, последние 12ч)"
                )
            
            return True
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
            return False
    
    async def monitoring_loop(self):
        """Главный цикл мониторинга"""
        logger.info("Starting monitoring loop...")
        self.is_running = True
        
        while self.is_running:
            try:
                logger.debug(f"Checking pairs at {CHECK_INTERVAL}s interval...")
                
                # Мониторим все пары
                signals = await self.monitor.monitor_all_pairs()
                
                # Обрабатываем найденные сигналы
                for signal in signals:
                    await self.process_signal(signal)
                
                if signals:
                    logger.info(f"Found {len(signals)} signals")
                
                # Ждём перед следующей проверкой
                await asyncio.sleep(CHECK_INTERVAL)
            
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(CHECK_INTERVAL)
    
    async def start(self):
        """Запустить бота"""
        logger.info("MEXC Signal Bot starting...")
        
        try:
            # Отправляем уведомление о старте
            await self.telegram.send_message(
                self.chat_id,
                "🤖 <b>MEXC Signal Bot запущен!</b>\n\n"
                "🔄 Мониторинг фьючерсов начался\n"
                "📊 Интервал проверки: " + str(CHECK_INTERVAL) + " сек",
                parse_mode="HTML"
            )
            
            # Запускаем цикл мониторинга
            await self.monitoring_loop()
        
        except KeyboardInterrupt:
            logger.info("Bot interrupted by user")
            await self.stop()
        except Exception as e:
            logger.error(f"Fatal error: {e}")
            await self.stop()
    
    async def stop(self):
        """Остановить бота"""
        logger.info("Stopping MEXC Signal Bot...")
        self.is_running = False
        await self.telegram.close()


async def main():
    """Главная функция"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.error("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set in .env")
        return
    
    bot = MexcSignalBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
