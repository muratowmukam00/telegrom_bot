import asyncio
import logging
from datetime import datetime
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CHECK_INTERVAL
from bot.services import TelegramService
from bot.utils import ChartGenerator
from services.analysis.signal_analyzer import SignalAnalyzer
from services.mexc.ws_client import MexcWSClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class WebSocketSignalBot:
    def __init__(self, token, chat_id):
        self.telegram = TelegramService(token)
        self.chat_id = chat_id
        self.price_cache = {}
        self.last_prices = {}
        self.last_signals = {}
        self.ws_client = None

    async def handle_message(self, data):
        """MEXC WS habaryny gaýtadan işleýär"""
        try:
            if isinstance(data, dict) and "s" in data and "c" in data:
                symbol = data["s"].upper()
                price = float(data["c"])
                self.price_cache[symbol] = self.price_cache.get(symbol, [])[-200:] + [price]
                logger.info(f"💾 Добавлена цена для {symbol}: {price}, кэш: {len(self.price_cache[symbol])} цен")
            else:
                logger.warning(f"⚠️ Неправильный формат данных: {data}")
        except Exception as e:
            logger.error(f"Handle message error: {e}")

    async def analyze_loop(self):
        """Bahalaryň üýtgeýşini we RSI-ni barlaýan esasy loop"""
        while True:
            try:
                logger.debug(f"🔄 Запуск цикла анализа, пар в кэше: {len(self.price_cache)}")
                for symbol, prices in list(self.price_cache.items()):
                    logger.debug(f"📊 Анализ для {symbol}, цен: {len(prices)}")
                    if len(prices) < 20:
                        logger.debug(f"⏳ Недостаточно данных для {symbol}: {len(prices)} цен")
                        continue

                    analysis = SignalAnalyzer.analyze_signal(
                        prices_1m=prices[-15:],
                        prices_15m=prices[-60:],
                        prices_1h=prices[-200:]
                    )

                    if analysis["signal_triggered"]:
                        last_signal_time = self.last_signals.get(symbol, datetime.min)
                        if (datetime.now() - last_signal_time).seconds < 300:
                            logger.debug(f"🛑 Cooldown для {symbol}, последний сигнал: {last_signal_time}")
                            continue

                        self.last_signals[symbol] = datetime.now()

                        # RSI we üýtgeýiş maglumatlaryny ýaz
                        change = analysis["filter_1_price"][1]
                        logger.info(f"🚨 Signal: {symbol} Δ={change:.2f}%")

                        await self.telegram.send_signal_alert(self.chat_id, symbol, analysis)

                        # Grafik döret
                        chart_path = ChartGenerator.generate_signal_chart(
                            symbol=symbol,
                            prices_5m=prices[-60:],
                            volumes_5m=[1] * len(prices[-60:]),
                            output_path=f"logs/signals/{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                        )
                        await self.telegram.send_photo(self.chat_id, chart_path,
                                                       caption=f"📊 {symbol} - Real-time 5m Chart")
            except Exception as e:
                logger.error(f"Analysis loop error: {e}")
            await asyncio.sleep(CHECK_INTERVAL)

    async def start(self):
        symbols = ["BTC_USDT"]
        logger.info(f"Starting WS bot for {len(symbols)} pairs...")
        self.ws_client = MexcWSClient(symbols, on_message=self.handle_message)
        asyncio.create_task(self.ws_client.connect_all())
        await self.analyze_loop()


async def main():
    bot = WebSocketSignalBot(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
