from typing import Dict, Tuple, List
from .rsi import RSICalculator
from config.settings import (
    RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD, PRICE_CHANGE_THRESHOLD
)
import logging

logger = logging.getLogger(__name__)


class SignalAnalyzer:
    """Класс для анализа торговых сигналов на основе цены и RSI."""

    @staticmethod
    def check_price_change(prices_1m: List[float]) -> Tuple[bool, float]:
        """
        Проверяет фильтр 1: изменение цены >= PRICE_CHANGE_THRESHOLD за последние 15 минут.

        Args:
            prices_1m (list[float]): последние 15 свечей (1 минута)

        Returns:
            tuple(bool, float): (прошёл фильтр, процент изменения)
        """
        try:
            if not prices_1m or len(prices_1m) < 15:
                logger.debug("Недостаточно данных для фильтра цены (1м).")
                return False, 0.0

            old_price = float(prices_1m[0])
            new_price = float(prices_1m[-1])

            if old_price <= 0:
                logger.warning("Некорректное значение old_price (<=0).")
                return False, 0.0

            price_change = ((new_price - old_price) / old_price) * 100
            passed = abs(price_change) >= PRICE_CHANGE_THRESHOLD

            return passed, price_change

        except Exception as e:
            logger.error(f"Ошибка при расчёте изменения цены: {e}", exc_info=True)
            return False, 0.0

    @staticmethod
    def check_rsi_1h(prices_1h: List[float]) -> Tuple[bool, float]:
        """
        Проверяет фильтр 2: RSI 1h > RSI_OVERBOUGHT или < RSI_OVERSOLD.

        Args:
            prices_1h (list[float]): последние 100+ свечей (1 час)

        Returns:
            tuple(bool, float): (прошёл фильтр, значение RSI)
        """
        try:
            if not prices_1h or len(prices_1h) < 30:
                logger.debug("Недостаточно данных для фильтра RSI 1h.")
                return False, 0.0

            rsi = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
            passed = rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD

            return passed, rsi

        except Exception as e:
            logger.error(f"Ошибка при проверке RSI 1h: {e}", exc_info=True)
            return False, 0.0

    @staticmethod
    def check_rsi_15m(prices_15m: List[float]) -> Tuple[bool, float]:
        """
        Проверяет фильтр 3: RSI 15m > RSI_OVERBOUGHT или < RSI_OVERSOLD.

        Args:
            prices_15m (list[float]): последние 50+ свечей (15 минут)

        Returns:
            tuple(bool, float): (прошёл фильтр, значение RSI)
        """
        try:
            if not prices_15m or len(prices_15m) < 30:
                logger.debug("Недостаточно данных для фильтра RSI 15m.")
                return False, 0.0

            rsi = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)
            passed = rsi > RSI_OVERBOUGHT or rsi < RSI_OVERSOLD

            return passed, rsi

        except Exception as e:
            logger.error(f"Ошибка при проверке RSI 15m: {e}", exc_info=True)
            return False, 0.0

    @staticmethod
    def analyze_signal(
        prices_1m: List[float],
        prices_15m: List[float],
        prices_1h: List[float]
    ) -> Dict[str, Tuple[bool, float]]:
        """
        Полный анализ трёх фильтров для формирования торгового сигнала.

        Returns:
            dict: {
                'signal_triggered': bool,
                'filter_1_price': (bool, float),
                'filter_2_rsi_1h': (bool, float),
                'filter_3_rsi_15m': (bool, float),
            }
        """
        try:
            f1_passed, f1_change = SignalAnalyzer.check_price_change(prices_1m)
            f2_passed, f2_rsi = SignalAnalyzer.check_rsi_1h(prices_1h)
            f3_passed, f3_rsi = SignalAnalyzer.check_rsi_15m(prices_15m)

            signal_triggered = f1_passed and f2_passed and f3_passed

            logger.debug(
                f"Результаты фильтров → "
                f"Цена: {f1_passed} ({f1_change:.2f}%), "
                f"RSI_1h: {f2_passed} ({f2_rsi:.2f}), "
                f"RSI_15m: {f3_passed} ({f3_rsi:.2f}), "
                f"Сигнал: {signal_triggered}"
            )

            return {
                'signal_triggered': signal_triggered,
                'filter_1_price': (f1_passed, f1_change),
                'filter_2_rsi_1h': (f2_passed, f2_rsi),
                'filter_3_rsi_15m': (f3_passed, f3_rsi),
            }

        except Exception as e:
            logger.error(f"Ошибка при анализе сигнала: {e}", exc_info=True)
            return {
                'signal_triggered': False,
                'filter_1_price': (False, 0.0),
                'filter_2_rsi_1h': (False, 0.0),
                'filter_3_rsi_15m': (False, 0.0),
            }
