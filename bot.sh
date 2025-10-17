#!/bin/bash
# ============================================================================
# MEXC Signal Bot - Management Script
# Скрипт для управления ботом на сервере
# ============================================================================

set -e

# Цвета
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Настройки
SERVICE_NAME="mexc-bot"
BOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$BOT_DIR/.venv"
PYTHON="$VENV_PATH/bin/python"
LOG_FILE="$BOT_DIR/logs/bot.log"

# Функции вывода
print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_header() {
    echo -e "\n${BLUE}═══════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════${NC}\n"
}

# Проверка systemd
check_systemd() {
    if ! systemctl --user list-units | grep -q "$SERVICE_NAME"; then
        return 1
    fi
    return 0
}

# Функция: Статус
status() {
    print_header "📊 СТАТУС БОТА"
    
    if check_systemd; then
        systemctl --user status "$SERVICE_NAME" --no-pager || true
    else
        print_warning "Systemd service не установлен"
        print_info "Используйте: ./bot.sh install"
    fi
}

# Функция: Запуск
start() {
    print_header "🚀 ЗАПУСК БОТА"
    
    if check_systemd; then
        systemctl --user start "$SERVICE_NAME"
        sleep 2
        if systemctl --user is-active --quiet "$SERVICE_NAME"; then
            print_success "Бот запущен!"
            print_info "Проверьте логи: ./bot.sh logs"
        else
            print_error "Ошибка запуска!"
            print_info "Смотрите ошибки: ./bot.sh logs"
        fi
    else
        print_info "Запуск в режиме разработки..."
        cd "$BOT_DIR"
        "$PYTHON" run_hybrid.py
    fi
}

# Функция: Остановка
stop() {
    print_header "🛑 ОСТАНОВКА БОТА"
    
    if check_systemd; then
        systemctl --user stop "$SERVICE_NAME"
        sleep 1
        print_success "Бот остановлен!"
    else
        print_warning "Systemd service не установлен"
        print_info "Остановите процесс вручную (Ctrl+C)"
    fi
}

# Функция: Перезапуск
restart() {
    print_header "🔄 ПЕРЕЗАПУСК БОТА"
    
    if check_systemd; then
        systemctl --user restart "$SERVICE_NAME"
        sleep 2
        if systemctl --user is-active --quiet "$SERVICE_NAME"; then
            print_success "Бот перезапущен!"
        else
            print_error "Ошибка перезапуска!"
        fi
    else
        print_error "Systemd service не установлен"
    fi
}

# Функция: Логи
logs() {
    print_header "📄 ЛОГИ БОТА"
    
    if check_systemd; then
        print_info "Логи systemd (последние 50 строк):"
        echo ""
        journalctl --user -u "$SERVICE_NAME" -n 50 --no-pager
        echo ""
        print_info "Для live логов: journalctl --user -u $SERVICE_NAME -f"
    else
        if [ -f "$LOG_FILE" ]; then
            print_info "Логи файла (последние 50 строк):"
            echo ""
            tail -n 50 "$LOG_FILE"
        else
            print_warning "Файл логов не найден: $LOG_FILE"
        fi
    fi
}

# Функция: Live логи
logs_live() {
    print_header "📡 LIVE ЛОГИ"
    
    if check_systemd; then
        print_info "Нажмите Ctrl+C для выхода"
        echo ""
        journalctl --user -u "$SERVICE_NAME" -f
    else
        if [ -f "$LOG_FILE" ]; then
            print_info "Нажмите Ctrl+C для выхода"
            echo ""
            tail -f "$LOG_FILE"
        else
            print_error "Файл логов не найден"
        fi
    fi
}

# Функция: Установка systemd service
install() {
    print_header "📦 УСТАНОВКА SYSTEMD SERVICE"
    
    # Проверка .env
    if [ ! -f "$BOT_DIR/.env" ]; then
        print_error ".env файл не найден!"
        print_info "Скопируйте .env.example в .env и заполните настройки"
        exit 1
    fi
    
    # Проверка виртуального окружения
    if [ ! -d "$VENV_PATH" ]; then
        print_error "Виртуальное окружение не найдено!"
        print_info "Установите зависимости: poetry install"
        exit 1
    fi
    
    # Создание systemd service файла
    SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"
    mkdir -p "$HOME/.config/systemd/user"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=MEXC Signal Bot - Crypto Trading Signals
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BOT_DIR
Environment="PATH=$VENV_PATH/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=$PYTHON $BOT_DIR/run_hybrid.py

# Автоматический перезапуск
Restart=always
RestartSec=10

# Ограничения ресурсов
MemoryMax=2G
CPUQuota=80%

# Логирование
StandardOutput=journal
StandardError=journal
SyslogIdentifier=mexc-bot

# Security
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=default.target
EOF
    
    print_success "Service файл создан: $SERVICE_FILE"
    
    # Перезагрузка systemd
    systemctl --user daemon-reload
    print_success "Systemd daemon перезагружен"
    
    # Включение автозапуска
    systemctl --user enable "$SERVICE_NAME"
    print_success "Автозапуск включён"
    
    echo ""
    print_success "Установка завершена!"
    print_info "Запустите бота: ./bot.sh start"
}

