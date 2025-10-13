#!/bin/bash

echo "🚀 Инициализация MEXC Signal Bot..."

# Проверяем Python версию
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✅ Python версия: $python_version"

# Создаём виртуальное окружение если его нет
if [ ! -d "venv" ]; then
    echo "📦 Создание виртуального окружения..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
fi

# Активируем окружение
source venv/bin/activate

# Устанавливаем зависимости
echo "📥 Установка зависимостей..."
if command -v poetry &> /dev/null; then
    poetry install
else
    pip install -r requirements.txt
fi

# Создаём необходимые папки
mkdir -p logs
mkdir -p screenshots

# Создаём .env если его нет
if [ ! -f ".env" ]; then
    echo "⚠️  Создание .env файла..."
    cp .env.example .env 2>/dev/null || cat > .env << 'ENVEOF'
# Telegram Bot
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE

# MEXC API (публичный)
MEXC_BASE_URL=https://contract.mexc.com

# Bot Settings
CHECK_INTERVAL=60
PRICE_CHANGE_THRESHOLD=8

# RSI Settings
RSI_PERIOD=14
RSI_OVERBOUGHT=70
RSI_OVERSOLD=30

# Logging
LOG_LEVEL=INFO
ENVEOF
    echo "⚠️  ВАЖНО: Отредактируйте .env и добавьте ваши токены!"
    echo "   nano .env"
fi

echo "✅ Инициализация завершена!"
echo ""
echo "📋 Следующие шаги:"
echo "1. Отредактируйте .env: nano .env"
echo "2. Добавьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID"
echo "3. Запустите бота: python main.py"
echo ""
