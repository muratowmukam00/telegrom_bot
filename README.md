# 🤖 MEXC Signal Bot

Автоматический бот для мониторинга торговых сигналов на MEXC фьючерсах.

## 📋 Возможности

- ✅ **WebSocket мониторинг** — real-time обновления цен всех USDT пар
- ✅ **REST API** — проверка RSI и исторических данных
- ✅ **3 фильтра**:
  - Изменение цены ≥8% за 15 минут
  - RSI 1h > 70 или < 30
  - RSI 15m > 70 или < 30
- ✅ **Telegram уведомления** — мгновенные сигналы с графиками
- ✅ **Автоматический перезапуск** — через systemd
- ✅ **Production ready** — логи, метрики, graceful shutdown

---

## 🚀 Быстрый старт

### 1. Клонирование и установка

```bash
# Клонируем репозиторий
cd ~/2025/projects
git clone <your-repo-url> mexc_signal_bot
cd mexc_signal_bot

# Устанавливаем зависимости (Poetry)
poetry install

# Или с pip
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Настройка

```bash
# Копируем .env.example
cp .env.example .env

# Редактируем .env
nano .env
```

**Обязательные параметры:**
```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

### 3. Проверка конфигурации

```bash
# Проверяем настройки
./bot.sh check

# Должно вывести:
# ✅ Все критичные настройки корректны
# 📋 КОНФИГУРАЦИЯ БОТА
# ...
```

### 4. Обновление списка пар

```bash
# Получаем актуальный список USDT пар с MEXC
./bot.sh update-symbols

# Должно создать: data/symbols_usdt.txt
```

### 5. Запуск

```bash
# Разработка (Ctrl+C для остановки)
./bot.sh start

# Production (через systemd)
./bot.sh install    # Установить service
./bot.sh start      # Запустить
```

---

## 🎮 Команды управления

```bash
# Основные команды
./bot.sh start          # Запустить бота
./bot.sh stop           # Остановить
./bot.sh restart        # Перезапустить
./bot.sh status         # Статус

# Логи
./bot.sh logs           # Последние 50 строк
./bot.sh logs-live      # Live логи (Ctrl+C для выхода)

# Systemd
./bot.sh install        # Установить автозапуск
./bot.sh uninstall      # Удалить service

# Утилиты
./bot.sh check          # Проверить конфигурацию
./bot.sh update-symbols # Обновить список пар
./bot.sh help           # Справка
```

---

## 📁 Структура проекта

```
mexc_signal_bot/
├── bot/
│   ├── handlers/           # Telegram команды
│   ├── services/           # Telegram сервис
│   └── utils/              # Генератор графиков
├── config/
│   └── settings.py         # Настройки с валидацией
├── services/
│   ├── analysis/           # RSI и анализ сигналов
│   └── mexc/               # API и WebSocket клиенты
├── tools/
│   └── update_symbols.py   # Обновление списка пар
├── logs/                   # Логи
├── charts/                 # Графики сигналов
├── data/
│   └── symbols_usdt.txt    # Список USDT пар
├── .env                    # Настройки (не в git!)
├── run_hybrid.py           # 🚀 Основной файл запуска
├── bot.sh                  # Скрипт управления
└── cleanup.sh              # Очистка проекта
```

---

## ⚙️ Настройки (.env)

### Обязательные

```bash
# Telegram
TELEGRAM_BOT_TOKEN=123456789:ABC...     # Токен от @BotFather
TELEGRAM_CHAT_ID=-1001234567890         # ID чата для сигналов
```

### Опциональные

```bash
# Интервалы
CHECK_INTERVAL=60                       # Проверка каждые N секунд
SIGNAL_COOLDOWN=300                     # Cooldown между сигналами (5 мин)

# Фильтры
PRICE_CHANGE_THRESHOLD=8                # Минимальное изменение цены (%)
RSI_OVERBOUGHT=70                       # RSI перекупленность
RSI_OVERSOLD=30                         # RSI перепроданность

# Логирование
LOG_LEVEL=INFO                          # DEBUG, INFO, WARNING, ERROR
```

