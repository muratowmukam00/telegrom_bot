from collections import deque
from datetime import datetime, timedelta

class PriceBuffer:
    """Хранит историю цен для каждой пары"""

    def __init__(self, max_minutes=60):
        self.buffer = deque()
        self.max_minutes = max_minutes

    def add(self, price: float):
        now = datetime.now()
        self.buffer.append((now, price))
        self._trim()

    def _trim(self):
        """Удаляет старые записи"""
        cutoff = datetime.now() - timedelta(minutes=self.max_minutes)
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def get_prices(self, minutes: int) -> list:
        """Возвращает цены за последние N минут"""
        cutoff = datetime.now() - timedelta(minutes=minutes)
        return [p for t, p in self.buffer if t >= cutoff]

    def get_latest(self) -> float:
        return self.buffer[-1][1] if self.buffer else 0.0
