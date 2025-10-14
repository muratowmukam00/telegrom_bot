import asyncio
from typing import Dict, List, Tuple, Optional
from .api_client import MexcClient
from services.analysis import SignalAnalyzer
from config.settings import CHECK_INTERVAL, PRICE_CHANGE_THRESHOLD
from services.mexc.ws_client import MexcWSClient

import logging
import time

logger = logging.getLogger(__name__)


class RateLimiter:
    """Интеллектуальный ограничитель частоты запросов"""

    def __init__(self, requests_per_second: float = 2.0):
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = 0
        self.lock = asyncio.Lock()
        self.requests_made = 0

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

    Логика:
    1. Проверяем ±8% изменение за 15 мин (1 запрос на 5m свечи)
    2. Если НЕ прошло → СТОП, переходим к следующей паре
    3. Если ДА → продолжаем проверку RSI (остальные 3-4 запроса)

    Экономия: ~75% запросов на парах без сигналов
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

        # Статистика
        self.total_requests = 0
        self.failed_requests = 0
        self.rate_limit_hits = 0
        self.signals_triggered = 0
        self.early_filtered_count = 0  # Пары, отфильтрованные на шаге 1

    async def _make_api_request(
            self,
            coro,
            symbol: str,
            interval: str
    ) -> Optional[List]:
        """Выполнить API запрос с rate limiting"""
        try:
            await self.rate_limiter.wait()
            self.total_requests += 1

            result = await coro
            return result
        except Exception as e:
            self.failed_requests += 1
            logger.debug(f"API ошибка для {symbol} ({interval}): {e}")
            return None

    async def start_websocket_monitor(self, symbols):
        async def handle_message(data):
            symbol = data["s"]
            price = float(data["c"])
            # RSI ýa-da başga filtrleme logikaňy şu ýerde ulanyp bolýar
            logger.info(f"{symbol}: {price}")

        ws_client = MexcWSClient(symbols, on_message=handle_message)
        await ws_client.connect_all()

    async def check_price_filter_only(
            self,
            client: MexcClient,
            symbol: str
    ) -> Tuple[bool, List[float]]:
        """
        Шаг 1: Проверить ТОЛЬКО фильтр цены (±8% за 15 мин)

        Returns:
            (passed, prices_5m) - True если прошел фильтр, иначе False
        """
        try:
            # ТОЛЬКО ОДИН запрос - получаем 5m свечи
            klines_5m = await self._make_api_request(
                self.mexc.get_klines(symbol, "5m", 144),
                symbol,
                "5m"
            )

            if not klines_5m or len(klines_5m) < 15:
                return False, []

            # Извлекаем цены
            prices_5m = self.mexc.extract_close_prices(klines_5m)

            if len(prices_5m) < 15:
                return False, []

            # Проверяем только фильтр цены (используем последние 15 свечей = 75 минут)
            # На самом деле нам нужны последние 3 свечи (15 минут)
            prices_15min = prices_5m[-3:]

            if len(prices_15min) >= 3:
                old_price = prices_15min[0]
                new_price = prices_15min[-1]

                if old_price > 0:
                    price_change = abs((new_price - old_price) / old_price * 100)

                    # ЕСЛИ не прошел фильтр цены - СТОП
                    if price_change < PRICE_CHANGE_THRESHOLD:
                        self.early_filtered_count += 1
                        return False, []

                    logger.debug(f"✓ {symbol}: цена изменилась на {price_change:.2f}% (прошел фильтр 1)")
                    return True, prices_5m

            return False, []

        except Exception as e:
            logger.error(f"Ошибка проверки цены для {symbol}: {e}")
            return False, []

    async def check_rsi_filters(
            self,
            client: MexcClient,
            symbol: str
    ) -> Tuple[bool, float, float]:
        """
        Шаг 2: Проверить RSI фильтры (вызывается ТОЛЬКО если прошел фильтр цены)

        Returns:
            (rsi_passed, rsi_1h, rsi_15m)
        """
        try:
            # Получаем RSI 1h
            prices_1h = await self._make_api_request(
                self.mexc.get_klines(symbol, "1h", 100),
                symbol,
                "1h"
            )
            if not prices_1h or len(prices_1h) < 30:
                return False, 0.0, 0.0

            prices_1h_list = self.mexc.extract_close_prices(prices_1h)

            # Получаем RSI 15m
            prices_15m = await self._make_api_request(
                self.mexc.get_klines(symbol, "15m", 100),
                symbol,
                "15m"
            )
            if not prices_15m or len(prices_15m) < 30:
                return False, 0.0, 0.0

            prices_15m_list = self.mexc.extract_close_prices(prices_15m)

            # Анализируем RSI
            from services.analysis import RSICalculator
            from config.settings import RSI_PERIOD, RSI_OVERBOUGHT, RSI_OVERSOLD

            rsi_1h = RSICalculator.get_last_rsi(prices_1h_list, RSI_PERIOD)
            rsi_15m = RSICalculator.get_last_rsi(prices_15m_list, RSI_PERIOD)

            # Проверяем оба RSI
            rsi_1h_passed = rsi_1h > RSI_OVERBOUGHT or rsi_1h < RSI_OVERSOLD
            rsi_15m_passed = rsi_15m > RSI_OVERBOUGHT or rsi_15m < RSI_OVERSOLD

            rsi_passed = rsi_1h_passed and rsi_15m_passed

            if rsi_passed:
                logger.debug(f"✓ {symbol}: RSI прошли (1h={rsi_1h:.1f}, 15m={rsi_15m:.1f})")
            else:
                logger.debug(f"✗ {symbol}: RSI не прошли (1h={rsi_1h:.1f}, 15m={rsi_15m:.1f})")

            return rsi_passed, rsi_1h, rsi_15m

        except Exception as e:
            logger.error(f"Ошибка проверки RSI для {symbol}: {e}")
            return False, 0.0, 0.0

    async def check_symbol_async(
            self,
            symbol: str,
            client: MexcClient
    ) -> Tuple[bool, Dict]:
        """
        ПОЛНАЯ ПРОВЕРКА с ранней фильтрацией

        Логика:
        1. Шаг 1: Проверить ±8% (1 запрос)
           - Если НЕ прошел → return False (экономия 3-4 запросов!)
        2. Шаг 2: Проверить RSI 1h и 15m (2 запроса)
        3. Шаг 3: Получить полные данные для график (1 запрос на объём)
        """
        async with self.semaphore:
            try:
                logger.debug(f"Проверка {symbol} - Шаг 1 (фильтр цены)...")

                # ШАГ 1: Проверить фильтр цены (1 запрос на 5m)
                price_passed, prices_5m = await self.check_price_filter_only(client, symbol)

                if not price_passed:
                    # Не прошел фильтр цены - СТОП, не делаем остальные запросы
                    logger.debug(f"✗ {symbol}: цена не прошла фильтр, пропускаем")
                    return False, {}

                # ШАГ 2: Проверить RSI фильтры (2 запроса на 1h и 15m)
                logger.debug(f"Проверка {symbol} - Шаг 2 (фильтры RSI)...")
                rsi_passed, rsi_1h, rsi_15m = await self.check_rsi_filters(client, symbol)

                if not rsi_passed:
                    logger.debug(f"✗ {symbol}: RSI не прошли")
                    return False, {}

                # ШАГ 3: Получить последние 15 цен для 1m (для полной проверки)
                logger.debug(f"Проверка {symbol} - Шаг 3 (финальная проверка)...")
                prices_1m = await self._make_api_request(
                    self.mexc.get_klines(symbol, "1m", 200),
                    symbol,
                    "1m"
                )

                if not prices_1m or len(prices_1m) < 15:
                    prices_1m = []
                else:
                    prices_1m = self.mexc.extract_close_prices(prices_1m)

                # ШАГ 4: Получить объёмы для графика
                volumes_5m = []
                try:
                    await self.rate_limiter.wait()
                    self.total_requests += 1
                    klines_5m = await client.get_klines(symbol, "5m", 144)
                    if klines_5m:
                        volumes_5m = client.extract_volumes(klines_5m)
                except:
                    volumes_5m = [0] * len(prices_5m)

                # Финальная проверка всех фильтров
                analysis = SignalAnalyzer.analyze_signal(
                    prices_1m[:15] if prices_1m else [],
                    prices_5m,
                    prices_5m  # Используем 5m вместо 1h для быстрой проверки
                )

                signal_triggered = analysis['signal_triggered']

                if signal_triggered:
                    logger.info(f"✓ СИГНАЛ НАЙДЕН: {symbol}!")
                    self.signals_triggered += 1

                return signal_triggered, {
                    'symbol': symbol,
                    'analysis': analysis,
                    'prices_5m': prices_5m,
                    'volumes_5m': volumes_5m
                }

            except Exception as e:
                self.failed_requests += 1
                logger.error(f"Ошибка при проверке {symbol}: {e}")
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
        Мониторить символы с РАННЕЙ ФИЛЬТРАЦИЕЙ

        Экономия запросов:
        - На каждую пару БЕЗ сигнала: экономия 3-4 запроса
        - На каждую пару С сигналом: +5 запросов вместо +1
        - Если 400 пар, из них только 1-2 с сигналом:
          * Без оптимизации: 400 * 5 = 2000 запросов
          * С оптимизацией: 1 + (399 * 1) + (2 * 4) = ~408 запросов (!)
          * ЭКОНОМИЯ: 80-90%!
        """
        logger.info(f"🔍 Мониторинг {len(symbols)} пар (оптимизированный режим)...")
        start_time = time.time()

        signals = []
        tasks = []

        async with self.mexc as client:
            # Создаём задачи для всех символов
            for symbol in symbols:
                task = self.check_symbol_async(symbol, client)
                tasks.append(task)

            # Выполняем параллельно
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Обрабатываем результаты
            for symbol, result in zip(symbols, results):
                if isinstance(result, Exception):
                    logger.error(f"Исключение для {symbol}: {result}")
                    self.failed_requests += 1
                    continue

                signal_found, data = result

                if signal_found and self._check_cooldown(symbol):
                    signals.append(data)
                    self._update_signal_time(symbol)
                    logger.info(f"✅ Сигнал добавлен: {symbol}")

        elapsed = time.time() - start_time

        success_rate = (
            (self.total_requests - self.failed_requests) / self.total_requests * 100
            if self.total_requests > 0 else 0
        )

        logger.info(f"\n{'=' * 70}")
        logger.info(f"✅ Сканирование завершено за {elapsed:.2f}s")
        logger.info(f"{'=' * 70}")
        logger.info(f"📊 Проверено пар: {len(symbols)}")
        logger.info(f"🚀 Отфильтровано на шаге 1 (цена): {self.early_filtered_count}")
        logger.info(f"🎯 Найдено сигналов: {len(signals)}")
        logger.info(f"📡 API запросов: {self.total_requests}")
        logger.info(f"❌ Ошибок: {self.failed_requests}")
        logger.info(f"✅ Процент успеха: {success_rate:.1f}%")
        logger.info(f"💾 Экономия запросов: ~{(self.early_filtered_count * 3 / self.total_requests * 100):.1f}%")
        logger.info(f"{'=' * 70}\n")

        return signals

    async def get_statistics(self) -> Dict:
        """Получить статистику"""
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
            'rate_limit_hits': self.rate_limit_hits
        }