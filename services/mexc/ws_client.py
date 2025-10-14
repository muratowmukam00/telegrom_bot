import asyncio
import json
import logging
import websockets

logger = logging.getLogger(__name__)

class MexcWSClient:
    def __init__(self, symbols, on_message=None):
        self.symbols = symbols
        self.on_message = on_message
        self.url = "wss://wbs.mexc.com/ws"

    async def connect_all(self):
        """Birden köp WebSocket baglanyşyk açýar, her biri ~200 jübüt alyp."""
        chunk_size = 200
        tasks = []
        for i in range(0, len(self.symbols), chunk_size):
            chunk = self.symbols[i:i + chunk_size]
            tasks.append(asyncio.create_task(self._connect_chunk(chunk, i // chunk_size + 1)))
        await asyncio.gather(*tasks)

    async def _connect_chunk(self, symbols, idx):
        """Her bir WebSocket baglanyşyk üçin aýratyn stream açýar."""
        while True:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=None,  # Özümiz ping ugradarys (manual keepalive)
                    max_size=2 ** 20
                ) as ws:
                    sub = {
                        "method": "SUBSCRIBE",
                        "params": [f"{s.lower()}@ticker" for s in symbols],
                        "id": idx
                    }
                    await ws.send(json.dumps(sub))
                    logger.info(f"🔌 Chunk #{idx} baglanyşyk açyldy: {len(symbols)} jübüt")

                    # Manual keepalive ping task
                    asyncio.create_task(self._keep_alive(ws, idx))

                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if "data" in data and self.on_message:
                                await self.on_message(data["data"])
                        except json.JSONDecodeError:
                            logger.warning(f"⚠️ Chunk #{idx}: JSON parse hatasy")
                        except Exception as parse_error:
                            logger.error(f"❌ Chunk #{idx} işleme hatasy: {parse_error}")

            except Exception as e:
                logger.warning(f"⚠️ Chunk #{idx} ýapyldy: {e}. Täzeden synanşylýar...")
                await asyncio.sleep(5)

    async def _keep_alive(self, ws, idx):
        """Manual ping arkaly baglanyşygy açyk saklaýar."""
        while True:
            try:
                await ws.ping()
                await asyncio.sleep(25)  # her 25 sekuntda ping
            except Exception:
                logger.warning(f"⚠️ Chunk #{idx}: ping ýalňyşlygy — täzeden birikýär")
                break
