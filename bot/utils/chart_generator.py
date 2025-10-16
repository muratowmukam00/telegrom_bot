import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict
from services.analysis.rsi import RSICalculator


class ChartGenerator:
    """Генерация графиков для сигналов (улучшенный вариант без легенд и с правыми шкалами)"""

    @staticmethod
    def _add_time_labels(ax, num_candles, end_time=None):
        """Добавить метки времени каждые 30 минут"""
        if end_time is None:
            end_time = datetime.now()

        interval_minutes = 5
        total_minutes = num_candles * interval_minutes
        start_time = end_time - timedelta(minutes=total_minutes)

        step = 30  # 30 минут
        times = []
        current = datetime(
            year=end_time.year,
            month=end_time.month,
            day=end_time.day,
            hour=end_time.hour,
            minute=(end_time.minute // 30) * 30
        )

        while current >= start_time:
            times.append(current)
            current -= timedelta(minutes=step)
        times.reverse()

        tick_positions = []
        tick_labels = []
        for t in times:
            diff = (t - start_time).total_seconds() / 60 / interval_minutes
            tick_positions.append(int(diff))
            tick_labels.append(t.strftime('%H:%M'))

        ax.set_xticks(tick_positions)
        ax.set_xticklabels(tick_labels, rotation=0, ha='center')
        ax.set_xlim(-1, num_candles)

    @staticmethod
    def generate_signal_chart(symbol: str, candles: List[Dict], output_path: str = "signal_chart.png") -> str:
        try:
            if not candles or len(candles) == 0:
                raise ValueError("Нет данных для построения графика")

            def safe_get(item, keys):
                for key in keys:
                    if key in item:
                        return float(item[key])
                return 0.0

            opens = [safe_get(c, ['open', 'o', 'Open']) for c in candles]
            highs = [safe_get(c, ['high', 'h', 'High']) for c in candles]
            lows = [safe_get(c, ['low', 'l', 'Low']) for c in candles]
            closes = [safe_get(c, ['close', 'c', 'Close']) for c in candles]
            volumes = [safe_get(c, ['volume', 'vol', 'v', 'Volume', 'amount']) for c in candles]

            rsi_values = RSICalculator.calculate(closes, period=14)

            fig, (ax1, ax2, ax3) = plt.subplots(
                3, 1,
                figsize=(16, 10),
                gridspec_kw={'height_ratios': [3, 1, 1]},
                sharex=True
            )
            fig.patch.set_facecolor('#1e1e1e')

            ax1.set_facecolor('#1e1e1e')
            ChartGenerator._plot_candlesticks(ax1, opens, highs, lows, closes)
            ax1.set_title(f'{symbol} - 5m Candlestick Chart (Last 12h)',
                          fontsize=14, fontweight='bold', color='white', pad=15)
            ax1.tick_params(colors='white')
            ax1.yaxis.tick_right()
            ax1.yaxis.set_label_position("right")
            ax1.grid(True, alpha=0.1, color='white')

            ax2.set_facecolor('#1e1e1e')
            ChartGenerator._plot_rsi(ax2, rsi_values)
            ax2.tick_params(colors='white')
            ax2.yaxis.tick_right()
            ax2.yaxis.set_label_position("right")
            ax2.set_ylabel('RSI', color='white', fontsize=10)
            ax2.grid(True, alpha=0.1, color='white')

            ax3.set_facecolor('#1e1e1e')
            ChartGenerator._plot_volume(ax3, volumes, opens, closes)
            ax3.tick_params(colors='white')
            ax3.yaxis.tick_right()
            ax3.yaxis.set_label_position("right")
            ax3.set_ylabel('Volume', color='white', fontsize=10)
            ax3.grid(True, alpha=0.1, color='white')

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
        candle_width = 0.6
        for i in range(len(closes)):
            open_price = opens[i]
            high_price = highs[i]
            low_price = lows[i]
            close_price = closes[i]
            color = '#26a69a' if close_price >= open_price else '#ef5350'
            body_height = abs(close_price - open_price)
            body_bottom = min(open_price, close_price)
            ax.plot([i, i], [low_price, high_price], color=color, linewidth=1)
            rect = Rectangle((i - candle_width / 2, body_bottom),
                             candle_width, body_height if body_height > 0 else 0.0001,
                             facecolor=color, edgecolor=color)
            ax.add_patch(rect)
        ax.set_xlim(-1, len(closes))

    @staticmethod
    def _plot_volume(ax, volumes, opens, closes):
        """Volume bars with dynamic top-5 average line"""
        n = len(volumes)
        avg_series = []

        # Dynamic top-5 average for each candle (sliding window of 200)
        for i in range(n):
            start = max(0, i - 199)
            window = volumes[start:i + 1]
            if len(window) > 5:
                top5 = sorted(window)[-5:]
                avg_val = np.mean(top5)
            else:
                avg_val = np.mean(window)
            avg_series.append(avg_val)

        # Цвета: синий если volume > avg_line, иначе серый
        colors = ['#2196f3' if volumes[i] > avg_series[i] else '#808080' for i in range(n)]

        # Бары
        ax.bar(range(n), volumes, color=colors, alpha=0.8, width=0.8)

        # Гладкая (сплошная) жёлтая линия среднего уровня
        ax.plot(range(n), avg_series, color='#ff9800', linewidth=2, linestyle='-')

        ax.set_xlim(-1, n)

    @staticmethod
    def _plot_rsi(ax, rsi_values):
        n = len(rsi_values)
        ax.plot(range(n), rsi_values, color='#ab47bc', linewidth=2)

        # Зоны перекупленности и перепроданности
        ax.axhspan(70, 100, color='#ffeb3b', alpha=0.2)
        ax.axhspan(0, 30, color='#4caf50', alpha=0.2)

        # Горизонтальные линии на уровнях 30 и 70
        ax.axhline(70, color='#f44336', linestyle='--', linewidth=1)
        ax.axhline(30, color='#4caf50', linestyle='--', linewidth=1)

        ax.set_ylim(0, 100)
        ax.set_xlim(-1, n)
