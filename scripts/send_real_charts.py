import asyncio
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from bot.services import TelegramService
from bot.utils import ChartGenerator
from services.mexc import MexcClient


async def send_real_charts():
    """Отправить реальные графики топ пар с MEXC — как будто сигнал"""

    telegram = TelegramService(TELEGRAM_BOT_TOKEN)
    symbols_to_chart = ["BTC_USDT", "ETH_USDT", "SOL_USDT"]
    print("🚀 Получаем данные с MEXC и отправляем графики через TelegramService...\n")

    async with MexcClient() as client:
        for symbol in symbols_to_chart:
            try:
                print(f"📊 Обработка {symbol}...")

                # Получаем реальные данные (5m, 144 свечи ~12 часов)
                klines_5m = await client.get_klines(symbol, "5m", 144)
                if not klines_5m:
                    print(f"  ❌ Не удалось получить данные для {symbol}")
                    continue

                # Генерация графика (универсальный метод)
                chart_path = ChartGenerator.generate_signal_chart(
                    symbol=symbol,
                    candles=klines_5m,
                    output_path=f"logs/{symbol}_real.png"
                )

                if not chart_path:
                    print(f"  ❌ Ошибка генерации графика для {symbol}")
                    continue

                # Получаем значения для подписи
                last_price = klines_5m[-1].get('close', 0)
                max_price = max(k.get('high', 0) for k in klines_5m)
                min_price = min(k.get('low', 0) for k in klines_5m)

                # Формируем фейковый анализ для send_signal_alert
                fake_analysis = {
                    "filter_1_price": (True, 1.25),
                    "filter_2_rsi_1h": (True, 55.32),
                    "filter_3_rsi_15m": (False, 68.45),
                    "signal_triggered": True
                }

                # Отправляем красивый сигнал через TelegramService
                await telegram.send_signal_alert(
                    TELEGRAM_CHAT_ID,
                    symbol,
                    fake_analysis
                )

                # Дополнительно отправляем сам график
                caption = (
                    f"📊 {symbol} - 5m Chart (Last 12h)\n"
                    f"💰 <b>Цена:</b> {last_price:.4f}\n"
                    f"📈 High: {max_price:.4f}\n"
                    f"📉 Low: {min_price:.4f}"
                )

                await telegram.send_photo(
                    TELEGRAM_CHAT_ID,
                    chart_path,
                    caption=caption
                )

                print(f"  ✅ График и сигнал отправлены для {symbol}")
                await asyncio.sleep(3)

            except Exception as e:
                print(f"  ❌ Ошибка обработки {symbol}: {e}")
                import traceback
                traceback.print_exc()

    await telegram.close()
    print("\n✅ Готово! Проверьте Telegram — сигналы отправлены.")


if __name__ == "__main__":
    asyncio.run(send_real_charts())
