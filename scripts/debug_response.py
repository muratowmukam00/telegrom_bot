import asyncio
import aiohttp
from config.settings import MEXC_BASE_URL

async def debug_response():
    """Смотрим что именно возвращает API"""
    
    print("=" * 60)
    print("🔍 ДЕТАЛЬНАЯ ОТЛАДКА ОТВЕТА")
    print("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        url = f"{MEXC_BASE_URL}/api/v1/contract/kline/BTC_USDT"
        params = {
            "interval": "Min1",
            "start": "",
            "end": ""
        }
        
        print(f"\n📡 Запрос:")
        print(f"   URL: {url}")
        print(f"   Params: {params}")
        
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            print(f"\n📥 Ответ:")
            print(f"   Status: {resp.status}")
            print(f"   Headers: {dict(resp.headers)}")
            
            # Получаем текст ответа
            text = await resp.text()
            print(f"\n📄 Raw response (первые 500 символов):")
            print(f"   {text[:500]}")
            
            # Парсим JSON
            try:
                import json
                data = json.loads(text)
                
                print(f"\n📊 Parsed JSON:")
                print(f"   Type: {type(data)}")
                print(f"   Keys: {data.keys() if isinstance(data, dict) else 'Not a dict'}")
                
                if isinstance(data, dict):
                    print(f"\n   success: {data.get('success')}")
                    print(f"   code: {data.get('code')}")
                    print(f"   message: {data.get('message')}")
                    
                    if 'data' in data:
                        klines = data['data']
                        print(f"\n   data type: {type(klines)}")
                        print(f"   data length: {len(klines) if isinstance(klines, list) else 'N/A'}")
                        
                        if isinstance(klines, list) and len(klines) > 0:
                            print(f"\n   Первая свеча:")
                            print(f"   Type: {type(klines[0])}")
                            print(f"   Content: {klines[0]}")
                            
                            if isinstance(klines[0], dict):
                                print(f"   Keys: {klines[0].keys()}")
                        else:
                            print(f"   ⚠️  data пустой или не список")
                    else:
                        print(f"\n   ⚠️  'data' не найден в ответе")
                
                print(f"\n📋 Полный JSON (отформатированный):")
                print(json.dumps(data, indent=2, ensure_ascii=False))
                
            except json.JSONDecodeError as e:
                print(f"\n❌ Ошибка парсинга JSON: {e}")
    
    print("\n" + "=" * 60)


if __name__ == "__main__":
    asyncio.run(debug_response())
