from typing import Dict, Optional, Tuple
from .rsi import RSICalculator
from config.settings import (
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, PRICE_CHANGE_THRESHOLD
)

class SignalAnalyzer:
    """Анализ торговых сигналов"""
    
    @staticmethod
    def check_price_change(prices_1m: list) -> Tuple[bool, float]:
        """
        Проверить фильтр 1: Изменение цены >= 8% за последние 15 минут
        
        Args:
            prices_1m: Последние 15 свечей (1 минута)
        
        Returns:
            (Прошёл фильтр, процент изменения)
        """
        if len(prices_1m) < 15:
            return False, 0.0
        
        old_price = float(prices_1m[0])
        new_price = float(prices_1m[-1])
        
        if old_price == 0:
            return False, 0.0
        
        price_change = ((new_price - old_price) / old_price) * 100
        
        passed = abs(price_change) >= PRICE_CHANGE_THRESHOLD
        return passed, price_change
    
    @staticmethod
    def check_rsi_1h(prices_1h: list) -> Tuple[bool, float]:
        """
        Проверить фильтр 2: RSI 1h > 70 или < 30
        
        Args:
            prices_1h: Последние 100+ свечей (1 час)
        
        Returns:
            (Прошёл фильтр, значение RSI)
        """
        if len(prices_1h) < 30:
            return False, 0.0
        
        rsi = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
        passed = rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD
        
        return passed, rsi
    
    @staticmethod
    def check_rsi_15m(prices_15m: list) -> Tuple[bool, float]:
        """
        Проверить фильтр 3: RSI 15min > 70 или < 30
        
        Args:
            prices_15m: Последние 50+ свечей (15 минут)
        
        Returns:
            (Прошёл фильтр, значение RSI)
        """
        if len(prices_15m) < 30:
            return False, 0.0
        
        rsi = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)
        passed = rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD
        
        return passed, rsi
    
    @staticmethod
    def analyze_signal(
        prices_1m: list,
        prices_15m: list,
        prices_1h: list
    ) -> Dict:
        """
        Полный анализ всех трёх фильтров
        
        Returns:
            {
                'signal_triggered': bool,
                'filter_1_price': (bool, float),  # (passed, change%)
                'filter_2_rsi_1h': (bool, float),  # (passed, rsi_value)
                'filter_3_rsi_15m': (bool, float),  # (passed, rsi_value)
            }
        """
        f1_passed, f1_change = SignalAnalyzer.check_price_change(prices_1m)
        f2_passed, f2_rsi = SignalAnalyzer.check_rsi_1h(prices_1h)
        f3_passed, f3_rsi = SignalAnalyzer.check_rsi_15m(prices_15m)
        
        # Сигнал срабатывает если все 3 фильтра прошли
        signal_triggered = f1_passed and f2_passed and f3_passed
        
        return {
            'signal_triggered': signal_triggered,
            'filter_1_price': (f1_passed, f1_change),
            'filter_2_rsi_1h': (f2_passed, f2_rsi),
            'filter_3_rsi_15m': (f3_passed, f3_rsi),
        }
