import asyncio
import logging
from collections import deque
from typing import Dict, List

from services.mexc.ws_client import MexcWSClient
from services.analysis.signal_analyzer import SignalAnalyzer
from bot.services.telegram_service import TelegramService
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class WSSignalMonitor:
    """
    Реал-тайм мониторинг сигналов через WebSocket
    - получает поток цен с MEXC Futures
    - хранит последние n цен для каждого символа
    - анализирует RSI и изменение цены
    - отправляет сигналы в Telegram
    """

    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        self.price_buffers: Dict[str, deque] = {}
        self.max_prices = 300  # хранить 300 последних тиков
        self.analyzer = SignalAnalyzer()

        # Telegram уведомления
        self.telegram = TelegramService(TELEGRAM_BOT_TOKEN)

        # cooldown для сигналов (чтобы не спамить)
        self.signal_cooldown = 60  # секунд
        self.last_signal_time: Dict[str, float] = {}

    async def on_message(self, data: dict):
        """
        Обработка каждого нового сообщения от WebSocket
        data: {"s": "BTC_USDT", "c": 65800.5}
        """
        symbol = data.get("s")
        price = float(data.get("c", 0))

        if not symbol or price <= 0:
            return

        # --- Обновляем буфер цен ---
        buf = self.price_buffers.setdefault(symbol, deque(maxlen=self.max_prices))
        buf.append(price)

        # --- Анализируем сигнал, когда есть достаточно данных ---
        if len(buf) < 60:  # минимум для RSI 15m
            return

        # Преобразуем deque в список
        prices = list(buf)

        analysis = self.analyzer.analyze_signal(
            prices_1m=prices[-15:],   # последние 15 тиков (имитация 15 минут)
            prices_15m=prices[-60:],  # последние 60 тиков
            prices_1h=prices[-240:] if len(prices) >= 240 else prices[-60:],  # если хватает
        )

        if analysis["signal_triggered"] and self._can_trigger(symbol):
            self._update_signal_time(symbol)

            logger.info(f"🚨 SIGNAL DETECTED: {symbol} — RSI/PRICE conditions met")
            await self.telegram.send_signal_alert(
                TELEGRAM_CHAT_ID,
                symbol,
                analysis
            )

    async def start(self):
        """Запуск мониторинга"""
        logger.info(f"🚀 Запуск WebSocket-монитора для {len(self.symbols)} пар...")
        ws_client = MexcWSClient(self.symbols, self.on_message)
        await ws_client.connect_all()

    # --- Internal helpers ---

    def _can_trigger(self, symbol: str) -> bool:
        """Проверка cooldown, чтобы не спамить одним и тем же символом"""
        import time
        last = self.last_signal_time.get(symbol, 0)
        return time.time() - last >= self.signal_cooldown

    def _update_signal_time(self, symbol: str):
        import time
        self.last_signal_time[symbol] = time.time()