# Функция: Удаление service
uninstall() {
    print_header "🗑️  УДАЛЕНИЕ SYSTEMD SERVICE"
    
    # Остановка
    if check_systemd; then
        systemctl --user stop "$SERVICE_NAME" 2>/dev/null || true
        systemctl --user disable "$SERVICE_NAME" 2>/dev/null || true
    fi
    
    # Удаление файла
    SERVICE_FILE="$HOME/.config/systemd/user/$SERVICE_NAME.service"
    if [ -f "$SERVICE_FILE" ]; then
        rm -f "$SERVICE_FILE"
        systemctl --user daemon-reload
        print_success "Service удалён"
    else
        print_warning "Service файл не найден"
    fi
}

# Функция: Проверка конфигурации
check() {
    print_header "🔍 ПРОВЕРКА КОНФИГУРАЦИИ"
    
    cd "$BOT_DIR"
    
    # Проверка Python
    if [ -f "$PYTHON" ]; then
        print_success "Python: $($PYTHON --version)"
    else
        print_error "Python не найден в venv!"
        exit 1
    fi
    
    # Проверка .env
    if [ -f ".env" ]; then
        print_success ".env файл найден"
    else
        print_error ".env файл не найден!"
        exit 1
    fi
    
    # Проверка конфигурации
    print_info "Проверка настроек..."
    "$PYTHON" config/settings.py
    
    echo ""
    print_success "Все проверки пройдены!"
}

# Функция: Обновление символов
update_symbols() {
    print_header "🔄 ОБНОВЛЕНИЕ СПИСКА СИМВОЛОВ"
    
    cd "$BOT_DIR"
    "$PYTHON" tools/update_symbols.py
    
    if [ -f "data/symbols_usdt.txt" ]; then
        SYMBOLS_COUNT=$(wc -l < data/symbols_usdt.txt)
        print_success "Обновлено $SYMBOLS_COUNT USDT пар"
    fi
}

# Функция: Помощь
help() {
    cat << EOF

${BLUE}MEXC Signal Bot - Management Script${NC}

${YELLOW}Использование:${NC}
    ./bot.sh [command]

${YELLOW}Команды:${NC}
    ${GREEN}start${NC}           Запустить бота
    ${GREEN}stop${NC}            Остановить бота
    ${GREEN}restart${NC}         Перезапустить бота
    ${GREEN}status${NC}          Показать статус
    ${GREEN}logs${NC}            Показать последние логи
    ${GREEN}logs-live${NC}       Live логи (Ctrl+C для выхода)
    
    ${GREEN}install${NC}         Установить systemd service
    ${GREEN}uninstall${NC}       Удалить systemd service
    
    ${GREEN}check${NC}           Проверить конфигурацию
    ${GREEN}update-symbols${NC}  Обновить список USDT пар
    
    ${GREEN}help${NC}            Показать эту справку

${YELLOW}Примеры:${NC}
    ./bot.sh start              # Запустить бота
    ./bot.sh logs-live          # Смотреть live логи
    ./bot.sh check              # Проверить настройки

${YELLOW}Логи:${NC}
    Systemd: journalctl --user -u mexc-bot -f
    Файл: tail -f logs/bot.log

EOF
}

# ============================================================================
# MAIN
# ============================================================================

case "${1:-help}" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        restart
        ;;
    status)
        status
        ;;
    logs)
        logs
        ;;
    logs-live|live)
        logs_live
        ;;
    install)
        install
        ;;
    uninstall)
        uninstall
        ;;
    check)
        check
        ;;
    update-symbols)
        update_symbols
        ;;
    help|--help|-h)
        help
        ;;
    *)
        print_error "Неизвестная команда: $1"
        echo ""
        help
        exit 1
        ;;
esac