Полный список: см. `.env.example`

---

## 📊 Логи

### Просмотр логов

```bash
# Последние логи
./bot.sh logs

# Live логи
./bot.sh logs-live

# Systemd логи
journalctl --user -u mexc-bot -f
```

### Файл логов

```bash
# Основной лог
tail -f logs/bot.log

# Логи обновления символов
tail -f logs/update_symbols.log
```

---

## 🔧 Production деплой

### 1. Установка на сервер

```bash
# SSH на сервер
ssh user@server

# Клонируем и настраиваем
cd ~/projects
git clone <repo> mexc_signal_bot
cd mexc_signal_bot
poetry install
cp .env.example .env
nano .env  # настраиваем

# Проверяем
./bot.sh check
./bot.sh update-symbols
```

### 2. Установка systemd service

```bash
# Устанавливаем service
./bot.sh install

# Запускаем
./bot.sh start

# Проверяем статус
./bot.sh status
```

### 3. Автозапуск при загрузке

```bash
# Включаем автозапуск
systemctl --user enable mexc-bot

# Проверяем
systemctl --user is-enabled mexc-bot
```

### 4. Мониторинг

```bash
# Статус
./bot.sh status

# Live логи
./bot.sh logs-live

# Перезапуск при изменениях
./bot.sh restart
```

---

## 🐛 Решение проблем

### Бот не запускается

```bash
# 1. Проверяем конфигурацию
./bot.sh check

# 2. Смотрим логи
./bot.sh logs

# 3. Проверяем .env
cat .env | grep TELEGRAM
```

### Нет сигналов

```bash
# 1. Проверяем WebSocket
./bot.sh logs-live | grep "WS"

# 2. Проверяем список пар
./bot.sh update-symbols
cat data/symbols_usdt.txt | wc -l

# 3. Проверяем фильтры
# Может быть слишком строгие (PRICE_CHANGE_THRESHOLD=8)
```

### Высокое использование памяти

```bash
# Перезапускаем бота раз в день
crontab -e
# Добавляем:
0 3 * * * systemctl --user restart mexc-bot
```

---

## 📈 Метрики

Бот собирает метрики:

- **API запросы**: total, successful, failed, success rate
- **WebSocket**: connections, reconnections, messages
- **Telegram**: messages sent, photos, retries, rate limits
- **Сигналы**: найдено, отправлено, cooldown hits

Метрики логируются каждые 5 минут.

---

## 🔐 Безопасность

- ✅ `.env` не в git (в `.gitignore`)
- ✅ Systemd security: `NoNewPrivileges=true`, `PrivateTmp=true`
- ✅ Ограничения ресурсов: 2GB RAM, 80% CPU
- ✅ Логи не содержат токены

---

## 🆘 Поддержка

### Проблемы с ботом

1. Проверьте логи: `./bot.sh logs`
2. Проверьте конфигурацию: `./bot.sh check`
3. Перезапустите: `./bot.sh restart`

### Telegram бот не отвечает

```bash
# Проверяем токен
curl https://api.telegram.org/bot<YOUR_TOKEN>/getMe
```

### MEXC API проблемы

```bash
# Проверяем доступность
curl https://contract.mexc.com/api/v1/contract/ping
```

---

## 📝 Changelog

### v2.0.0 (Production Ready)
- ✅ Production logging
- ✅ Graceful shutdown
- ✅ Метрики подключений
- ✅ Systemd integration
- ✅ Management скрипт

### v1.0.0 (Initial)
- ✅ WebSocket + REST API
- ✅ 3 фильтра сигналов
- ✅ Telegram уведомления
- ✅ График генератор

---

## 📄 Лицензия

MIT License

---

## 👨‍💻 Автор

Created by @muratowmukam00

**Запуск:** `./bot.sh start`
**Помощь:** `./bot.sh help`
