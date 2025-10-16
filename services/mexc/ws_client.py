import asyncio
import json
import logging
import re
import websockets
from typing import List, Callable, Optional

logger = logging.getLogger(__name__)

class MexcWSClient:
    """WebSocket клиент для MEXC Futures (USDT контракты)"""

    def __init__(self, symbols: List[str], on_message: Optional[Callable] = None):
        self.symbols = symbols
        self.on_message = on_message
        self.ws_url = "wss://contract.mexc.com/edge"  # Правильный Futures WS endpoint
        self.chunk_size = 200
        self.reconnect_delay = 5

    async def connect_all(self):
        """Запускает несколько WebSocket соединений (по 200 пар максимум)"""
        tasks = []
        for i in range(0, len(self.symbols), self.chunk_size):
            chunk = self.symbols[i:i + self.chunk_size]
            idx = i // self.chunk_size + 1
            task = asyncio.create_task(self._connect_chunk(chunk, idx))
            tasks.append(task)

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _connect_chunk(self, symbols: List[str], idx: int):
        """Открывает одно WS-подключение и подписывается на все пары из чанка"""

        # Фильтрация символов
        clean_symbols = []
        for s in symbols:
            s = str(s).strip()
            s = re.sub(r"^https?://[^/]+/(?:futures(?:/perpetual)?/)?", "", s, flags=re.IGNORECASE)
            s = s.upper()
            if re.fullmatch(r"[A-Z0-9_]+_USDT", s):
                clean_symbols.append(s)
                logger.debug(f"🔎 Очищенный символ: {s}")

        if not clean_symbols:
            logger.error(f"❌ Chunk #{idx}: нет валидных символов!")
            return

        logger.info(f"🔍 Chunk #{idx} будет подписываться на: {clean_symbols[:3]}... ({len(clean_symbols)} всего)")

        while True:
            try:
                logger.info(f"🔌 Chunk #{idx}: подключаюсь к {self.ws_url}...")
                async with websockets.connect(
                    self.ws_url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=10,
                    max_size=2 ** 20
                ) as ws:
                    logger.info(f"✅ Chunk #{idx}: WebSocket подключен!")

                    # Подписка на тикеры
                    for symbol in clean_symbols:
                        sub_msg = {
                            "method": "sub.ticker",
                            "param": {
                                "symbol": symbol
                            }
                        }
                        logger.debug(f"🧩 SUBSCRIBE DEBUG: {sub_msg}")
                        await ws.send(json.dumps(sub_msg))
                        await asyncio.sleep(0.01)

                    logger.info(f"📌 Chunk #{idx}: подписался на {len(clean_symbols)} пар")

                    # Запускаем поддержание соединения
                    ping_task = asyncio.create_task(self._keep_alive(ws, idx))

                    try:
                        async for msg in ws:
                            logger.debug(f"📥 Сырое сообщение от сервера: {msg}")
                            try:
                                data = json.loads(msg)
                                if isinstance(data, dict):
                                    if data.get("channel") == "rs.error":
                                        logger.error(f"❌ Ошибка подписки: {data}")
                                        continue
                                    if "msg" in data and "success" in str(data.get("msg", "")).lower():
                                        logger.info(f"📨 Подтверждение подписки: {data}")
                                        continue
                                    await self._process_ticker_data(data)
                            except json.JSONDecodeError:
                                logger.warning(f"⚠️ Chunk #{idx}: не могу распарсить JSON: {msg}")
                            except Exception as e:
                                logger.error(f"❌ Chunk #{idx}: ошибка обработки сообщения: {e}")
                    finally:
                        ping_task.cancel()
                        try:
                            await ping_task
                        except asyncio.CancelledError:
                            pass

            except websockets.exceptions.WebSocketException as e:
                logger.warning(f"⚠️ Chunk #{idx}: WebSocket ошибка: {e}")
                logger.info(f"🔄 Chunk #{idx}: переподключение через {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)
            except Exception as e:
                logger.error(f"❌ Chunk #{idx}: критическая ошибка: {e}")
                logger.info(f"🔄 Chunk #{idx}: переподключение через {self.reconnect_delay}s...")
                await asyncio.sleep(self.reconnect_delay)

    async def _keep_alive(self, ws, idx: int):
        """Периодически отправляет ping для поддержания соединения"""
        try:
            while True:
                await asyncio.sleep(15)
                ping_msg = {"method": "ping"}
                await ws.send(json.dumps(ping_msg))
                logger.debug(f"📡 Chunk #{idx}: Sent JSON ping")
                try:
                    pong = await ws.ping()
                    await asyncio.wait_for(pong, timeout=10)
                except asyncio.TimeoutError:
                    logger.warning(f"⚠️ Chunk #{idx}: ping timeout - переподключаюсь")
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.warning(f"⚠️ Chunk #{idx}: ping error: {e}")

    async def _process_ticker_data(self, data: dict):
        """Обрабатывает данные тикера от MEXC"""
        logger.debug(f"📥 Получено тикер-сообщение: {data}")
        try:
            # Формат 1: {"channel": "push.ticker", "symbol": "BTC_USDT", "data": {...}}
            if "channel" in data and "push.ticker" in data["channel"]:
                symbol = data.get("symbol")
                ticker_data = data.get("data", {})
                if symbol and ticker_data:
                    price = float(ticker_data.get("lastPrice", 0))
                    if price > 0 and self.on_message:
                        # logger.info(f"📊 Тикер: {symbol}, цена: {price}")
                        await self.on_message({"s": symbol, "c": price})
                return

            # Формат 2: {"symbol": "BTC_USDT", "lastPrice": "43210.5", ...}
            if "symbol" in data and "lastPrice" in data:
                symbol = data.get("symbol")
                price = float(data.get("lastPrice", 0))
                if symbol and price > 0 and self.on_message:
                    # logger.info(f"📊 Тикер: {symbol}, цена: {price}")
                    await self.on_message({"s": symbol, "c": price})
                return

            # Формат 3: {"data": {"symbol": "BTC_USDT", "lastPrice": "..."}}
            if "data" in data and isinstance(data["data"], dict):
                ticker_data = data["data"]
                symbol = ticker_data.get("symbol")
                price = float(ticker_data.get("lastPrice", 0))
                if symbol and price > 0 and self.on_message:
                    # logger.info(f"📊 Тикер: {symbol}, цена: {price}")
                    await self.on_message({"s": symbol, "c": price})
                return

            # Дополнительный формат: {"symbol": "BTC_USDT", "price": "..."}
            if "symbol" in data and "price" in data:
                symbol = data.get("symbol")
                price = float(data.get("price", 0))
                if symbol and price > 0 and self.on_message:
                    logger.info(f"📊 Тикер: {symbol}, цена: {price}")
                    await self.on_message({"s": symbol, "c": price})
                return

            # logger.warning(f"⚠️ Неизвестный формат сообщения: {data}")
        except (ValueError, TypeError, KeyError) as e:
            logger.debug(f"Не удалось извлечь данные тикера: {e}")
        except Exception as e:
            logger.error(f"Ошибка обработки тикера: {e}")