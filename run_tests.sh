#!/bin/bash

echo "🧪 Запуск тестов MEXC Signal Bot..."
echo ""

# Активируем виртуальное окружение если оно есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Запускаем тесты
python test_bot.py

echo ""
echo "✅ Тестирование завершено!"
