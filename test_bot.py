import asyncio
import logging
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from services.mexc import MexcClient, PairMonitor
from services.analysis import RSICalculator, SignalAnalyzer
from bot.services import TelegramService
from bot.utils import ChartGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_config():
    """Тест 1: Проверка конфигурации"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 1: КОНФИГУРАЦИЯ")
    print("="*60)
    
    if TELEGRAM_BOT_TOKEN and TELEGRAM_BOT_TOKEN != "YOUR_BOT_TOKEN_HERE":
        print("✅ TELEGRAM_BOT_TOKEN: OK")
    else:
        print("❌ TELEGRAM_BOT_TOKEN: НЕ УСТАНОВЛЕН")
        return False
    
    if TELEGRAM_CHAT_ID and TELEGRAM_CHAT_ID != "YOUR_CHAT_ID_HERE":
        print("✅ TELEGRAM_CHAT_ID: OK")
    else:
        print("❌ TELEGRAM_CHAT_ID: НЕ УСТАНОВЛЕН")
        return False
    
    return True

async def test_mexc_api():
    """Тест 2: MEXC API"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 2: MEXC API")
    print("="*60)
    
    try:
        client = MexcClient()
        
        # Получаем символы
        async with client as c:
            symbols = await c.get_all_symbols()
        
        if symbols:
            print(f"✅ Получено {len(symbols)} символов")
            print(f"   Первые 5: {symbols[:5]}")
        else:
            print("❌ Не удалось получить символы")
            return False
        
        # Получаем свечи для тестовой пары
        test_symbol = symbols[0] if symbols else "BTC_USDT"
        async with client as c:
            klines = await c.get_klines(test_symbol, "1m", 50)
        
        if klines:
            print(f"✅ Получены свечи для {test_symbol}: {len(klines)} штук")
        else:
            print(f"❌ Не удалось получить свечи для {test_symbol}")
            return False
        
        return True
    except Exception as e:
        print(f"❌ Ошибка API: {e}")
        return False

async def test_rsi_calculation():
    """Тест 3: Расчёт RSI"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 3: РАСЧЁТ RSI")
    print("="*60)
    
    try:
        # Создаём тестовые данные
        test_prices = [100 + i*0.5 for i in range(50)]
        
        rsi_values = RSICalculator.calculate(test_prices, period=14)
        
        if rsi_values:
            last_rsi = rsi_values[-1]
            print(f"✅ RSI рассчитан: {len(rsi_values)} значений")
            print(f"   Последний RSI: {last_rsi:.2f}")
            return True
        else:
            print("❌ RSI не рассчитан")
            return False
    except Exception as e:
        print(f"❌ Ошибка расчёта RSI: {e}")
        return False

async def test_signal_analyzer():
    """Тест 4: Анализ сигналов"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 4: АНАЛИЗ СИГНАЛОВ")
    print("="*60)
    
    try:
        # Создаём тестовые данные (15 свечей по 1 мин)
        prices_1m = [100 + i*0.5 for i in range(15)]
        
        # Тестовые данные для 15м и 1h
        prices_15m = [100 + i*0.3 for i in range(50)]
        prices_1h = [100 + i*0.2 for i in range(100)]
        
        # Проверяем каждый фильтр
        f1_passed, f1_change = SignalAnalyzer.check_price_change(prices_1m)
        print(f"✅ Фильтр 1 (Цена): {'PASSED' if f1_passed else 'FAILED'}")
        print(f"   Изменение: {f1_change:.2f}%")
        
        f2_passed, f2_rsi = SignalAnalyzer.check_rsi_1h(prices_1h)
        print(f"✅ Фильтр 2 (RSI 1h): {'PASSED' if f2_passed else 'FAILED'}")
        print(f"   RSI: {f2_rsi:.2f}")
        
        f3_passed, f3_rsi = SignalAnalyzer.check_rsi_15m(prices_15m)
        print(f"✅ Фильтр 3 (RSI 15m): {'PASSED' if f3_passed else 'FAILED'}")
        print(f"   RSI: {f3_rsi:.2f}")
        
        # Полный анализ
        analysis = SignalAnalyzer.analyze_signal(prices_1m, prices_15m, prices_1h)
        print(f"\n✅ Полный анализ: {'СИГНАЛ!' if analysis['signal_triggered'] else 'Нет сигнала'}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка анализа: {e}")
        return False

