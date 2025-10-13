import aiohttp
import asyncio
from typing import List, Dict, Optional
from config.settings import MEXC_BASE_URL

class MexcClient:
    def __init__(self):
        self.base_url = MEXC_BASE_URL
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def get_klines(self, symbol: str, interval: str = "1m", limit: int = 200) -> List[Dict]:
        """
        Получить свечи (klines) для символа
        interval: 1m, 5m, 15m, 1h, etc.
        """
        try:
            url = f"{self.base_url}/api/v1/contract/kline/{symbol}?interval={interval}&limit={limit}"
            
            if not self.session:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data.get("data", [])
                        else:
                            print(f"Error: {resp.status}")
                            return []
            else:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("data", [])
                    else:
                        print(f"Error: {resp.status}")
                        return []
        except Exception as e:
            print(f"Exception in get_klines: {e}")
            return []
    
    async def get_all_symbols(self) -> List[str]:
        """Получить список всех USDT фьючерс пар"""
        try:
            url = f"{self.base_url}/api/v1/contract/detail"
            
            if not self.session:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            symbols = [item["symbol"] for item in data.get("data", []) if "USDT" in item["symbol"]]
                            return symbols
                        else:
                            return []
            else:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        symbols = [item["symbol"] for item in data.get("data", []) if "USDT" in item["symbol"]]
                        return symbols
                    else:
                        return []
        except Exception as e:
            print(f"Exception in get_all_symbols: {e}")
            return []
    
    async def get_24h_price_change(self, symbol: str) -> Optional[float]:
        """Получить изменение цены за 24 часа в %"""
        try:
            url = f"{self.base_url}/api/v1/contract/ticker?symbol={symbol}"
            
            if not self.session:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            if data.get("data"):
                                return float(data["data"][0].get("priceChangePercent", 0))
                            return None
            else:
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("data"):
                            return float(data["data"][0].get("priceChangePercent", 0))
                        return None
        except Exception as e:
            print(f"Exception in get_24h_price_change: {e}")
            return None
