import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
import numpy as np
from typing import List, Dict
from services.analysis.rsi import RSICalculator


class ChartGenerator:
    """Генерация графиков для сигналов"""

    @staticmethod
    def _add_time_labels(ax, num_candles):
        """Добавить временные метки на ось X"""
        from datetime import datetime, timedelta

        # Вычисляем время: каждая свеча = 5 минут, идём назад от текущего времени
        now = datetime.now()
        interval_minutes = 5

        # Создаём метки времени для каждой свечи
        times = []
        for i in range(num_candles):
            time = now - timedelta(minutes=interval_minutes * (num_candles - i - 1))
            times.append(time)

        # Выбираем каждую 24-ю свечу (каждые 2 часа) для меток
        step = 24  # 24 свечи * 5 минут = 2 часа
        tick_positions = list(range(0, num_candles, step))
        tick_labels = [times[i].strftime('%H:%M') for i in tick_positions]

        # Добавляем последнюю свечу
        if tick_positions[-1] != num_candles - 1:
            tick_positions.append(num_candles - 1)
            tick_labels.append(times[-1].strftime('%H:%M'))

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=0, ha='center')
        ax.set_xlim(-1, num_candles)

    @staticmethod
    def generate_signal_chart(
            symbol: str,
            candles: List[Dict] = None,  # [{'open': x, 'high': x, 'low': x, 'close': x, 'volume': x}, ...]
            prices_5m: List[float] = None,  # Обратная совместимость
            volumes_5m: List[float] = None,  # Обратная совместимость
            output_path: str = "signal_chart.png"
    ) -> str:
        """
        Генерировать свечной график сигнала (5m, последние 12 часов)

        Args:
            symbol: Название символа
            candles: Список свечей с OHLCV данными ИЛИ словарь с массивами
            prices_5m: Старый формат (для обратной совместимости)
            volumes_5m: Старый формат (для обратной совместимости)
            output_path: Путь для сохранения

        Returns:
            Путь к сохранённому файлу
        """
        try:
            # Проверяем формат данных и конвертируем если нужно
            if candles is None and prices_5m is not None and volumes_5m is not None:
                # Старый формат: только prices и volumes
                candles = []
                for i, (price, volume) in enumerate(zip(prices_5m, volumes_5m)):
                    prev_price = prices_5m[i - 1] if i > 0 else price
                    candles.append({
                        'open': prev_price,
                        'high': max(price, prev_price) * 1.001,
                        'low': min(price, prev_price) * 0.999,
                        'close': price,
                        'volume': volume
                    })
            elif candles is not None and isinstance(candles, dict):
                # MEXC API формат: словарь с массивами realOpen, realClose и т.д.
                opens_arr = candles.get('realOpen', candles.get('open', []))
                closes_arr = candles.get('realClose', candles.get('close', []))
                highs_arr = candles.get('realHigh', candles.get('high', []))
                lows_arr = candles.get('realLow', candles.get('low', []))
                volumes_arr = candles.get('volume', candles.get('vol', candles.get('amount', [])))

                # Конвертируем в список свечей
                candles = []
                min_len = min(len(opens_arr), len(closes_arr), len(highs_arr), len(lows_arr))
                for i in range(min_len):
                    candles.append({
                        'open': float(opens_arr[i]),
                        'high': float(highs_arr[i]),
                        'low': float(lows_arr[i]),
                        'close': float(closes_arr[i]),
                        'volume': float(volumes_arr[i]) if i < len(volumes_arr) and volumes_arr else 0
                    })
            elif candles is not None and isinstance(candles, list) and len(candles) > 0:
                # Список может содержать словари или списки
                if isinstance(candles[0], list):
                    # Список списков: [[timestamp, open, high, low, close, volume], ...]
                    new_candles = []
                    for k in candles:
                        if len(k) >= 6:
                            new_candles.append({
                                'open': float(k[1]),
                                'high': float(k[2]),
                                'low': float(k[3]),
                                'close': float(k[4]),
                                'volume': float(k[5])
                            })
                    candles = new_candles if new_candles else candles

            if not candles or len(candles) == 0:
                raise ValueError("Нет данных для построения графика")

            # Извлекаем данные с поддержкой разных форматов ключей
            def safe_get(item, keys):
                """Безопасно получить значение по списку возможных ключей"""
                for key in keys:
                    if key in item:
                        return float(item[key])
                return 0.0

            opens = [safe_get(c, ['open', 'o', 'Open']) for c in candles]
            highs = [safe_get(c, ['high', 'h', 'High']) for c in candles]
            lows = [safe_get(c, ['low', 'l', 'Low']) for c in candles]
            closes = [safe_get(c, ['close', 'c', 'Close']) for c in candles]
            volumes = [safe_get(c, ['volume', 'vol', 'v', 'Volume', 'amount']) for c in candles]

            # Рассчитываем RSI
            rsi_values = RSICalculator.calculate(closes, period=14)

            # Создаём фигуру с 3 субграфиками: График (верх), RSI (центр), Volume (низ)
            fig, (ax1, ax2, ax3) = plt.subplots(
                3, 1,
                figsize=(16, 10),
                gridspec_kw={'height_ratios': [3, 1, 1]},
                sharex=True  # Общая ось X для всех графиков
            )

            fig.patch.set_facecolor('#1e1e1e')  # Тёмный фон

            # График 1: Свечной график (ВЕРХ)
            ax1.set_facecolor('#1e1e1e')
            ChartGenerator._plot_candlesticks(ax1, opens, highs, lows, closes)
            ax1.set_title(f'{symbol} - 5m Candlestick Chart (Last 12h)',
                          fontsize=14, fontweight='bold', color='white', pad=15)
            ax1.set_ylabel('Price (USDT)', fontsize=11, color='white')
            ax1.grid(True, alpha=0.2, linestyle='--', color='gray')
            ax1.tick_params(colors='white')

            # График 2: RSI (ЦЕНТР)
            ax2.set_facecolor('#1e1e1e')
            ChartGenerator._plot_rsi(ax2, rsi_values)
            ax2.set_ylabel('RSI(14)', fontsize=11, color='white')
            ax2.grid(True, alpha=0.2, linestyle='--', color='gray')
            ax2.tick_params(colors='white')

            # График 3: Объём (НИЗ)
            ax3.set_facecolor('#1e1e1e')
            ChartGenerator._plot_volume(ax3, volumes, opens, closes)
            ax3.set_ylabel('Volume', fontsize=11, color='white')
            ax3.set_xlabel('Time (5m intervals)', fontsize=11, color='white')
            ax3.grid(True, alpha=0.2, axis='y', linestyle='--', color='gray')
            ax3.tick_params(colors='white')

            # Добавляем временные метки на ось X
            ChartGenerator._add_time_labels(ax3, len(closes))

            plt.tight_layout()
            plt.savefig(output_path, dpi=120, bbox_inches='tight', facecolor='#1e1e1e')
            plt.close()

            return output_path

        except Exception as e:
            print(f"Error generating chart: {e}")
            import traceback
            traceback.print_exc()
            return ""

    @staticmethod
    def _plot_candlesticks(ax, opens, highs, lows, closes):
        """Отрисовка свечей"""
        candle_width = 0.6
        wick_width = 0.1

        for i in range(len(closes)):
            open_price = opens[i]
            high_price = highs[i]
            low_price = lows[i]
            close_price = closes[i]

            # Определяем цвет свечи
            if close_price >= open_price:
                color = '#26a69a'  # Зелёная (растущая)
                body_height = close_price - open_price
                body_bottom = open_price
            else:
                color = '#ef5350'  # Красная (падающая)
                body_height = open_price - close_price
                body_bottom = close_price

            # Рисуем фитиль (wick)
            ax.plot([i, i], [low_price, high_price],
                    color=color, linewidth=1, solid_capstyle='round')

            # Рисуем тело свечи
            if body_height > 0:
                rect = Rectangle((i - candle_width / 2, body_bottom),
                                 candle_width, body_height,
                                 facecolor=color, edgecolor=color, linewidth=1)
            else:
                # Доджи (открытие = закрытие)
                rect = Rectangle((i - candle_width / 2, body_bottom - 0.0001),
                                 candle_width, 0.0002,
                                 facecolor=color, edgecolor=color, linewidth=1.5)
            ax.add_patch(rect)

        ax.set_xlim(-1, len(closes))

        # Добавляем легенду
        green_patch = mpatches.Patch(color='#26a69a', label='Bullish')
        red_patch = mpatches.Patch(color='#ef5350', label='Bearish')
        ax.legend(handles=[green_patch, red_patch], loc='upper left')

    @staticmethod
    def _plot_volume(ax, volumes, opens, closes):
        """Отрисовка объёма с цветами по свечам"""
        colors = ['#26a69a' if closes[i] >= opens[i] else '#ef5350'
                  for i in range(len(volumes))]

        bars = ax.bar(range(len(volumes)), volumes,
                      color=colors, alpha=0.6, width=0.8)

        # Средний объём топ-5 свечей
        avg_volume = np.mean(sorted(volumes)[-5:])
        ax.axhline(y=avg_volume, color='#ff9800', linestyle='--',
                   linewidth=2, label=f'Avg Vol (Top 5): {avg_volume:.0f}', alpha=0.8)

        ax.set_xlim(-1, len(volumes))
        ax.legend(loc='upper left')

    @staticmethod
    def _plot_rsi(ax, rsi_values):
        """Отрисовка RSI"""
        x = np.arange(len(rsi_values))

        # Линия RSI
        ax.plot(x, rsi_values, color='#9c27b0', linewidth=2, label='RSI(14)')

        # Уровни перекупленности/перепроданности
        ax.axhline(y=70, color='#ef5350', linestyle='--',
                   linewidth=1.5, alpha=0.7, label='Overbought (70)')
        ax.axhline(y=30, color='#26a69a', linestyle='--',
                   linewidth=1.5, alpha=0.7, label='Oversold (30)')
        ax.axhline(y=50, color='gray', linestyle=':',
                   linewidth=1, alpha=0.5)

        # Заливка зон
        ax.fill_between(x, 70, 100, alpha=0.1, color='#ef5350')
        ax.fill_between(x, 0, 30, alpha=0.1, color='#26a69a')

        ax.set_ylim(0, 100)
        ax.set_xlim(-1, len(rsi_values))
        ax.legend(loc='upper left')


# Пример использования:
if __name__ == "__main__":
    # Пример данных (замените на реальные данные из API)
    example_candles = [
        {'open': 100, 'high': 105, 'low': 98, 'close': 103, 'volume': 1000},
        {'open': 103, 'high': 108, 'low': 102, 'close': 107, 'volume': 1500},
        {'open': 107, 'high': 110, 'low': 105, 'close': 106, 'volume': 1200},
        # ... добавьте больше свечей
    ]

    chart = ChartGenerator()
    chart.generate_signal_chart("BTC_USDT", example_candles, "test_chart.png")