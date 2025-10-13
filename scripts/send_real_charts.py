import asyncio
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.services import TelegramService
from bot.utils import ChartGenerator
from services.mexc import MexcClient


async def send_real_charts():
    """Отправить реальные графики топ пар с MEXC"""

    telegram = TelegramService(TELEGRAM_BOT_TOKEN)

    symbols_to_chart = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    print("Получаем данные с MEXC и генерируем графики...\n")

    async with MexcClient() as client:
        for symbol in symbols_to_chart:
            try:
                print(f"Обработка {symbol}...")

                # Получаем реальные данные (5m, 144 свечи ~12 часов)
                klines_5m = await client.get_klines(symbol, "5m", 144)
                if not klines_5m:
                    print(f"  ❌ Не удалось получить данные для {symbol}")
                    continue

                # Проверяем формат данных
                print(f"  Тип данных: {type(klines_5m)}")

                # ВАЖНО: Передаём данные напрямую - функция сама разберёт формат
                chart_path = ChartGenerator.generate_signal_chart(
                    symbol=symbol,
                    candles=klines_5m,  # Передаём как есть
                    output_path=f"logs/{symbol}_real.png"
                )

                if chart_path:
                    print(f"  ✅ График сгенерирован: {chart_path}")

                    # Получаем последнюю цену для caption
                    if isinstance(klines_5m, dict):
                        closes = klines_5m.get('realClose', klines_5m.get('close', []))
                        highs = klines_5m.get('realHigh', klines_5m.get('high', []))
                        lows = klines_5m.get('realLow', klines_5m.get('low', []))
                        last_price = closes[-1] if closes else 0
                        max_price = max(highs) if highs else 0
                        min_price = min(lows) if lows else 0
                    else:
                        last_price = klines_5m[-1].get('close', 0)
                        max_price = max(k.get('high', 0) for k in klines_5m)
                        min_price = min(k.get('low', 0) for k in klines_5m)

                    # Отправляем в Telegram
                    result = await telegram.send_photo(
                        TELEGRAM_CHAT_ID,
                        chart_path,
                        caption=f"📊 {symbol} - 5m Candlestick Chart (Last 12h)\n"
                                f"Close: {last_price:.8f}\n"
                                f"High: {max_price:.8f}\n"
                                f"Low: {min_price:.8f}"
                    )

                    if result:
                        print(f"  ✅ График отправлен в Telegram")
                    else:
                        print(f"  ❌ Ошибка отправки")

                    await asyncio.sleep(2)  # Задержка между отправками
                else:
                    print(f"  ❌ Ошибка генерации графика")

            except Exception as e:
                print(f"  ❌ Ошибка: {e}")
                import traceback
                traceback.print_exc()

    await telegram.close()
    print("\n✅ Готово! Проверьте Telegram")


# Альтернативный вариант: если хотите использовать старый формат
async def send_real_charts_old_format():
    """Отправить графики используя старый формат (только close prices)"""

    telegram = TelegramService(TELEGRAM_BOT_TOKEN)
    symbols_to_chart = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]

    async with MexcClient() as client:
        for symbol in symbols_to_chart:
            try:
                print(f"Обработка {symbol}...")

                klines_5m = await client.get_klines(symbol, "5m", 144)
                if not klines_5m:
                    continue

                # Извлекаем цены и объемы
                prices = client.extract_close_prices(klines_5m)
                volumes = client.extract_volumes(klines_5m)

                if len(prices) < 50:
                    continue

                # ВАЖНО: Используем именованные аргументы!
                chart_path = ChartGenerator.generate_signal_chart(
                    symbol=symbol,
                    prices_5m=prices,  # Именованный аргумент
                    volumes_5m=volumes,  # Именованный аргумент
                    output_path=f"logs/{symbol}_real.png"
                )

                if chart_path:
                    result = await telegram.send_photo(
                        TELEGRAM_CHAT_ID,
                        chart_path,
                        caption=f"📊 {symbol}\nЦена: {prices[-1]:.8f}"
                    )
                    await asyncio.sleep(2)

            except Exception as e:
                print(f"Ошибка: {e}")

    await telegram.close()


if __name__ == "__main__":
    # Используйте первый вариант для свечного графика
    asyncio.run(send_real_charts())

    # Или второй для простого графика линий
    # asyncio.run(send_real_charts_old_format())