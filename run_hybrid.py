#!/usr/bin/env python3
"""
Гибридный мониторинг MEXC (WebSocket + REST API + ChartGenerator)
ИСПРАВЛЕНО: Правильная отправка графиков в Telegram
"""

from pathlib import Path
import asyncio
import logging
import time
from typing import Dict, List
from collections import defaultdict

from config.settings import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, PRICE_CHANGE_THRESHOLD,
    RSI_OVERBOUGHT, RSI_OVERSOLD, RSI_PERIOD
)
from bot.services import TelegramService
from services.mexc.api_client import MexcClient
from services.analysis import RSICalculator
from services.mexc.ws_client import MexcWSClient
from bot.utils.chart_generator import ChartGenerator

# Логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Фильтр лишних сообщений
class WsNoiseFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Неизвестный формат сообщения" in msg and "'data': 'success'" in msg:
            return False
        return True


for name in logging.root.manager.loggerDict:
    logging.getLogger(name).addFilter(WsNoiseFilter())

SYMBOLS_FILE = Path("data/symbols_usdt.txt")


class HybridMonitor:
    def __init__(self, bot_token: str, chat_id: str):
        self.telegram = TelegramService(bot_token)
        self.chat_id = chat_id

        self.prices: Dict[str, List[float]] = defaultdict(list)
        self.timestamps: Dict[str, List[float]] = defaultdict(list)
        self.max_buffer = 1200

        self.last_signal_time: Dict[str, float] = {}
        self.cooldown = 300

        self.ticks_received = 0
        self.signals_found = 0
        self.price_alerts = 0
        self.start_time = time.time()
        self.is_running = False

    async def handle_ws_message(self, data: dict):
        try:
            symbol = data.get("s", "").upper()
            price = float(data.get("c", 0))
            if not symbol or price <= 0:
                return

            now = time.time()
            self.prices[symbol].append(price)
            self.timestamps[symbol].append(now)

            if len(self.prices[symbol]) > self.max_buffer:
                self.prices[symbol].pop(0)
                self.timestamps[symbol].pop(0)

            self.ticks_received += 1
            await self.check_price_alert(symbol)

        except Exception as e:
            logger.error(f"Ошибка обработки WS: {e}")

    async def check_price_alert(self, symbol: str):
        if len(self.prices[symbol]) < 2:
            return

        now = time.time()
        cutoff_time = now - 900
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
        if price_change >= PRICE_CHANGE_THRESHOLD:
            self.price_alerts += 1
            logger.info(f"[ALERT] {symbol}: {price_change:.2f}% за 15 мин")

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
                logger.warning(f"  -> Нет данных для {symbol}")
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
                self.signals_found += 1
                self.last_signal_time[symbol] = time.time()

                logger.warning(f"🚨 SIGNAL FOUND: {symbol}!")

                # ✅ ИСПРАВЛЕНО: Генерация графика с правильными параметрами
                try:
                    logger.info(f"📈 Генерация графика для {symbol}...")

                    # Получаем данные для графика (5m, последние 12 часов = 144 свечи)
                    async with MexcClient(timeout=30) as client:
                        candles_5m = await client.get_klines(symbol, "5m", 144)

                    if not candles_5m or len(candles_5m) == 0:
                        logger.warning(f"  -> Нет свечей 5m для графика {symbol}")
                    else:
                        # Создаём директорию для графиков
                        Path("charts").mkdir(exist_ok=True)
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        chart_path = f"charts/{symbol}_{timestamp}_signal.png"

                        # Генерируем график
                        chart_path = ChartGenerator.generate_signal_chart(
                            symbol=symbol,
                            candles=candles_5m,  # ✅ Передаём candles напрямую
                            output_path=chart_path
                        )

                        if chart_path and Path(chart_path).exists():
                            logger.info(f"  ✅ График создан: {chart_path}")

                            # ✅ ИСПРАВЛЕНО: Правильный способ отправки фото
                            caption = (
                                f"📊 <b>{symbol}</b> — Сигнал по RSI\n\n"
                                f"📈 Цена: {price_change:+.2f}%\n"
                                f"🔴 RSI 1h: {rsi_1h:.1f}\n"
                                f"🔴 RSI 15m: {rsi_15m:.1f}"
                            )

                            success = await self.telegram.send_photo(
                                chat_id=self.chat_id,
                                photo_path=chart_path,  # ✅ Правильный параметр
                                caption=caption,
                                parse_mode="HTML"
                            )

                            if success:
                                logger.info(f"  ✅ График отправлен в Telegram")
                            else:
                                logger.error(f"  ❌ Ошибка отправки графика")
                        else:
                            logger.error(f"  ❌ График не создан или не найден")

                except Exception as e:
                    logger.error(f"  ❌ Ошибка при работе с графиком {symbol}: {e}", exc_info=True)

                # ✅ Отправка текстового сигнала
                analysis = {
                    'signal_triggered': True,
                    'filter_1_price': (True, price_change),
                    'filter_2_rsi_1h': (True, rsi_1h),
                    'filter_3_rsi_15m': (True, rsi_15m),
                }
                await self.telegram.send_signal_alert(self.chat_id, symbol, analysis)

        except Exception as e:
            logger.error(f"Ошибка RSI для {symbol}: {e}")

    async def stats_loop(self):
        while self.is_running:
            await asyncio.sleep(60)
            uptime = time.time() - self.start_time
            logger.info(f"\n{'=' * 70}")
            logger.info(f"STATS (uptime: {uptime / 60:.1f} мин)")
            logger.info(f"  Тиков: {self.ticks_received}")
            logger.info(f"  Price alerts: {self.price_alerts}")
            logger.info(f"  Сигналов: {self.signals_found}")
            logger.info(f"  Пар активны: {len(self.prices)}")
            logger.info(f"{'=' * 70}\n")

    async def start(self):
        self.is_running = True
        logger.info("=" * 70)
        logger.info("HYBRID MONITOR (WebSocket + REST API + Charts)")
        logger.info("=" * 70)

        try:
            if not SYMBOLS_FILE.exists():
                raise FileNotFoundError(f"Файл {SYMBOLS_FILE} не найден. Запустите tools/update_symbols.py")

            symbols = [line.strip() for line in SYMBOLS_FILE.read_text().splitlines() if line.strip()]
            logger.info(f"Мониторим {len(symbols)} пар: {symbols[:5]}...")

            await self.telegram.send_message(
                self.chat_id,
                f"✅ WebSocket монитор ЗАПУЩЕН\n\n"
                f"Пар: {len(symbols)}\n"
                f"Фильтры:\n"
                f"  • Цена: ±{PRICE_CHANGE_THRESHOLD}% за 15 мин\n"
                f"  • RSI 1h: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD}\n"
                f"  • RSI 15m: &gt;{RSI_OVERBOUGHT} или &lt;{RSI_OVERSOLD}\n"
                f"  • Cooldown: 5 мин\n"
                f"📊 Графики: ВКЛ"
            )

            ws_client = MexcWSClient(symbols, on_message=self.handle_ws_message)
            await asyncio.gather(ws_client.connect_all(), self.stats_loop(), return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Остановка...")
        except Exception as e:
            logger.error(f"Ошибка: {e}", exc_info=True)
        finally:
            self.is_running = False
            await self.stop()

    async def stop(self):
        uptime = time.time() - self.start_time
        try:
            await self.telegram.send_message(
                self.chat_id,
                f"🛑 Монитор остановлен\n\n"
                f"Работал: {uptime / 3600:.1f}h\n"
                f"Сигналов: {self.signals_found}"
            )
        except:
            pass
        await self.telegram.close()
        logger.info("✓ Остановлен")


async def main():
    monitor = HybridMonitor(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
    await monitor.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Exit")