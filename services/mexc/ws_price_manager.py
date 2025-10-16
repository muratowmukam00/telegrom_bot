import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class WSPriceManager:
    """Хранит последние цены всех USDT пар из WebSocket"""

    def __init__(self, max_minutes: int = 30):
        # Для каждой пары храним очередь [(время, цена)]
        self.prices = defaultdict(lambda: deque(maxlen=max_minutes * 60))
        self.last_update = {}

    async def update_price(self, data: dict):
        """Асинхронно обновить цену (вызывается из WebSocket on_message)"""
        try:
            symbol = data.get("s")
            price = float(data.get("c", 0))
            if not symbol or price <= 0:
                return

            now = datetime.utcnow()
            self.prices[symbol].append((now, price))
            self.last_update[symbol] = now
            logger.debug(f"💾 {symbol}: {price}")
        except Exception as e:
            logger.warning(f"Ошибка в update_price: {e}")

    def get_prices_last_n_minutes(self, symbol: str, minutes: int = 15):
        """Вернуть цены за последние N минут"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        return [p for t, p in self.prices[symbol] if t >= cutoff]

    def get_latest_price(self, symbol: str):
        """Последняя цена"""
        if symbol in self.prices and self.prices[symbol]:
            return self.prices[symbol][-1][1]
        return None

    def count_pairs(self):
        """Сколько пар сейчас обновляется"""
        return len(self.prices)
