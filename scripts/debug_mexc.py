import asyncio
import aiohttp
from config.settings import MEXC_BASE_URL


async def debug_mexc_api():
    """Проверяем что именно возвращает MEXC API"""

    print("=" * 60)
    print("🔍 ОТЛАДКА MEXC API - Правильные параметры")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:

        # Тест 1: Правильный формат interval
        print("\n1️⃣ Проверяем разные форматы interval...")

        intervals = [
            ("Min1", "1 минута"),
            ("Min5", "5 минут"),
            ("Min15", "15 минут"),
            ("Min60", "1 час"),
            ("Hour4", "4 часа"),
            ("Day1", "1 день"),
            ("1m", "1m альтернативный"),
            ("5m", "5m альтернативный"),
        ]

        for interval, desc in intervals:
            url = f"{MEXC_BASE_URL}/api/v1/contract/kline/BTC_USDT"
            params = {
                "interval": interval,
                "start": "",
                "end": ""
            }

            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        if data.get("success") and data.get("data"):
                            klines = data["data"]
                            print(f"   ✅ {interval:10s} ({desc:20s}): {len(klines)} свечей")

                            if klines:
                                # Показываем структуру первой свечи
                                print(
                                    f"      Структура: {list(klines[0].keys()) if isinstance(klines[0], dict) else 'Array'}")
                                if isinstance(klines[0], dict):
                                    print(f"      Пример: open={klines[0].get('open')}, close={klines[0].get('close')}")
                                else:
                                    print(f"      Пример: {klines[0]}")
                        else:
                            print(f"   ❌ {interval:10s} ({desc:20s}): {data.get('message', 'No data')}")
            except Exception as e:
                print(f"   ❌ {interval:10s}: Ошибка - {e}")

        # Тест 2: Проверяем формат с start/end временем
        print("\n2️⃣ Проверяем с временными метками...")

        import time
        end_time = int(time.time())
        start_time = end_time - 3600  # 1 час назад

        url = f"{MEXC_BASE_URL}/api/v1/contract/kline/BTC_USDT"
        params = {
            "interval": "Min1",
            "start": start_time,
            "end": end_time
        }

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

                if data.get("success") and data.get("data"):
                    print(f"   ✅ С временем: получено {len(data['data'])} свечей")
                else:
                    print(f"   ❌ С временем: {data.get('message')}")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

        # Тест 3: Без параметров времени
        print("\n3️⃣ Проверяем БЕЗ start/end...")

        url = f"{MEXC_BASE_URL}/api/v1/contract/kline/BTC_USDT"
        params = {"interval": "Min1"}

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

                if data.get("success") and data.get("data"):
                    klines = data["data"]
                    print(f"   ✅ Без времени: получено {len(klines)} свечей")

                    if klines:
                        first = klines[0]
                        last = klines[-1]
                        print(f"   Первая свеча: {first}")
                        print(f"   Последняя свеча: {last}")
                else:
                    print(f"   ❌ Без времени: {data}")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

        # Тест 4: Проверяем ticker (исправленный)
        print("\n4️⃣ Проверяем ticker...")
        url = f"{MEXC_BASE_URL}/api/v1/contract/ticker"
        params = {"symbol": "BTC_USDT"}

        try:
            async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()

                if data.get("success") and data.get("data"):
                    ticker = data["data"][0] if isinstance(data["data"], list) else data["data"]
                    print(f"   ✅ Ticker:")
                    print(f"      Symbol: {ticker.get('symbol')}")
                    print(f"      Last Price: {ticker.get('lastPrice')}")
                    print(f"      24h Change: {ticker.get('riseFallRate')}%")
                else:
                    print(f"   ❌ Ticker: {data}")
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")

    print("\n" + "=" * 60)
    print("✅ Отладка завершена")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(debug_mexc_api())