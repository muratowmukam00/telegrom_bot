import aiohttp
import asyncio
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


class KlineIndex(Enum):
    """Индексы данных в kline массиве (если это массив, а не dict)"""
    TIMESTAMP = 0
    OPEN = 1
    HIGH = 2
    LOW = 3
    CLOSE = 4
    VOLUME = 5
    AMOUNT = 6
    VOLUME_QUOTE = 7


class APIError(Exception):
    """Базовая ошибка API"""
    pass


class RateLimitError(APIError):
    """Превышен лимит запросов"""
    pass


class MexcClient:
    """
    MEXC API клиент с автоматическими повторами и обработкой ошибок

    Attributes:
        base_url: Базовый URL MEXC API
        session: Aiohttp сессия для запросов
        max_retries: Максимальное количество повторов при ошибке
        timeout: Таймаут запроса в секундах
    """

    def __init__(
            self,
            base_url: str = MEXC_BASE_URL,
            max_retries: int = 3,
            timeout: int = 10
    ):
        self.base_url = base_url
        self.max_retries = max_retries
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Создаём сессию при входе в контекст"""
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Закрываем сессию при выходе из контекста"""
        if self.session:
            await self.session.close()
            self.session = None

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
            retry_count: Текущая попытка (для рекурсии)

        Returns:
            JSON ответ или None при ошибке

        Raises:
            RateLimitError: При превышении лимита запросов
            APIError: При других ошибках API
        """
        if not self.session:
            raise APIError("Session not initialized. Use 'async with' context manager.")

        try:
            async with self.session.get(url, params=params) as response:
                # Проверяем rate limit
                if response.status == 429:
                    logger.warning(f"Rate limit hit for {url}")
                    raise RateLimitError("API rate limit exceeded")

                # Проверяем успешность запроса
                if response.status != 200:
                    logger.error(f"API error {response.status} for {url}")
                    return None

                data = await response.json()

                # Проверяем формат ответа
                if not isinstance(data, dict):
                    logger.error(f"Invalid response format from {url}")
                    return None

                return data

        except aiohttp.ClientError as e:
            logger.error(f"Client error for {url}: {e}")

            # Повторяем запрос при сетевых ошибках
            if retry_count < self.max_retries:
                wait_time = 2 ** retry_count  # Exponential backoff: 1s, 2s, 4s
                logger.info(f"Retrying in {wait_time}s... (attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(wait_time)
                return await self._make_request(url, method, params, retry_count + 1)

            return None

        except asyncio.TimeoutError:
            logger.warning(f"Timeout for {url}")

            if retry_count < self.max_retries:
                logger.info(f"Retrying... (attempt {retry_count + 1}/{self.max_retries})")
                await asyncio.sleep(1)
                return await self._make_request(url, method, params, retry_count + 1)

            return None

        except Exception as e:
            logger.error(f"Unexpected error for {url}: {e}", exc_info=True)
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
            symbol: Торговая пара (например, BTC_USDT)
            interval: Интервал свечей (1m, 5m, 15m, 1h, 4h, 1d)
                     Автоматически конвертируется в формат MEXC (Min1, Min5, etc.)
            limit: Количество свечей для возврата (берём последние N)

        Returns:
            Список свечей в виде словарей
            Каждая свеча: {"time": int, "open": float, "close": float, "high": float,
                          "low": float, "vol": float, "amount": float}
        """
        # Конвертируем интервал в формат MEXC
        mexc_interval = IntervalMapping.convert(interval)

        url = f"{self.base_url}/api/v1/contract/kline/{symbol}"
        params = {
            "interval": mexc_interval,
            "start": "",  # MEXC требует эти параметры, даже пустые
            "end": ""
        }

        try:
            data = await self._make_request(url, params=params)

            if not data:
                logger.warning(f"No response for {symbol} ({interval})")
                return []

            # Проверяем успешность запроса
            if not data.get("success"):
                logger.warning(f"API error for {symbol}: {data.get('message', 'Unknown error')}")
                return []

            raw_data = data.get("data", {})

            # MEXC возвращает данные в формате словаря массивов:
            # {"time": [...], "open": [...], "close": [...], ...}
            if not isinstance(raw_data, dict):
                logger.error(f"Invalid klines format for {symbol}")
                return []

            # Преобразуем в список словарей
            klines = self._transform_klines(raw_data, limit)

            logger.debug(f"Got {len(klines)} klines for {symbol} ({interval} -> {mexc_interval})")
            return klines

        except Exception as e:
            logger.error(f"Error getting klines for {symbol}: {e}")
            return []

    def _transform_klines(self, raw_data: Dict[str, List], limit: int) -> List[Dict[str, Any]]:
        """
        Преобразовать формат MEXC (словарь массивов) в список словарей

        Args:
            raw_data: Сырые данные от MEXC API
            limit: Количество последних свечей для возврата

        Returns:
            Список свечей в удобном формате
        """
        try:
            times = raw_data.get("time", [])
            opens = raw_data.get("open", [])
            closes = raw_data.get("close", [])
            highs = raw_data.get("high", []) or raw_data.get("realHigh", [])
            lows = raw_data.get("low", []) or raw_data.get("realLow", [])
            volumes = raw_data.get("vol", [])
            amounts = raw_data.get("amount", [])

            # Проверяем что все массивы одной длины
            lengths = [len(times), len(opens), len(closes), len(highs), len(lows)]
            if not all(l == lengths[0] for l in lengths):
                logger.error("Klines arrays have different lengths")
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

            # Возвращаем последние N свечей
            return klines[-limit:] if limit < len(klines) else klines

        except Exception as e:
            logger.error(f"Error transforming klines: {e}")
            return []

    def extract_close_prices(self, klines: List[Dict[str, Any]]) -> List[float]:
        """
        Извлечь цены закрытия из klines

        Args:
            klines: Список свечей от API (dict формат)

        Returns:
            Список цен закрытия
        """
        try:
            return [
                float(kline.get("close", 0))
                for kline in klines
                if isinstance(kline, dict) and kline.get("close")
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Error extracting close prices: {e}")
            return []

    def extract_volumes(self, klines: List[Dict[str, Any]]) -> List[float]:
        """
        Извлечь объёмы из klines

        Args:
            klines: Список свечей от API (dict формат)

        Returns:
            Список объёмов
        """
        try:
            return [
                float(kline.get("vol", 0))
                for kline in klines
                if isinstance(kline, dict) and kline.get("vol")
            ]
        except (ValueError, TypeError) as e:
            logger.error(f"Error extracting volumes: {e}")
            return []

    async def get_all_symbols(self) -> List[str]:
        """
        Получить список всех USDT фьючерсных пар

        Returns:
            Список символов (например, ['BTC_USDT', 'ETH_USDT', ...])
        """
        url = f"{self.base_url}/api/v1/contract/detail"

        try:
            data = await self._make_request(url)

            if not data or "data" not in data:
                logger.error("No symbols data from API")
                return []

            contracts = data["data"]

            if not isinstance(contracts, list):
                logger.error("Invalid contracts format")
                return []

            # Фильтруем только USDT пары
            symbols = [
                contract["symbol"]
                for contract in contracts
                if isinstance(contract, dict) and "USDT" in contract.get("symbol", "")
            ]

            logger.info(f"Found {len(symbols)} USDT pairs")
            return symbols

        except Exception as e:
            logger.error(f"Error getting symbols: {e}")
            return []

    async def get_24h_price_change(self, symbol: str) -> Optional[float]:
        """
        Получить изменение цены за 24 часа в процентах

        Args:
            symbol: Торговая пара

        Returns:
            Процент изменения цены или None при ошибке
        """
        url = f"{self.base_url}/api/v1/contract/ticker"
        params = {"symbol": symbol}

        try:
            data = await self._make_request(url, params=params)

            if not data:
                return None

            # Проверяем успешность
            if not data.get("success"):
                logger.warning(f"Ticker API error: {data.get('message')}")
                return None

            ticker_data = data.get("data")

            if not ticker_data:
                return None

            # Если это список, берем первый элемент
            if isinstance(ticker_data, list):
                if len(ticker_data) == 0:
                    return None
                ticker_data = ticker_data[0]

            # MEXC использует поле "riseFallRate" для 24h изменения
            price_change = ticker_data.get("riseFallRate")

            if price_change is None:
                return None

            return float(price_change)

        except (ValueError, TypeError) as e:
            logger.error(f"Error parsing price change for {symbol}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting price change for {symbol}: {e}")
            return None


# Пример использования
async def example_usage():
    """Пример использования улучшенного клиента"""
    async with MexcClient() as client:
        # Получаем все символы
        symbols = await client.get_all_symbols()
        print(f"Found {len(symbols)} symbols")

        # Получаем klines для BTC
        klines = await client.get_klines("BTC_USDT", "1m", 100)

        # Извлекаем цены и объёмы
        prices = client.extract_close_prices(klines)
        volumes = client.extract_volumes(klines)

        print(f"Got {len(prices)} prices, last: {prices[-1] if prices else 'N/A'}")
        print(f"Got {len(volumes)} volumes")

        # Получаем изменение за 24ч
        change = await client.get_24h_price_change("BTC_USDT")
        print(f"24h change: {change}%")


if __name__ == "__main__":
    asyncio.run(example_usage())