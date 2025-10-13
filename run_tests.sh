#!/bin/bash

echo "🧪 Запуск тестов MEXC Signal Bot..."
echo ""

# Активируем виртуальное окружение если оно есть
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Запускаем тесты
pytest tests/ --cov=bot --cov=services --cov=config --cov-report=term-missing -v

echo ""
echo "✅ Тестирование завершено!"
