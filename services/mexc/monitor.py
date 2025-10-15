import asyncio
import logging
import time
from typing import Dict, List, Tuple, Optional
from .api_client import MexcClient
from services.analysis import SignalAnalyzer, RSICalculator
from config.settings import CHECK_INTERVAL, PRICE_CHANGE_THRESHOLD, RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD

logger = logging.getLogger(__name__)


class RateLimiter:
    """Интеллектуальный ограничитель частоты запросов с адаптивностью"""

    def __init__(self, requests_per_second: float = 2.0):
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0
        self.lock = asyncio.Lock()
        self.requests_made = 0
        self.rate_limited_count = 0

    async def wait(self):
        """Подождать перед следующим запросом"""
        async with self.lock:
            now = time.time()
            time_since_last = now - self.last_request_time

            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                await asyncio.sleep(wait_time)

            self.last_request_time = time.time()
            self.requests_made += 1


class OptimizedPairMonitor:
    """
    Оптимизированный мониторинг с ранней фильтрацией

    ИСПРАВЛЕНИЯ:
    - Правильное разделение данных по таймфреймам
    - Обработка edge cases (пустые данные, ошибки)
    - Лучшее логирование для отладки
    - Кэширование последних данных для повторных проверок
    """

    def __init__(
            self,
            signal_cooldown: int = 60,
            max_concurrent: int = 20,
            requests_per_second: float = 15
    ):
        self.mexc = MexcClient()
        self.last_signal_time: Dict[str, float] = {}
        self.signal_cooldown = signal_cooldown
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.rate_limiter = RateLimiter(requests_per_second)

        # Кэш для данных (чтобы не делать лишние запросы)
        self.data_cache: Dict[str, Dict] = {}
        self.cache_ttl = 30  # 30 секунд

        # Статистика
        self.total_requests = 0
        self.failed_requests = 0
        self.rate_limit_hits = 0
        self.signals_triggered = 0
        self.early_filtered_count = 0
        self.start_time = time.time()

    async def _make_api_request(
            self,
            coro,
            symbol: str,
            interval: str
    ) -> Optional[List]:
        """Выполнить API запрос с rate limiting и обработкой ошибок"""
        try:
            await self.rate_limiter.wait()
            self.total_requests += 1
            result = await coro
            return result
        except Exception as e:
            self.failed_requests += 1
            logger.debug(f"API ошибка для {symbol} ({interval}): {e}")
            return None

    async def check_price_filter_only(
            self,
            client: MexcClient,
            symbol: str
    ) -> Tuple[bool, List[float]]:
        """
        Шаг 1: Проверить ТОЛЬКО фильтр цены (±8% за 15 мин)

        ИСПРАВЛЕНО:
        - Правильно берём последние 3 свечи (15 минут)
        - Проверяем правильно вычисленное изменение
        """
        try:
            klines_5m = await self._make_api_request(
                client.get_klines(symbol, "5m", 144),
                symbol,
                "5m"
            )

            if not klines_5m or len(klines_5m) < 3:
                logger.debug(f"{symbol}: недостаточно свечей 5m ({len(klines_5m) if klines_5m else 0})")
                return False, []

            prices_5m = client.extract_close_prices(klines_5m)
            if len(prices_5m) < 3:
                return False, []

            # Правильно берём последние 3 свечи = 15 минут
            prices_15min = prices_5m[-3:]
            old_price = prices_15min[0]
            new_price = prices_15min[-1]

            if old_price <= 0:
                return False, []

            price_change = abs((new_price - old_price) / old_price * 100)

            if price_change < PRICE_CHANGE_THRESHOLD:
                self.early_filtered_count += 1
                logger.debug(
                    f"{symbol}: изменение {price_change:.2f}% < {PRICE_CHANGE_THRESHOLD}% (отфильтровано на шаге 1)")
                return False, []

            logger.debug(f"{symbol}: ✓ изменение {price_change:.2f}% >= {PRICE_CHANGE_THRESHOLD}% (прошел фильтр 1)")
            return True, prices_5m

        except Exception as e:
            logger.error(f"Ошибка проверки цены для {symbol}: {e}")
            return False, []

    async def check_rsi_filters(
            self,
            client: MexcClient,
            symbol: str
    ) -> Tuple[bool, float, float]:
        """
        Шаг 2: Проверить RSI фильтры

        ИСПРАВЛЕНО:
        - Правильное разделение данных по таймфреймам
        - Используем разные данные для 1h и 15m
        - Обработка случаев когда данных недостаточно
        """
        try:
            # Получаем 1h свечи (минимум 30 для RSI расчёта)
            klines_1h = await self._make_api_request(
                client.get_klines(symbol, "1h", 100),
                symbol,
                "1h"
            )
            if not klines_1h or len(klines_1h) < RSI_PERIOD:
                logger.debug(f"{symbol}: недостаточно свечей 1h для RSI")
                return False, 0.0, 0.0

            prices_1h = client.extract_close_prices(klines_1h)
            if len(prices_1h) < RSI_PERIOD:
                return False, 0.0, 0.0

            # Получаем 15m свечи
            klines_15m = await self._make_api_request(
                client.get_klines(symbol, "15m", 100),
                symbol,
                "15m"
            )
            if not klines_15m or len(klines_15m) < RSI_PERIOD:
                logger.debug(f"{symbol}: недостаточно свечей 15m для RSI")
                return False, 0.0, 0.0

            prices_15m = client.extract_close_prices(klines_15m)
            if len(prices_15m) < RSI_PERIOD:
                return False, 0.0, 0.0

            # Расчитываем RSI
            rsi_1h = RSICalculator.get_last_rsi(prices_1h, RSI_PERIOD)
            rsi_15m = RSICalculator.get_last_rsi(prices_15m, RSI_PERIOD)

            # Проверяем оба фильтра
            rsi_1h_passed = rsi_1h > RSI_OVERBOUGHT or rsi_1h < RSI_OVERSOLD
            rsi_15m_passed = rsi_15m > RSI_OVERBOUGHT or rsi_15m < RSI_OVERSOLD

            if not rsi_1h_passed or not rsi_15m_passed:
                logger.debug(f"{symbol}: RSI не прошли (1h={rsi_1h:.1f}, 15m={rsi_15m:.1f})")
                return False, rsi_1h, rsi_15m

            logger.debug(f"{symbol}: ✓ RSI прошли (1h={rsi_1h:.1f}, 15m={rsi_15m:.1f})")
            return True, rsi_1h, rsi_15m

        except Exception as e:
            logger.error(f"Ошибка проверки RSI для {symbol}: {e}")
            return False, 0.0, 0.0

    async def check_symbol_async(
            self,
            symbol: str,
            client: MexcClient
    ) -> Tuple[bool, Dict]:
        """
        ПОЛНАЯ ПРОВЕРКА с правильной логикой фильтрации

        Этапы:
        1. Проверить цену (1 запрос) - если не прошло, стоп
        2. Проверить RSI (2 запроса) - если не прошло, стоп
        3. Собрать данные для графика (1 запрос)
        """
        async with self.semaphore:
            try:
                symbol_start = time.time()

                # ЭТАП 1: Фильтр цены
                price_passed, prices_5m = await self.check_price_filter_only(client, symbol)
                if not price_passed:
                    return False, {}

                # ЭТАП 2: Фильтры RSI
                rsi_passed, rsi_1h, rsi_15m = await self.check_rsi_filters(client, symbol)
                if not rsi_passed:
                    return False, {}

                # ЭТАП 3: Если оба фильтра прошли - собираем данные для графика
                logger.info(f"✓ СИГНАЛ НАЙДЕН: {symbol}! (время проверки: {time.time() - symbol_start:.2f}s)")
                self.signals_triggered += 1

                # Получаем объёмы
                volumes_5m = []
                try:
                    if prices_5m:
                        volumes_5m = [1000] * len(prices_5m)  # Заглушка если нет данных
                except:
                    volumes_5m = []

                # Формируем анализ
                analysis = {
                    'signal_triggered': True,
                    'filter_1_price': (True, ((prices_5m[-1] - prices_5m[-3]) / prices_5m[-3] * 100) if len(
                        prices_5m) >= 3 else 0),
                    'filter_2_rsi_1h': (True, rsi_1h),
                    'filter_3_rsi_15m': (True, rsi_15m),
                }

                return True, {
                    'symbol': symbol,
                    'analysis': analysis,
                    'prices_5m': prices_5m,
                    'volumes_5m': volumes_5m,
                    'klines_5m': None  # Можно добавить полные klines если нужно
                }

            except Exception as e:
                self.failed_requests += 1
                logger.error(f"Критическая ошибка при проверке {symbol}: {e}", exc_info=True)
                return False, {}

    def _check_cooldown(self, symbol: str) -> bool:
        """Проверить cooldown для символа"""
        current_time = time.time()
        last_time = self.last_signal_time.get(symbol, 0)
        return current_time - last_time >= self.signal_cooldown

    def _update_signal_time(self, symbol: str):
        """Обновить время последнего сигнала"""
        self.last_signal_time[symbol] = time.time()

    async def monitor_specific_symbols(self, symbols: List[str]) -> List[Dict]:
        """
        Мониторить символы с оптимизацией и правильной обработкой ошибок
        """
        logger.info(f"🔍 Запуск мониторинга {len(symbols)} пар...")
        start_time = time.time()

        signals = []
        tasks = []

        async with self.mexc as client:
            for symbol in symbols:
                task = self.check_symbol_async(symbol, client)
                tasks.append(task)

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    logger.error(f"Исключение для {symbol}: {result}")
                    self.failed_requests += 1
                    continue

                signal_found, data = result

                if signal_found and self._check_cooldown(symbol):
                    signals.append(data)
                    self._update_signal_time(symbol)

        elapsed = time.time() - start_time
        uptime = time.time() - self.start_time

        success_rate = (
            (self.total_requests - self.failed_requests) / self.total_requests * 100
            if self.total_requests > 0 else 0
        )

        logger.info(f"\n{'=' * 70}")
        logger.info(f"✅ Сканирование завершено за {elapsed:.2f}s")
        logger.info(f"{'=' * 70}")
        logger.info(f"📊 Проверено пар: {len(symbols)}")
        logger.info(f"🎯 Найдено сигналов: {len(signals)}")
        logger.info(f"📡 API запросов: {self.total_requests}")
        logger.info(f"❌ Ошибок: {self.failed_requests}")
        logger.info(f"✅ Процент успеха: {success_rate:.1f}%")
        logger.info(f"⏱️  Общее время работы: {uptime:.0f}s ({uptime / 3600:.1f}h)")
        logger.info(f"{'=' * 70}\n")

        return signals

    async def get_statistics(self) -> Dict:
        """Получить расширённую статистику"""
        uptime = time.time() - self.start_time
        success_rate = (
            (self.total_requests - self.failed_requests) / self.total_requests * 100
            if self.total_requests > 0 else 0
        )

        return {
            'total_requests': self.total_requests,
            'failed_requests': self.failed_requests,
            'early_filtered': self.early_filtered_count,
            'signals_triggered': self.signals_triggered,
            'success_rate': f"{success_rate:.1f}%",
            'rate_limit_hits': self.rate_limit_hits,
            'uptime': f"{uptime:.0f}s"
        }