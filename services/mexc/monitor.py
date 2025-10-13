import asyncio
from typing import Dict, List, Tuple, Optional
from .api_client import MexcClient
from services.analysis import SignalAnalyzer
from config.settings import CHECK_INTERVAL
import logging

logger = logging.getLogger(__name__)


class PairMonitor:
    """
    Мониторинг фьючерсных пар MEXC

    Attributes:
        mexc: MEXC API клиент
        last_signal_time: Словарь последних времен сигналов для каждого символа
        signal_cooldown: Время охлаждения между сигналами (секунды)
    """

    def __init__(self, signal_cooldown: int = 300):
        """
        Args:
            signal_cooldown: Время между повторными сигналами для одного символа (сек)
        """
        self.mexc = MexcClient()
        self.last_signal_time: Dict[str, float] = {}
        self.signal_cooldown = signal_cooldown

    async def get_prices_for_symbol(
            self,
            client: MexcClient,
            symbol: str,
            interval: str,
            limit: int
    ) -> List[float]:
        """
        Получить список цен закрытия для символа

        Args:
            client: Уже открытый MEXC клиент
            symbol: Торговая пара
            interval: Интервал (1m, 5m, 15m, 1h)
            limit: Количество свечей

        Returns:
            Список цен закрытия
        """
        try:
            klines = await client.get_klines(symbol, interval, limit)

            if not klines:
                return []

            # Извлекаем цены закрытия
            prices = client.extract_close_prices(klines)
            return prices

        except Exception as e:
            logger.error(f"Error getting prices for {symbol} ({interval}): {e}")
            return []

    async def get_volumes_for_symbol(
            self,
            client: MexcClient,
            symbol: str,
            interval: str,
            limit: int
    ) -> List[float]:
        """
        Получить список объёмов для символа

        Args:
            client: Уже открытый MEXC клиент
            symbol: Торговая пара
            interval: Интервал (1m, 5m, 15m, 1h)
            limit: Количество свечей

        Returns:
            Список объёмов
        """
        try:
            klines = await client.get_klines(symbol, interval, limit)

            if not klines:
                return []

            # Извлекаем объёмы
            volumes = client.extract_volumes(klines)
            return volumes

        except Exception as e:
            logger.error(f"Error getting volumes for {symbol} ({interval}): {e}")
            return []

    async def check_symbol(self, symbol: str, client: Optional[MexcClient] = None) -> Tuple[bool, Dict]:
        """
        Проверить символ на предмет торговых сигналов

        Args:
            symbol: Торговая пара для проверки
            client: Опциональный уже открытый клиент (для оптимизации)

        Returns:
            Tuple[signal_found, signal_data]
            - signal_found: Найден ли сигнал
            - signal_data: Данные сигнала (символ, анализ, цены, объёмы)
        """
        try:
            logger.debug(f"Checking {symbol}...")

            # Если клиент не передан, создаём временный
            if client is None:
                async with self.mexc as temp_client:
                    return await self._check_symbol_with_client(symbol, temp_client)
            else:
                return await self._check_symbol_with_client(symbol, client)

        except Exception as e:
            logger.error(f"Error checking symbol {symbol}: {e}", exc_info=True)
            return False, {}

    async def _check_symbol_with_client(self, symbol: str, client: MexcClient) -> Tuple[bool, Dict]:
        """Внутренний метод проверки с готовым клиентом"""
        # Получаем данные параллельно для ускорения
        results = await asyncio.gather(
            self.get_prices_for_symbol(client, symbol, "1m", 200),
            self.get_prices_for_symbol(client, symbol, "5m", 144),  # 12 часов
            self.get_prices_for_symbol(client, symbol, "15m", 100),
            self.get_prices_for_symbol(client, symbol, "1h", 100),
            self.get_volumes_for_symbol(client, symbol, "5m", 144),
            return_exceptions=True
        )

        # Распаковываем результаты
        prices_1m, prices_5m, prices_15m, prices_1h, volumes_5m = results

        # Проверяем на ошибки
        if any(isinstance(r, Exception) for r in results):
            logger.error(f"Error in gathering data for {symbol}")
            return False, {}

        # Проверяем что все данные получены
        if not all([prices_1m, prices_5m, prices_15m, prices_1h, volumes_5m]):
            logger.debug(f"Incomplete data for {symbol}")
            return False, {}

        # Анализируем сигнал
        analysis = SignalAnalyzer.analyze_signal(
            prices_1m[:15],  # Последние 15 минут (15 свечей по 1м)
            prices_15m,
            prices_1h
        )

        signal_triggered = analysis['signal_triggered']

        if signal_triggered:
            logger.info(f"🔔 Signal detected for {symbol}!")

        return signal_triggered, {
            'symbol': symbol,
            'analysis': analysis,
            'prices_5m': prices_5m,
            'volumes_5m': volumes_5m
        }

    def _check_cooldown(self, symbol: str) -> bool:
        """
        Проверить прошло ли достаточно времени с последнего сигнала

        Args:
            symbol: Торговая пара

        Returns:
            True если можно отправить сигнал, False если cooldown активен
        """
        import time
        current_time = time.time()
        last_time = self.last_signal_time.get(symbol, 0)

        if current_time - last_time >= self.signal_cooldown:
            return True

        remaining = int(self.signal_cooldown - (current_time - last_time))
        logger.debug(f"Cooldown active for {symbol}: {remaining}s remaining")
        return False

    def _update_signal_time(self, symbol: str):
        """Обновить время последнего сигнала для символа"""
        import time
        self.last_signal_time[symbol] = time.time()

    async def monitor_all_pairs(self) -> List[Dict]:
        """
        Мониторить все USDT пары и найти сигналы

        Returns:
            Список найденных сигналов с данными
        """
        try:
            # Используем один клиент для всех запросов
            async with self.mexc as client:
                # Получаем список всех символов
                symbols = await client.get_all_symbols()

                if not symbols:
                    logger.warning("No symbols found")
                    return []

                logger.info(f"Monitoring {len(symbols)} symbols...")

                signals = []

                # Проверяем символы по одному
                for symbol in symbols:
                    try:
                        signal_found, data = await self.check_symbol(symbol, client)

                        if signal_found:
                            # Проверяем cooldown
                            if self._check_cooldown(symbol):
                                signals.append(data)
                                self._update_signal_time(symbol)
                                logger.info(f"✅ Signal added: {symbol}")
                            else:
                                logger.debug(f"Signal ignored (cooldown): {symbol}")

                        # Небольшая задержка между проверками
                        await asyncio.sleep(0.1)

                    except Exception as e:
                        logger.error(f"Error processing {symbol}: {e}")
                        continue

                if signals:
                    logger.info(f"Found {len(signals)} signals total")
                else:
                    logger.debug("No signals found in this cycle")

                return signals

        except Exception as e:
            logger.error(f"Error monitoring pairs: {e}", exc_info=True)
            return []

    async def monitor_specific_symbols(self, symbols: List[str]) -> List[Dict]:
        """
        Мониторить только определённые символы

        Args:
            symbols: Список символов для мониторинга

        Returns:
            Список найденных сигналов
        """
        logger.info(f"Monitoring {len(symbols)} specific symbols...")

        signals = []

        # Используем один клиент для всех запросов
        async with self.mexc as client:
            for symbol in symbols:
                try:
                    signal_found, data = await self.check_symbol(symbol, client)

                    if signal_found and self._check_cooldown(symbol):
                        signals.append(data)
                        self._update_signal_time(symbol)
                        logger.info(f"✅ Signal found: {symbol}")

                    await asyncio.sleep(0.1)

                except Exception as e:
                    logger.error(f"Error checking {symbol}: {e}")
                    continue

        return signals


# Пример использования
async def example_usage():
    """Пример использования монитора"""
    monitor = PairMonitor(signal_cooldown=300)  # 5 минут

    # Вариант 1: Мониторить все пары
    signals = await monitor.monitor_all_pairs()
    print(f"Found {len(signals)} signals")

    # Вариант 2: Мониторить только топ пары
    top_symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    signals = await monitor.monitor_specific_symbols(top_symbols)
    print(f"Found {len(signals)} signals in top pairs")


if __name__ == "__main__":
    asyncio.run(example_usage())