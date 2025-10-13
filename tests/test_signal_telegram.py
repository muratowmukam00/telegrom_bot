import asyncio
import numpy as np
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.services import TelegramService
from bot.utils import ChartGenerator

async def send_test_signal():
    """Отправить тестовый сигнал с графиком в Telegram"""
    
    print("Создаём тестовый сигнал...")
    
    # Создаём реалистичные тестовые данные (имитируем движение цены)
    np.random.seed(42)
    base_price = 100
    prices_5m = []
    
    # Создаём реалистичный график цены (случайное блуждание)
    for i in range(144):  # 144 * 5 минут = 12 часов
        change = np.random.normal(0, 0.5)  # Случайное изменение
        base_price += change
        prices_5m.append(base_price)
    
    # Создаём объёмы торговли
    volumes_5m = [1000000 + np.random.randint(-300000, 500000) for _ in range(144)]
    
    symbol = "TEST_USDT"
    
    # Генерируем график
    print(f"Генерируем график для {symbol}...")
    chart_path = ChartGenerator.generate_signal_chart(
        symbol,
        prices_5m,
        volumes_5m,
        output_path=f"logs/{symbol}_test.png"
    )
    print(f"График сохранён: {chart_path}")
    
    # Создаём тестовый анализ
    analysis = {
        'signal_triggered': True,
        'filter_1_price': (True, 8.5),      # Цена выросла на 8.5%
        'filter_2_rsi_1h': (True, 72.3),    # RSI 1h = 72.3 (перекуплено)
        'filter_3_rsi_15m': (True, 75.8),   # RSI 15m = 75.8 (перекуплено)
    }
    
    # Отправляем сигнал в Telegram
    print("Отправляем сигнал в Telegram...")
    telegram = TelegramService(TELEGRAM_BOT_TOKEN)
    
    # Отправляем алерт
    result1 = await telegram.send_signal_alert(
        TELEGRAM_CHAT_ID,
        symbol,
        analysis
    )
    
    if result1:
        print("✅ Алерт отправлен!")
    else:
        print("❌ Ошибка отправки алерта")
    
    # Отправляем график
    await asyncio.sleep(1)  # Небольшая задержка
    result2 = await telegram.send_photo(
        TELEGRAM_CHAT_ID,
        chart_path,
        caption=f"📊 Тестовый график {symbol} (5m, последние 12ч)"
    )
    
    if result2:
        print("✅ График отправлен!")
    else:
        print("❌ Ошибка отправки графика")
    
    await telegram.close()
    
    print("\n✅ Тестовый сигнал отправлен в Telegram!")
    print(f"   Откройте Telegram и проверьте чат!")

if __name__ == "__main__":
    asyncio.run(send_test_signal())
