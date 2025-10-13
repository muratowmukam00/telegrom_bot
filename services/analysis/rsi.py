import numpy as np
from typing import List, Tuple

class RSICalculator:
    """Расчёт RSI (Relative Strength Index)"""
    
    @staticmethod
    def calculate(prices: List[float], period: int = 14) -> List[float]:
        """
        Рассчитать RSI для списка цен
        
        Args:
            prices: Список цен (close prices)
            period: Период RSI (обычно 14)
        
        Returns:
            Список значений RSI
        """
        if len(prices) < period + 1:
            return []
        
        prices = np.array(prices, dtype=float)
        
        # Рассчитываем изменения
        deltas = np.diff(prices)
        
        # Отделяем gains и losses
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # Инициализируем средние значения
        avg_gain = np.mean(gains[:period])
        avg_loss = np.mean(losses[:period])
        
        rsi_values = []
        
        # Рассчитываем RSI для каждого периода
        for i in range(period, len(prices)):
            if i > period:
                avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
                avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
            
            if avg_loss == 0:
                rsi = 100 if avg_gain > 0 else 0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            
            rsi_values.append(rsi)
        
        return rsi_values
    
    @staticmethod
    def get_last_rsi(prices: List[float], period: int = 14) -> float:
        """Получить последнее значение RSI"""
        rsi_values = RSICalculator.calculate(prices, period)
        return rsi_values[-1] if rsi_values else 0.0
