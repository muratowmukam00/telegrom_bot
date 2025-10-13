import asyncio
import sys
sys.path.insert(0, '.')

# Импортируем исправленный клиент из артефакта
# (скопируй код из артефакта в services/mexc/api_client.py)

from services.mexc import MexcClient

async def test_fixed_api():
    """Тестируем исправленный API клиент"""
    
    print("=" * 60)
    print("🧪 ТЕСТ ИСПРАВЛЕННОГО API КЛИЕНТА")
    print("=" * 60)
    
    async with MexcClient() as client:
        
        # Тест 1: Получаем символы
        print("\n1️⃣ Получение символов...")
        symbols = await client.get_all_symbols()
        
        if symbols:
            print(f"   ✅ Получено {len(symbols)} символов")
            print(f"   Первые 5: {symbols[:5]}")
        else:
            print("   ❌ Не получили символы")
            return
        
        # Тест 2: Получаем klines для BTC_USDT
        test_symbol = "BTC_USDT"
        print(f"\n2️⃣ Получение klines для {test_symbol}...")
        
        intervals_to_test = ["1m", "5m", "15m", "1h"]
        
        for interval in intervals_to_test:
            klines = await client.get_klines(test_symbol, interval, 100)
            
            if klines:
                print(f"   ✅ {interval:5s}: {len(klines)} свечей")
                
                # Извлекаем цены
                prices = client.extract_close_prices(klines)
                volumes = client.extract_volumes(klines)
                
                if prices:
                    print(f"           Цена: {prices[-1]:.2f} (min: {min(prices):.2f}, max: {max(prices):.2f})")
                if volumes:
                    print(f"           Объем: {sum(volumes):.0f}")
            else:
                print(f"   ❌ {interval:5s}: Не получили данные")
        
        # Тест 3: Получаем 24h изменение
        print(f"\n3️⃣ Получение 24h изменения для {test_symbol}...")
        change = await client.get_24h_price_change(test_symbol)
        
        if change is not None:
            print(f"   ✅ 24h изменение: {change:.2f}%")
        else:
            print(f"   ❌ Не получили изменение")
        
        # Тест 4: Проверяем несколько символов
        print(f"\n4️⃣ Быстрая проверка топ-5 символов...")
        
        for symbol in symbols[:5]:
            klines = await client.get_klines(symbol, "1m", 50)
            
            if klines:
                prices = client.extract_close_prices(klines)
                print(f"   ✅ {symbol:15s}: {len(klines)} свечей, цена: {prices[-1] if prices else 'N/A'}")
            else:
                print(f"   ❌ {symbol:15s}: Нет данных")
    
    print("\n" + "=" * 60)
    print("✅ Тест завершен!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_fixed_api())
