import numpy as np
import logging
from typing import List

logger = logging.getLogger(__name__)


class RSICalculator:
    """Расчёт RSI (Relative Strength Index) как в TradingView"""

    @staticmethod
    def calculate(prices: List[float], period: int = 14) -> List[float]:
        """
        Рассчитать RSI для списка цен (алгоритм Wilder's как в TradingView).
        Возвращает массив той же длины что и входной.
        """
        if not prices or len(prices) < 2:
            logger.debug("Недостаточно данных для расчёта RSI.")
            return [0.0] * len(prices)

        prices = np.array(prices, dtype=float)
        n = len(prices)

        # Вычисляем изменения цены
        deltas = np.diff(prices)
        deltas = np.insert(deltas, 0, 0)  # Добавляем 0 в начало

        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        rsi_values = [0.0] * period  # Первые period значений = 0

        if n <= period:
            return rsi_values[:n]

        # Инициализация: первое значение — простое среднее
        avg_gain = np.sum(gains[1:period + 1]) / period
        avg_loss = np.sum(losses[1:period + 1]) / period

        # Вычисляем первое RSI
        if avg_loss == 0:
            first_rsi = 100.0 if avg_gain > 0 else 0.0
        else:
            rs = avg_gain / avg_loss
            first_rsi = 100 - (100 / (1 + rs))
        rsi_values.append(first_rsi)

        # Остальные значения с методом Wilder's smoothing
        for i in range(period + 1, n):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period

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