"""
MEXC WebSocket Client - Production Version
Подключение к MEXC Futures WebSocket API
"""

import asyncio
import json
import logging
import re
import time
from typing import List, Callable, Optional, Dict

import websockets
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
    WebSocketException
)

logger = logging.getLogger(__name__)


class ConnectionMetrics:
    """Метрики WebSocket подключений"""

    def __init__(self):
        self.total_connections = 0
        self.active_connections = 0
        self.reconnections = 0
        self.messages_received = 0
        self.errors = 0
        self.last_message_time = 0

    def connection_opened(self):
        self.total_connections += 1
        self.active_connections += 1

    def connection_closed(self):
        self.active_connections = max(0, self.active_connections - 1)

    def reconnection_attempted(self):
        self.reconnections += 1

    def message_received(self):
        self.messages_received += 1
        self.last_message_time = time.time()

    def error_occurred(self):
        self.errors += 1

    def get_stats(self) -> Dict:
        return {
            'total_connections': self.total_connections,
            'active_connections': self.active_connections,
            'reconnections': self.reconnections,
            'messages_received': self.messages_received,
            'errors': self.errors,
            'last_message_age': time.time() - self.last_message_time if self.last_message_time > 0 else None
        }


class MexcWSClient:
    """
    Production WebSocket клиент для MEXC Futures

    Features:
    - Автоматическое переподключение
    - Chunked subscriptions (макс 200 пар на подключение)
    - Health checks (ping/pong)
    - Метрики подключений
    - Graceful shutdown
    """

    WS_URL = "wss://contract.mexc.com/edge"
    CHUNK_SIZE = 200
    PING_INTERVAL = 20  # секунд
    PING_TIMEOUT = 10  # секунд
    RECONNECT_DELAY = 5  # секунд
    MAX_RECONNECT_DELAY = 60  # макс задержка

    def __init__(
            self,
            symbols: List[str],
            on_message: Optional[Callable] = None
    ):
        self.symbols = self._clean_symbols(symbols)
        self.on_message = on_message
        self.metrics = ConnectionMetrics()
        self.is_running = False

        logger.info(f"Инициализация WS клиента для {len(self.symbols)} пар")

    def _clean_symbols(self, symbols: List[str]) -> List[str]:
        """
        Очистка и валидация символов

        Правила:
        - Только SYMBOL_USDT формат
        - Убираем URL префиксы
        - Uppercase
        """
        clean_symbols = []

        for s in symbols:
            s = str(s).strip()

            # Убираем URL если есть
            s = re.sub(
                r"^https?://[^/]+/(?:futures(?:/perpetual)?/)?",
                "",
                s,
                flags=re.IGNORECASE
            )

            s = s.upper()

            # Валидация формата
            if re.fullmatch(r"[A-Z0-9_]+_USDT", s):
                clean_symbols.append(s)
            else:
                logger.warning(f"Невалидный символ пропущен: {s}")

        logger.info(f"Очищено символов: {len(clean_symbols)}/{len(symbols)}")
        return clean_symbols

    async def connect_all(self):
        """Запуск всех WebSocket подключений"""
        if not self.symbols:
            logger.error("Нет символов для подключения!")
            return

        self.is_running = True

        # Разбиваем на чанки
        chunks = [
            self.symbols[i:i + self.CHUNK_SIZE]
            for i in range(0, len(self.symbols), self.CHUNK_SIZE)
        ]

        logger.info(
            f"Запуск {len(chunks)} WebSocket подключений "
            f"(по {self.CHUNK_SIZE} пар)"
        )

        # Запускаем все чанки параллельно
        tasks = [
            asyncio.create_task(self._connect_chunk(chunk, idx + 1))
            for idx, chunk in enumerate(chunks)
        ]

        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Ошибка в connect_all: {e}", exc_info=True)
        finally:
            self.is_running = False

    async def _connect_chunk(self, symbols: List[str], chunk_id: int):
        """
        Подключение к одному чанку символов с автореконнектом
        """
        reconnect_delay = self.RECONNECT_DELAY

        while self.is_running:
            try:
                logger.info(f"[Chunk #{chunk_id}] Подключение к {self.WS_URL}...")

                async with websockets.connect(
                        self.WS_URL,
                        ping_interval=self.PING_INTERVAL,
                        ping_timeout=self.PING_TIMEOUT,
                        close_timeout=10,
                        max_size=2 ** 20,  # 1MB
                        compression=None  # Отключаем compression для скорости
                ) as ws:
                    self.metrics.connection_opened()
                    logger.info(f"[Chunk #{chunk_id}] ✅ Подключено ({len(symbols)} пар)")

                    # Сбрасываем задержку после успешного подключения
                    reconnect_delay = self.RECONNECT_DELAY

                    # Подписываемся на все символы
                    await self._subscribe_symbols(ws, symbols, chunk_id)

                    # Запускаем keep-alive
                    keep_alive_task = asyncio.create_task(
                        self._keep_alive(ws, chunk_id)
                    )

                    try:
                        # Обрабатываем сообщения
                        await self._process_messages(ws, chunk_id)
                    finally:
                        keep_alive_task.cancel()
                        try:
                            await keep_alive_task
                        except asyncio.CancelledError:
                            pass

                        self.metrics.connection_closed()

            except (ConnectionClosed, ConnectionClosedError, ConnectionClosedOK) as e:
                logger.warning(
                    f"[Chunk #{chunk_id}] Соединение закрыто: {e.__class__.__name__}"
                )
                self.metrics.error_occurred()

            except WebSocketException as e:
                logger.warning(
                    f"[Chunk #{chunk_id}] WebSocket ошибка: {e}"
                )
                self.metrics.error_occurred()

            except Exception as e:
                logger.error(
                    f"[Chunk #{chunk_id}] Неожиданная ошибка: {e}",
                    exc_info=True
                )
                self.metrics.error_occurred()

            # Переподключение (если бот ещё работает)
            if self.is_running:
                self.metrics.reconnection_attempted()
                logger.info(
                    f"[Chunk #{chunk_id}] Переподключение через {reconnect_delay}s..."
                )
                await asyncio.sleep(reconnect_delay)

                # Exponential backoff
                reconnect_delay = min(
                    reconnect_delay * 1.5,
                    self.MAX_RECONNECT_DELAY
                )
            else:
                logger.info(f"[Chunk #{chunk_id}] Остановка (флаг is_running=False)")
                break

        logger.info(f"[Chunk #{chunk_id}] Завершено")

    async def _subscribe_symbols(
            self,
            ws,
            symbols: List[str],
            chunk_id: int
    ):
        """Подписка на тикеры символов"""
        logger.info(f"[Chunk #{chunk_id}] Подписка на {len(symbols)} пар...")

        for symbol in symbols:
            sub_msg = {
                "method": "sub.ticker",
                "param": {
                    "symbol": symbol
                }
            }

            try:
                await ws.send(json.dumps(sub_msg))
                await asyncio.sleep(0.01)  # Небольшая задержка между подписками
            except Exception as e:
                logger.error(
                    f"[Chunk #{chunk_id}] Ошибка подписки на {symbol}: {e}"
                )

        logger.info(f"[Chunk #{chunk_id}] ✅ Подписка завершена")

    async def _keep_alive(self, ws, chunk_id: int):
        """Поддержание соединения (ping)"""
        try:
            while True:
                await asyncio.sleep(self.PING_INTERVAL)

                # JSON ping для MEXC
                ping_msg = {"method": "ping"}
                await ws.send(json.dumps(ping_msg))

                # Также используем встроенный WS ping
                try:
                    pong = await ws.ping()
                    await asyncio.wait_for(pong, timeout=self.PING_TIMEOUT)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[Chunk #{chunk_id}] Ping timeout — закрываю соединение"
                    )
                    await ws.close()
                    break

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(
                f"[Chunk #{chunk_id}] Ошибка keep-alive: {e}"
            )

    async def _process_messages(self, ws, chunk_id: int):
        """Обработка входящих сообщений"""
        async for msg in ws:
            try:
                data = json.loads(msg)

                # Фильтруем служебные сообщения
                if not isinstance(data, dict):
                    continue

                # Ошибки подписки
                if data.get("channel") == "rs.error":
                    logger.error(
                        f"[Chunk #{chunk_id}] Ошибка от сервера: {data}"
                    )
                    continue

                # Успешная подписка (игнорируем)
                if "msg" in data and "success" in str(data.get("msg", "")).lower():
                    continue

                # Обрабатываем тикер
                await self._process_ticker_data(data, chunk_id)
                self.metrics.message_received()

            except json.JSONDecodeError:
                logger.debug(
                    f"[Chunk #{chunk_id}] Не удалось распарсить JSON: {msg[:100]}"
                )
            except Exception as e:
                logger.error(
                    f"[Chunk #{chunk_id}] Ошибка обработки сообщения: {e}",
                    exc_info=True
                )
                self.metrics.error_occurred()

    async def _process_ticker_data(self, data: dict, chunk_id: int):
        """
        Обработка данных тикера

        Поддерживаемые форматы:
        1. {"channel": "push.ticker", "symbol": "BTC_USDT", "data": {...}}
        2. {"symbol": "BTC_USDT", "lastPrice": "43210.5"}
        3. {"data": {"symbol": "BTC_USDT", "lastPrice": "..."}}
        """
        try:
            symbol = None
            price = None

            # Формат 1: push.ticker
            if "channel" in data and "push.ticker" in data["channel"]:
                symbol = data.get("symbol")
                ticker_data = data.get("data", {})
                price = ticker_data.get("lastPrice")

            # Формат 2: прямой
            elif "symbol" in data:
                symbol = data.get("symbol")
                price = data.get("lastPrice") or data.get("price")

            # Формат 3: вложенный
            elif "data" in data and isinstance(data["data"], dict):
                ticker_data = data["data"]
                symbol = ticker_data.get("symbol")
                price = ticker_data.get("lastPrice") or ticker_data.get("price")

            # Валидация
            if symbol and price:
                price = float(price)
                if price > 0 and self.on_message:
                    await self.on_message({"s": symbol, "c": price})

        except (ValueError, TypeError, KeyError) as e:
            logger.debug(
                f"[Chunk #{chunk_id}] Не удалось извлечь тикер: {e}"
            )
        except Exception as e:
            logger.error(
                f"[Chunk #{chunk_id}] Ошибка обработки тикера: {e}",
                exc_info=True
            )

    async def stop(self):
        """Остановка всех подключений"""
        logger.info("Остановка WebSocket клиента...")
        self.is_running = False

    def get_metrics(self) -> Dict:
        """Получить метрики подключений"""
        return self.metrics.get_stats()


# === Пример использования ===
async def example():
    """Пример использования production клиента"""

    async def on_price_update(data):
        symbol = data.get("s")
        price = data.get("c")
        print(f"{symbol}: {price}")

    # Создаём клиент
    symbols = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    client = MexcWSClient(symbols, on_message=on_price_update)

    try:
        # Запускаем
        await asyncio.wait_for(client.connect_all(), timeout=60)
    except asyncio.TimeoutError:
        print("Timeout")
    finally:
        await client.stop()
        print("Метрики:", client.get_metrics())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example())