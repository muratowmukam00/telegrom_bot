"""
Chart Generator - Production Version
Генерация профессиональных графиков для торговых сигналов
"""

import logging
import matplotlib
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from pathlib import Path

# Используем Agg backend для серверов без GUI
matplotlib.use('Agg')

from services.analysis.rsi import RSICalculator

logger = logging.getLogger(__name__)


class ChartGenerator:
    """
    Production генератор графиков

    Features:
    - Валидация входных данных
    - Правильное управление памятью
    - Error handling
    - Оптимизация для production
    """

    # Константы для стилизации
    BG_COLOR = '#1e1e1e'
    GRID_COLOR = 'white'
    GRID_ALPHA = 0.1

    CANDLE_UP_COLOR = '#26a69a'
    CANDLE_DOWN_COLOR = '#ef5350'

    RSI_LINE_COLOR = '#ab47bc'
    RSI_OVERBOUGHT_COLOR = '#ffeb3b'
    RSI_OVERSOLD_COLOR = '#4caf50'

    VOLUME_HIGH_COLOR = '#2196f3'
    VOLUME_LOW_COLOR = '#808080'
    VOLUME_AVG_COLOR = '#ff9800'

    DPI = 120  # Качество изображения

    @staticmethod
    def _validate_candles(candles: List[Dict]) -> bool:
        """
        Валидация данных свечей

        Args:
            candles: Список свечей

        Returns:
            True если данные валидны
        """
        if not candles or len(candles) == 0:
            logger.error("Пустой список свечей")
            return False

        # Проверяем первую свечу
        required_fields = ['open', 'high', 'low', 'close']
        first_candle = candles[0]

        if not isinstance(first_candle, dict):
            logger.error(f"Свеча не dict: {type(first_candle)}")
            return False

        for field in required_fields:
            if field not in first_candle:
                logger.error(f"Отсутствует поле '{field}' в свече")
                return False

        return True

    @staticmethod
    def _safe_get(item: Dict, keys: List[str], default: float = 0.0) -> float:
        """
        Безопасное извлечение значения из словаря с несколькими вариантами ключей

        Args:
            item: Словарь
            keys: Список возможных ключей
            default: Значение по умолчанию

        Returns:
            Значение или default
        """
        for key in keys:
            if key in item:
                try:
                    return float(item[key])
                except (ValueError, TypeError):
                    logger.warning(f"Не удалось конвертировать '{key}': {item[key]}")
                    continue
        return default

    @staticmethod
    def _add_time_labels(ax, num_candles: int, end_time: Optional[datetime] = None):
        """
        Добавить метки времени на ось X

        Args:
            ax: Matplotlib axis
            num_candles: Количество свечей
            end_time: Время последней свечи
        """
        if end_time is None:
            end_time = datetime.now()

        interval_minutes = 5
        total_minutes = num_candles * interval_minutes
        start_time = end_time - timedelta(minutes=total_minutes)

        step = 30  # Метки каждые 30 минут
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
    def _plot_candlesticks(
            ax,
            opens: List[float],
            highs: List[float],
            lows: List[float],
            closes: List[float]
    ):
        """
        Отрисовка японских свечей

        Args:
            ax: Matplotlib axis
            opens, highs, lows, closes: Данные OHLC
        """
        candle_width = 0.6

        for i in range(len(closes)):
            open_price = opens[i]
            high_price = highs[i]
            low_price = lows[i]
            close_price = closes[i]

            # Цвет свечи
            color = (
                ChartGenerator.CANDLE_UP_COLOR
                if close_price >= open_price
                else ChartGenerator.CANDLE_DOWN_COLOR
            )

            # Тело свечи
            body_height = abs(close_price - open_price)
            body_bottom = min(open_price, close_price)

            # Фитиль (high-low line)
            ax.plot(
                [i, i],
                [low_price, high_price],
                color=color,
                linewidth=1
            )

            # Прямоугольник тела
            rect = Rectangle(
                (i - candle_width / 2, body_bottom),
                candle_width,
                body_height if body_height > 0 else 0.0001,
                facecolor=color,
                edgecolor=color
            )
            ax.add_patch(rect)

        ax.set_xlim(-1, len(closes))

    @staticmethod
    def _plot_volume(
            ax,
            volumes: List[float],
    ):
        """
        Отрисовка объёмов с динамической линией среднего

        Args:
            ax: Matplotlib axis
            volumes: Объёмы
            opens, closes: Цены для определения цвета
        """
        n = len(volumes)
        avg_series = []

        # Динамический top-5 average (скользящее окно 200)
        for i in range(n):
            start = max(0, i - 199)
            window = volumes[start:i + 1]
            if len(window) > 5:
                top5 = sorted(window)[-5:]
                avg_val = np.mean(top5)
            else:
                avg_val = np.mean(window) if window else 0
            avg_series.append(avg_val)

        # Цвета баров: синий если volume > avg, иначе серый
        colors = [
            ChartGenerator.VOLUME_HIGH_COLOR if volumes[i] > avg_series[i]
            else ChartGenerator.VOLUME_LOW_COLOR
            for i in range(n)
        ]

        # Бары объёма
        ax.bar(range(n), volumes, color=colors, alpha=0.8, width=0.8)

        # Линия среднего уровня
        ax.plot(
            range(n),
            avg_series,
            color=ChartGenerator.VOLUME_AVG_COLOR,
            linewidth=2,
            linestyle='-'
        )

        ax.set_xlim(-1, n)

    @staticmethod
    def _plot_rsi(ax, rsi_values: List[float]):
        """
        Отрисовка RSI индикатора

        Args:
            ax: Matplotlib axis
            rsi_values: Значения RSI
        """
        n = len(rsi_values)

        # Линия RSI
        ax.plot(
            range(n),
            rsi_values,
            color=ChartGenerator.RSI_LINE_COLOR,
            linewidth=2
        )

        # Зоны перекупленности и перепроданности
        ax.axhspan(
            70, 100,
            color=ChartGenerator.RSI_OVERBOUGHT_COLOR,
            alpha=0.2
        )
        ax.axhspan(
            0, 30,
            color=ChartGenerator.RSI_OVERSOLD_COLOR,
            alpha=0.2
        )

        # Горизонтальные линии
        ax.axhline(70, color='#f44336', linestyle='--', linewidth=1)
        ax.axhline(30, color='#4caf50', linestyle='--', linewidth=1)

        ax.set_ylim(0, 100)
        ax.set_xlim(-1, n)

    @staticmethod
    def generate_signal_chart(
            symbol: str,
            candles: List[Dict],
            output_path: str = "signal_chart.png"
    ) -> str:
        """
        Генерация профессионального графика сигнала

        Args:
            symbol: Символ (BTC_USDT)
            candles: Список свечей (5m, последние 12 часов)
            output_path: Путь для сохранения

        Returns:
            Путь к сохранённому файлу или пустая строка при ошибке
        """
        try:
            # Валидация
            if not ChartGenerator._validate_candles(candles):
                return ""

            # Создаём директорию если нужно
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)

            # Извлекаем данные
            opens = [
                ChartGenerator._safe_get(c, ['open', 'o', 'Open'])
                for c in candles
            ]
            highs = [
                ChartGenerator._safe_get(c, ['high', 'h', 'High'])
                for c in candles
            ]
            lows = [
                ChartGenerator._safe_get(c, ['low', 'l', 'Low'])
                for c in candles
            ]
            closes = [
                ChartGenerator._safe_get(c, ['close', 'c', 'Close'])
                for c in candles
            ]
            volumes = [
                ChartGenerator._safe_get(c, ['volume', 'vol', 'v', 'Volume', 'amount'])
                for c in candles
            ]

            # Проверка данных
            if len(closes) < 14:  # Минимум для RSI
                logger.warning(f"Недостаточно данных для {symbol}: {len(closes)} свечей")
                return ""

            # Расчёт RSI
            rsi_values = RSICalculator.calculate(closes, period=14)

            # Создаём фигуру
            fig, (ax1, ax2, ax3) = plt.subplots(
                3, 1,
                figsize=(16, 10),
                gridspec_kw={'height_ratios': [3, 1, 1]},
                sharex=True
            )
            fig.patch.set_facecolor(ChartGenerator.BG_COLOR)

            # График 1: Свечи
            ax1.set_facecolor(ChartGenerator.BG_COLOR)
            ChartGenerator._plot_candlesticks(ax1, opens, highs, lows, closes)
            ax1.set_title(
                f'{symbol} - 5m Chart (Last 12h)',
                fontsize=14,
                fontweight='bold',
                color='white',
                pad=15
            )
            ax1.tick_params(colors='white')
            ax1.yaxis.tick_right()
            ax1.yaxis.set_label_position("right")
            ax1.grid(True, alpha=ChartGenerator.GRID_ALPHA, color=ChartGenerator.GRID_COLOR)

            # График 2: RSI
            ax2.set_facecolor(ChartGenerator.BG_COLOR)
            ChartGenerator._plot_rsi(ax2, rsi_values)
            ax2.tick_params(colors='white')
            ax2.yaxis.tick_right()
            ax2.yaxis.set_label_position("right")
            ax2.set_ylabel('RSI', color='white', fontsize=10)
            ax2.grid(True, alpha=ChartGenerator.GRID_ALPHA, color=ChartGenerator.GRID_COLOR)

            # График 3: Объёмы
            ax3.set_facecolor(ChartGenerator.BG_COLOR)
            ChartGenerator._plot_volume(ax3, volumes)
            ax3.tick_params(colors='white')
            ax3.yaxis.tick_right()
            ax3.yaxis.set_label_position("right")
            ax3.set_ylabel('Volume', color='white', fontsize=10)
            ax3.grid(True, alpha=ChartGenerator.GRID_ALPHA, color=ChartGenerator.GRID_COLOR)

            # Метки времени
            ChartGenerator._add_time_labels(ax3, len(closes))

            # Сохранение
            plt.tight_layout()
            plt.savefig(
                output_path,
                dpi=ChartGenerator.DPI,
                bbox_inches='tight',
                facecolor=ChartGenerator.BG_COLOR
            )

            # ВАЖНО: Закрываем фигуру для освобождения памяти
            plt.close(fig)

            logger.info(f"✅ График создан: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"Ошибка создания графика для {symbol}: {e}", exc_info=True)

            # Закрываем все фигуры на случай ошибки
            plt.close('all')

            return ""


# === Пример использования ===
def example():
    """Пример создания тестового графика"""

    # Генерируем тестовые данные
    np.random.seed(42)
    base_price = 100

    candles = []
    for i in range(144):  # 12 часов по 5 минут
        change = np.random.normal(0, 0.5)
        base_price += change

        candle = {
            'open': base_price,
            'high': base_price + abs(np.random.normal(0, 0.3)),
            'low': base_price - abs(np.random.normal(0, 0.3)),
            'close': base_price + np.random.normal(0, 0.2),
            'volume': 1000000 + np.random.randint(-300000, 500000)
        }
        candles.append(candle)

    # Создаём график
    chart_path = ChartGenerator.generate_signal_chart(
        symbol="TEST_USDT",
        candles=candles,
        output_path="logs/test_chart.png"
    )

    if chart_path:
        logger.info(f"График создан: {chart_path}")
    else:
        logger.error("Не удалось создать график")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    example()