async def test_telegram():
    """Тест 5: Telegram сервис"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 5: TELEGRAM СЕРВИС")
    print("="*60)
    
    try:
        telegram = TelegramService(TELEGRAM_BOT_TOKEN)
        
        # Отправляем тестовое сообщение
        result = await telegram.send_message(
            TELEGRAM_CHAT_ID,
            "🧪 <b>Тестовое сообщение от бота</b>\n\n"
            "✅ Все компоненты работают корректно!"
        )
        
        if result:
            print("✅ Тестовое сообщение отправлено в Telegram!")
            await telegram.close()
            return True
        else:
            print("❌ Не удалось отправить сообщение")
            return False
    except Exception as e:
        print(f"❌ Ошибка Telegram: {e}")
        return False

async def test_chart_generator():
    """Тест 6: Генератор графиков"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 6: ГЕНЕРАТОР ГРАФИКОВ")
    print("="*60)
    
    try:
        import numpy as np
        
        # Создаём тестовые данные
        prices = [100 + np.sin(i/10) * 5 for i in range(144)]
        volumes = [1000000 + np.random.randint(-500000, 500000) for _ in range(144)]
        
        chart_path = ChartGenerator.generate_signal_chart(
            "TEST_USDT",
            prices,
            volumes,
            output_path="logs/test_chart.png"
        )
        
        if chart_path:
            print(f"✅ График создан: {chart_path}")
            return True
        else:
            print("❌ Не удалось создать график")
            return False
    except Exception as e:
        print(f"❌ Ошибка генератора: {e}")
        return False

async def test_monitor():
    """Тест 7: Монитор пар"""
    print("\n" + "="*60)
    print("✅ ТЕСТ 7: МОНИТОР ПАР (БЫСТРАЯ ПРОВЕРКА)")
    print("="*60)
    
    try:
        monitor = PairMonitor()
        
        # Проверяем 1 пару
        test_symbol = "BTC_USDT"
        signal_found, data = await monitor.check_symbol(test_symbol)
        
        print(f"✅ Проверена пара: {test_symbol}")
        print(f"   Сигнал найден: {'ДА' if signal_found else 'НЕТ'}")
        
        return True
    except Exception as e:
        print(f"❌ Ошибка монитора: {e}")
        return False

async def main():
    """Запуск всех тестов"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  🧪 ТЕСТИРОВАНИЕ MEXC SIGNAL BOT".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")
    
    results = {
        "Конфигурация": await test_config(),
        "MEXC API": await test_mexc_api(),
        "Расчёт RSI": await test_rsi_calculation(),
        "Анализ сигналов": await test_signal_analyzer(),
        "Telegram": await test_telegram(),
        "Генератор графиков": await test_chart_generator(),
        "Монитор пар": await test_monitor(),
    }
    
    # Итоги
    print("\n" + "="*60)
    print("📊 ИТОГИ ТЕСТИРОВАНИЯ")
    print("="*60)
    
    for test_name, result in results.items():
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{test_name}: {status}")
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    print("\n" + "="*60)
    print(f"Результат: {passed}/{total} тестов пройдено")
    print("="*60 + "\n")
    
    if passed == total:
        print("🎉 ВСЕ ТЕСТЫ ПРОЙДЕНЫ! БОТ ГОТОВ К РАБОТЕ!")
    else:
        print(f"⚠️  {total - passed} тест(ов) не пройдено. Проверьте ошибки выше.")

if __name__ == "__main__":
    asyncio.run(main())
