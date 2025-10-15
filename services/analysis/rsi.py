import numpy as np
import logging
from typing import List

logger = logging.getLogger(__name__)

class RSICalculator:
    """Расчёт RSI (Relative Strength Index)"""

    @staticmethod
    def calculate(prices: List[float], period: int = 14) -> List[float]:
        """Рассчитать RSI для списка цен."""
        if not prices or len(prices) <= period:
            logger.debug("Недостаточно данных для расчёта RSI.")
            return []

        prices = np.array(prices, dtype=float)
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])

        rsi_values = []

        for i in range(period, len(prices)):
            if i > period:
                avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period

            if avg_loss == 0:
                rsi = 100.0 if avg_gain > 0 else 0.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

            rsi_values.append(rsi)

        logger.debug(f"RSI calculated (period={period}) → last={rsi_values[-1]:.2f}")
        return rsi_values

    @staticmethod
    def get_last_rsi(prices: List[float], period: int = 14) -> float:
        """Получить последнее значение RSI."""
        values = RSICalculator.calculate(prices, period)
        return values[-1] if values else 0.0
