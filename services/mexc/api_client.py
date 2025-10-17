"""
MEXC REST API Client - Production Version
Оптимизированный клиент с автоматическими повторами и rate limiting
"""

import aiohttp
import asyncio
import time
from typing import List, Dict, Optional, Any
from enum import Enum
import logging

from config.settings import MEXC_BASE_URL

logger = logging.getLogger(__name__)


class IntervalMapping:
    """Маппинг стандартных интервалов в формат MEXC"""

    STANDARD_TO_MEXC = {
        "1m": "Min1",
        "5m": "Min5",
        "15m": "Min15",
        "30m": "Min30",
        "1h": "Min60",
        "4h": "Hour4",
        "1d": "Day1",
        "1w": "Week1",
        "1M": "Month1",
    }

    @classmethod
    def convert(cls, interval: str) -> str:
        """Конвертировать стандартный интервал в формат MEXC"""
        return cls.STANDARD_TO_MEXC.get(interval, interval)


class APIError(Exception):
    """Базовая ошибка API"""
    pass


class RateLimitError(APIError):
    """Превышен лимит запросов"""
    pass


class RequestMetrics:
    """Метрики API запросов"""

    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.retries = 0
        self.rate_limit_hits = 0
        self.total_response_time = 0.0

    def request_made(self):
        self.total_requests += 1

    def request_succeeded(self, response_time: float):
        self.successful_requests += 1
        self.total_response_time += response_time

    def request_failed(self):
        self.failed_requests += 1

    def retry_attempted(self):
        self.retries += 1

    def rate_limit_hit(self):
        self.rate_limit_hits += 1

    def get_stats(self) -> Dict:
        avg_response_time = (
            self.total_response_time / self.successful_requests
            if self.successful_requests > 0
            else 0
        )

        success_rate = (
            self.successful_requests / self.total_requests * 100
            if self.total_requests > 0
            else 0
        )

        return {
            'total_requests': self.total_requests,
            'successful': self.successful_requests,
            'failed': self.failed_requests,
            'retries': self.retries,
            'rate_limit_hits': self.rate_limit_hits,
            'success_rate': f"{success_rate:.1f}%",
            'avg_response_time': f"{avg_response_time:.3f}s"
        }


