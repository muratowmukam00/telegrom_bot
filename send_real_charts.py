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

                # Извлекаем цены и объемы
                prices = client.extract_close_prices(klines_5m)
                volumes = client.extract_volumes(klines_5m)

                if len(prices) < 50:
                    print(f"  ⚠️  Недостаточно данных для {symbol}")
                    continue

                print(f"  Получено {len(prices)} свечей")
                print(f"  Цена: {prices[-1]:.8f} (мин: {min(prices):.8f}, макс: {max(prices):.8f})")

                # Генерируем график
                chart_path = ChartGenerator.generate_signal_chart(
                    symbol,
                    prices,
                    volumes,
                    output_path=f"logs/{symbol}_real.png"
                )

                if chart_path:
                    print(f"  ✅ График сгенерирован: {chart_path}")

                    # Отправляем в Telegram
                    result = await telegram.send_photo(
                        TELEGRAM_CHAT_ID,
                        chart_path,
                        caption=f"📊 {symbol} - 5m Chart (Last 12h)\n"
                                f"Цена: {prices[-1]:.8f}\n"
                                f"Min: {min(prices):.8f}\n"
                                f"Max: {max(prices):.8f}"
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

    await telegram.close()
    print("\n✅ Готово! Проверьте Telegram")


if __name__ == "__main__":
    asyncio.run(send_real_charts())
