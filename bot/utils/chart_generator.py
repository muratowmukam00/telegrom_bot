import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime
from typing import List, Tuple
import numpy as np
from services.analysis.rsi import RSICalculator

class ChartGenerator:
    """Генерация графиков для сигналов"""
    
    @staticmethod
    def generate_signal_chart(
        symbol: str,
        prices_5m: List[float],
        volumes_5m: List[float],
        output_path: str = "signal_chart.png"
    ) -> str:
        """
        Генерировать график сигнала (5m, последние 12 часов)
        
        Args:
            symbol: Название символа
            prices_5m: Цены (close) за 5 минут
            volumes_5m: Объёмы за 5 минут
            output_path: Путь для сохранения
        
        Returns:
            Путь к сохранённому файлу
        """
        try:
            # Рассчитываем RSI
            rsi_values = RSICalculator.calculate(prices_5m, period=14)
            
            # Создаём фигуру с 3 субграфиками
            fig, (ax1, ax2, ax3) = plt.subplots(
                3, 1,
                figsize=(14, 10),
                gridspec_kw={'height_ratios': [3, 1, 1]}
            )
            
            # График 1: Цена
            x = np.arange(len(prices_5m))
            ax1.plot(x, prices_5m, color='#1f77b4', linewidth=2, label='Close Price')
            ax1.set_title(f'{symbol} - 5m Chart (Last 12h)', fontsize=14, fontweight='bold')
            ax1.set_ylabel('Price', fontsize=10)
            ax1.grid(True, alpha=0.3)
            ax1.legend()
            
            # График 2: Объём с средней линией
            avg_volume = np.mean(sorted(volumes_5m)[-5:])  # Средний объём 5 больших свечей
            bars = ax2.bar(x, volumes_5m, color='#2ca02c', alpha=0.7, label='Volume')
            ax2.axhline(y=avg_volume, color='red', linestyle='--', linewidth=2, label=f'Avg Volume (Top 5)')
            ax2.set_ylabel('Volume', fontsize=10)
            ax2.grid(True, alpha=0.3, axis='y')
            ax2.legend()
            
            # График 3: RSI
            rsi_x = np.arange(len(rsi_values))
            ax3.plot(rsi_x, rsi_values, color='#ff7f0e', linewidth=2, label='RSI(14)')
            ax3.axhline(y=70, color='red', linestyle='--', linewidth=1, alpha=0.7, label='Overbought (70)')
            ax3.axhline(y=30, color='green', linestyle='--', linewidth=1, alpha=0.7, label='Oversold (30)')
            ax3.fill_between(rsi_x, 70, 100, alpha=0.1, color='red')
            ax3.fill_between(rsi_x, 0, 30, alpha=0.1, color='green')
            ax3.set_ylabel('RSI', fontsize=10)
            ax3.set_xlabel('Time (5m candles)', fontsize=10)
            ax3.set_ylim(0, 100)
            ax3.grid(True, alpha=0.3)
            ax3.legend()
            
            plt.tight_layout()
            plt.savefig(output_path, dpi=100, bbox_inches='tight')
            plt.close()
            
            return output_path
        except Exception as e:
            print(f"Error generating chart: {e}")
            return ""