class MexcClient:
    """
    Production MEXC API клиент

    Features:
    - Автоматические повторы с exponential backoff
    - Rate limiting
    - Connection pooling
    - Request metrics
    - Timeout handling
    """

    def __init__(
            self,
            base_url: str = MEXC_BASE_URL,
            max_retries: int = 3,
            timeout: int = 30,
            max_connections: int = 100
    ):
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_connections = max_connections
        self.session: Optional[aiohttp.ClientSession] = None
        self.metrics = RequestMetrics()

        logger.debug(
            f"Инициализация MEXC клиента: "
            f"timeout={timeout}s, max_retries={max_retries}"
        )

    async def __aenter__(self):
        """Создаём сессию при входе в контекст"""
        connector = aiohttp.TCPConnector(
            limit=self.max_connections,
            ttl_dns_cache=300,
            enable_cleanup_closed=True
        )

        self.session = aiohttp.ClientSession(
            timeout=self.timeout,
            connector=connector,
            headers={
                'User-Agent': 'MEXC-Signal-Bot/2.0',
                'Accept': 'application/json'
            }
        )

        logger.debug("API сессия создана")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрываем сессию при выходе из контекста"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.debug("API сессия закрыта")

    async def _make_request(
            self,
            url: str,
            method: str = "GET",
            params: Optional[Dict[str, Any]] = None,
            retry_count: int = 0
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить HTTP запрос с автоматическими повторами

        Args:
            url: URL для запроса
            method: HTTP метод
            params: Query параметры
            retry_count: Текущая попытка

        Returns:
            JSON ответ или None при ошибке
        """
        if not self.session:
            raise APIError("Session not initialized. Use 'async with' context manager.")

        self.metrics.request_made()
        start_time = time.time()

        try:
            async with self.session.get(url, params=params) as response:
                response_time = time.time() - start_time

                # Rate limit
                if response.status == 429:
                    self.metrics.rate_limit_hit()
                    logger.warning(f"Rate limit hit: {url}")

                    # Повторяем с большей задержкой
                    if retry_count < self.max_retries:
                        wait_time = 2 ** (retry_count + 2)  # 4s, 8s, 16s
                        logger.info(f"Ожидание {wait_time}s перед повтором...")
                        await asyncio.sleep(wait_time)
                        self.metrics.retry_attempted()
                        return await self._make_request(url, method, params, retry_count + 1)

                    raise RateLimitError("API rate limit exceeded")

                # Ошибка сервера
                if response.status != 200:
                    self.metrics.request_failed()
                    logger.warning(
                        f"HTTP {response.status} для {url}: "
                        f"{await response.text()}"
                    )
                    return None

                # Парсим ответ
                data = await response.json()

                if not isinstance(data, dict):
                    self.metrics.request_failed()
                    logger.warning(f"Невалидный формат ответа: {type(data)}")
                    return None

                self.metrics.request_succeeded(response_time)
                return data

        except aiohttp.ClientError as e:
            self.metrics.request_failed()
            logger.warning(f"Client error для {url}: {e}")

            # Повторяем при сетевых ошибках
            if retry_count < self.max_retries:
                wait_time = 2 ** retry_count  # 1s, 2s, 4s
                logger.info(
                    f"Повтор через {wait_time}s... "
                    f"(попытка {retry_count + 1}/{self.max_retries})"
                )
                await asyncio.sleep(wait_time)
                self.metrics.retry_attempted()
                return await self._make_request(url, method, params, retry_count + 1)

            return None

        except asyncio.TimeoutError:
            self.metrics.request_failed()
            logger.warning(f"Timeout для {url}")

            if retry_count < self.max_retries:
                logger.info(
                    f"Повтор... (попытка {retry_count + 1}/{self.max_retries})"
                )
                await asyncio.sleep(1)
                self.metrics.retry_attempted()
                return await self._make_request(url, method, params, retry_count + 1)

            return None

        except Exception as e:
            self.metrics.request_failed()
            logger.error(f"Неожиданная ошибка для {url}: {e}", exc_info=True)
            return None

    async def get_klines(
            self,
            symbol: str,
            interval: str = "1m",
            limit: int = 200
    ) -> List[Dict[str, Any]]:
        """
        Получить свечи (klines) для символа

        Args:
            symbol: Торговая пара (BTC_USDT)
            interval: Интервал (1m, 5m, 15m, 1h, 4h, 1d)
            limit: Количество последних свечей

        Returns:
            Список свечей в формате dict
        """
        mexc_interval = IntervalMapping.convert(interval)
        url = f"{self.base_url}/api/v1/contract/kline/{symbol}"
        params = {
            "interval": mexc_interval,
            "start": "",
            "end": ""
        }

        try:
            data = await self._make_request(url, params=params)

            if not data:
                return []

            if not data.get("success"):
                logger.debug(
                    f"API error для {symbol}: {data.get('message', 'Unknown')}"
                )
                return []

            raw_data = data.get("data", {})

            if not isinstance(raw_data, dict):
                return []

            klines = self._transform_klines(raw_data, limit)

            if klines:
                logger.debug(
                    f"Получено {len(klines)} свечей для {symbol} ({interval})"
                )

            return klines

        except Exception as e:
            logger.error(f"Ошибка get_klines для {symbol}: {e}")
            return []

    def _transform_klines(
            self,
            raw_data: Dict[str, List],
            limit: int
    ) -> List[Dict[str, Any]]:
        """
        Преобразовать формат MEXC в список словарей

        MEXC формат: {"time": [...], "open": [...], "close": [...], ...}
        Наш формат: [{"time": x, "open": y, "close": z, ...}, ...]
        """
        try:
            times = raw_data.get("time", [])
            opens = raw_data.get("open", [])
            closes = raw_data.get("close", [])
            highs = raw_data.get("high", []) or raw_data.get("realHigh", [])
            lows = raw_data.get("low", []) or raw_data.get("realLow", [])
            volumes = raw_data.get("vol", [])
            amounts = raw_data.get("amount", [])

            # Проверка длины
            lengths = [len(times), len(opens), len(closes), len(highs), len(lows)]
            if not all(l == lengths[0] for l in lengths):
                logger.warning("Массивы klines разной длины")
                return []

            # Собираем свечи
            klines = []
            for i in range(len(times)):
                kline = {
                    "time": times[i],
                    "open": opens[i],
                    "close": closes[i],
                    "high": highs[i],
                    "low": lows[i],
                    "vol": volumes[i] if i < len(volumes) else 0,
                    "amount": amounts[i] if i < len(amounts) else 0,
                }
                klines.append(kline)

            # Возвращаем последние N
            return klines[-limit:] if limit < len(klines) else klines

        except Exception as e:
            logger.error(f"Ошибка transform_klines: {e}")
            return []

    def extract_close_prices(self, klines: List[Dict[str, Any]]) -> List[float]:
        """Извлечь цены закрытия"""
        try:
            return [
                float(kline.get("close", 0))
                for kline in klines
                if isinstance(kline, dict) and kline.get("close")
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Ошибка extract_close_prices: {e}")
            return []

    def extract_volumes(self, klines: List[Dict[str, Any]]) -> List[float]:
        """Извлечь объёмы"""
        try:
            return [
                float(kline.get("vol", 0))
                for kline in klines
                if isinstance(kline, dict) and kline.get("vol")
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Ошибка extract_volumes: {e}")
            return []

    async def get_all_symbols(self) -> List[str]:
        """
        Получить список всех USDT фьючерсных пар

        Returns:
            Список символов формата SYMBOL_USDT
        """
        url = f"{self.base_url}/api/v1/contract/detail"

        try:
            data = await self._make_request(url)

            if not data or not data.get("success"):
                logger.error("Не удалось получить список пар")
                return []

            contracts = data.get("data", [])

            if not isinstance(contracts, list):
                logger.error(f"Невалидный формат contracts: {type(contracts)}")
                return []

            # Фильтруем USDT пары
            symbols = sorted([
                c["symbol"]
                for c in contracts
                if isinstance(c, dict) and c.get("symbol", "").endswith("_USDT")
            ])

            logger.info(f"Получено {len(symbols)} USDT фьючерсных пар")
            return symbols

        except Exception as e:
            logger.error(f"Ошибка get_all_symbols: {e}", exc_info=True)
            return []

    async def get_24h_price_change(self, symbol: str) -> Optional[float]:
        """
        Получить изменение цены за 24 часа

        Args:
            symbol: Торговая пара

        Returns:
            Процент изменения или None
        """
        url = f"{self.base_url}/api/v1/contract/ticker"
        params = {"symbol": symbol}

        try:
            data = await self._make_request(url, params=params)

            if not data or not data.get("success"):
                return None

            ticker_data = data.get("data")

            if not ticker_data:
                return None

            # Если список, берём первый элемент
            if isinstance(ticker_data, list):
                if len(ticker_data) == 0:
                    return None
                ticker_data = ticker_data[0]

            # MEXC использует "riseFallRate"
            price_change = ticker_data.get("riseFallRate")

            if price_change is None:
                return None

            return float(price_change)

        except (ValueError, TypeError) as e:
            logger.debug(f"Ошибка парсинга 24h change для {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Ошибка get_24h_price_change для {symbol}: {e}")
            return None

    def get_metrics(self) -> Dict:
        """Получить метрики API запросов"""
        return self.metrics.get_stats()


# === Пример использования ===
async def example():
    """Пример использования production клиента"""

    async with MexcClient(timeout=30) as client:
        # Получаем символы
        symbols = await client.get_all_symbols()
        logger.info(f"Найдено {len(symbols)} символов")

        # Получаем klines для BTC
        klines = await client.get_klines("BTC_USDT", "1m", 100)

        if klines:
            prices = client.extract_close_prices(klines)
            logger.info(
                f"BTC_USDT: {len(prices)} свечей, "
                f"цена: {prices[-1] if prices else 'N/A'}"
            )

        # Получаем 24h изменение
        change = await client.get_24h_price_change("BTC_USDT")
        logger.info(f"24h изменение: {change}%")

        # Метрики
        logger.info(f"Метрики API: {client.get_metrics()}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())