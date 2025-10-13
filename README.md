# MEXC Signal Bot 🤖

Telegram бот для мониторинга фьючерсов MEXC и отправки торговых сигналов.

## 📋 Особенности

- ✅ Мониторинг всех USDT фьючерс пар на MEXC
- ✅ 3-уровневый фильтр сигналов
- ✅ Автоматические уведомления в Telegram
- ✅ Графики с анализом (цена, объём, RSI)
- ✅ Публичный API (без необходимости в приватных ключах)

## 🎯 Фильтры сигналов

1. **Фильтр 1**: Изменение цены >= 8% за последние 15 минут
2. **Фильтр 2**: RSI 1h > 70 или < 30 (период 14)
3. **Фильтр 3**: RSI 15m > 70 или < 30 (период 14)

Сигнал срабатывает когда **ВСЕ 3 фильтра** выполняются одновременно.

## 🚀 Установка

### Требования
- Python 3.12+
- pip или poetry

### Быстрый старт

```bash
# Клонируем репозиторий
git clone <your-repo>
cd mexc-signal-bot

# Запускаем инициализацию
bash setup.sh

# Редактируем конфиг
nano .env

# Запускаем бота
python main.py
```

## ⚙️ Конфигурация

Отредактируйте `.env` файл:

```env
# Telegram
TELEGRAM_BOT_TOKEN=YOUR_BOT_TOKEN_HERE
TELEGRAM_CHAT_ID=YOUR_CHAT_ID_HERE

# Интервал проверки (секунды)
CHECK_INTERVAL=60

# Пороги
PRICE_CHANGE_THRESHOLD=8
RSI_PERIOD=14
RSI_OVERBOUGHT=70
RSI_OVERSOLD=30
```

### Как получить токены?

1. **Telegram Bot Token**:
   - Напишите @BotFather в Telegram
   - Команда `/newbot`
   - Скопируйте токен

2. **Chat ID**:
   - Напишите @userinfobot
   - Получите ваш Chat ID
   - Добавьте бота в чат и отправьте любое сообщение

## 📊 Структура проекта

```
mexc-signal-bot/
├── bot/
│   ├── handlers/           # Обработчики команд
│   ├── services/           # Telegram сервис
│   └── utils/              # Генератор графиков
├── services/
│   ├── mexc/               # MEXC API клиент
│   └── analysis/           # RSI и анализ сигналов
├── config/
│   └── settings.py         # Конфигурация
├── logs/                   # Логи и графики
├── main.py                 # Главный скрипт
├── requirements.txt        # Зависимости
└── .env                    # Переменные окружения
```

## 📝 Логирование

Логи сохраняются в `logs/bot.log`

```bash
# Просмотр логов в реальном времени
tail -f logs/bot.log

# Или запуск с логами в консоль
LOG_LEVEL=DEBUG python main.py
```

## 🧪 Тестирование

```bash
# Проверка конфигурации
python -c "from config.settings import *; print('✅ Config OK')"

# Тест API
python -c "from services.mexc import MexcClient; print('✅ API OK')"
```

## 📌 Команды Telegram

- `/start` - Запуск бота
- `/status` - Статус
- `/help` - Справка

## ⚠️ Важно

- Используется **публичный API** (не требуются приватные ключи)
- Лимиты API могут применяться при частых запросах
- Бот отправляет сигнал не чаще чем 1 раз в 5 минут на одну пару

## 📄 Лицензия

MIT

## 👨‍💻 Автор

muhammet

---

**Удачи в торговле! 🚀📈**
