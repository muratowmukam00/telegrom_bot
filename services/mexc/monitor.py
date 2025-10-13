import asyncio
from typing import Dict, List, Tuple
from .api_client import MexcClient
from services.analysis import SignalAnalyzer
from config.settings import CHECK_INTERVAL
import logging

logger = logging.getLogger(__name__)

class PairMonitor:
    """Мониторинг фьючерс пар MEXC"""
    
    def __init__(self):
        self.mexc = MexcClient()
        self.last_signal_time: Dict[str, float] = {}
        self.signal_cooldown = 300  # 5 минут между сигналами для одной пары
    
    async def get_klines_for_symbol(
        self,
        symbol: str,
        interval: str,
        limit: int
    ) -> List[float]:
        """Получить список цен (close) для символа"""
        try:
            async with self.mexc as client:
                klines = await client.get_klines(symbol, interval, limit)
                if not klines:
                    return []
                
                # Извлекаем close цены (обычно индекс 4)
                prices = [float(kline[4]) for kline in klines if len(kline) > 4]
                return prices
        except Exception as e:
            logger.error(f"Error getting klines for {symbol}: {e}")
            return []
    
    async def get_volumes_for_symbol(
        self,
        symbol: str,
        interval: str,
        limit: int
    ) -> List[float]:
        """Получить список объёмов для символа"""
        try:
            async with self.mexc as client:
                klines = await client.get_klines(symbol, interval, limit)
                if not klines:
                    return []
                
                # Извлекаем объёмы (обычно индекс 7)
                volumes = [float(kline[7]) for kline in klines if len(kline) > 7]
                return volumes
        except Exception as e:
            logger.error(f"Error getting volumes for {symbol}: {e}")
            return []
    
    async def check_symbol(self, symbol: str) -> Tuple[bool, Dict]:
        """
        Проверить символ на предмет сигналов
        
        Returns:
            (signal_found, analysis_data)
        """
        try:
            # Получаем свечи разных таймфреймов
            prices_1m = await self.get_klines_for_symbol(symbol, "1m", 200)
            prices_5m = await self.get_klines_for_symbol(symbol, "5m", 144)  # 12 часов
            prices_15m = await self.get_klines_for_symbol(symbol, "15m", 100)
            prices_1h = await self.get_klines_for_symbol(symbol, "1h", 100)
            
            volumes_5m = await self.get_volumes_for_symbol(symbol, "5m", 144)
            
            # Проверяем условия
            if not all([prices_1m, prices_5m, prices_15m, prices_1h, volumes_5m]):
                return False, {}
            
            # Анализируем сигнал
            analysis = SignalAnalyzer.analyze_signal(
                prices_1m[:15],  # Последние 15 минут
                prices_15m,
                prices_1h
            )
            
            signal_triggered = analysis['signal_triggered']
            
            return signal_triggered, {
                'symbol': symbol,
                'analysis': analysis,
                'prices_5m': prices_5m,
                'volumes_5m': volumes_5m
            }
        
        except Exception as e:
            logger.error(f"Error checking symbol {symbol}: {e}")
            return False, {}
    
    async def monitor_all_pairs(self) -> List[Dict]:
        """
        Мониторить все USDT пары и найти сигналы
        
        Returns:
            Список сигналов
        """
        try:
            async with self.mexc as client:
                symbols = await client.get_all_symbols()
            
            logger.info(f"Checking {len(symbols)} symbols...")
            
            signals = []
            
            for symbol in symbols:
                signal_found, data = await self.check_symbol(symbol)
                
                if signal_found:
                    # Проверяем cooldown
                    import time
                    current_time = time.time()
                    last_time = self.last_signal_time.get(symbol, 0)
                    
                    if current_time - last_time >= self.signal_cooldown:
                        signals.append(data)
                        self.last_signal_time[symbol] = current_time
                        logger.info(f"✅ Signal found: {symbol}")
                    else:
                        logger.debug(f"Signal cooldown for {symbol}")
                
                # Небольшая задержка между проверками
                await asyncio.sleep(0.1)
            
            return signals
        
        except Exception as e:
            logger.error(f"Error monitoring pairs: {e}")
            return []
