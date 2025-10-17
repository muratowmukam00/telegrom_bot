"""
Configuration Settings - Production Version
Централизованные настройки с валидацией
"""

import os
import logging
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Загружаем .env файл
load_dotenv()

logger = logging.getLogger(__name__)

# ============================================================================
# TELEGRAM SETTINGS
# ============================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ============================================================================
# MEXC API SETTINGS
# ============================================================================

MEXC_BASE_URL = os.getenv("MEXC_BASE_URL", "https://contract.mexc.com")
MEXC_API_TIMEOUT = int(os.getenv("MEXC_API_TIMEOUT", "30"))
MEXC_MAX_CONNECTIONS = int(os.getenv("MEXC_MAX_CONNECTIONS", "100"))

# ============================================================================
# BOT OPERATION SETTINGS
# ============================================================================

# Интервал проверки (секунды)
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "60"))

# Максимальное количество одновременных запросов
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "20"))

# Запросов в секунду (rate limiting)
REQUESTS_PER_SECOND = float(os.getenv("REQUESTS_PER_SECOND", "15"))

# ============================================================================
# TRADING FILTERS
# ============================================================================

# Фильтр 1: Изменение цены (%)
PRICE_CHANGE_THRESHOLD = float(os.getenv("PRICE_CHANGE_THRESHOLD", "8"))

# Период проверки цены (минуты)
PRICE_CHECK_PERIOD_MINUTES = int(os.getenv("PRICE_CHECK_PERIOD_MINUTES", "15"))

# Фильтр 2 и 3: RSI настройки
RSI_PERIOD = int(os.getenv("RSI_PERIOD", "14"))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", "70"))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", "30"))

# ============================================================================
# SIGNAL SETTINGS
# ============================================================================

# Cooldown между сигналами одной пары (секунды)
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", "300"))

# Минимальное количество сигналов за цикл
MIN_SIGNALS_PER_CYCLE = int(os.getenv("MIN_SIGNALS_PER_CYCLE", "1"))

# Отправлять графики?
SEND_CHART = os.getenv("SEND_CHART", "true").lower() == "true"

# Отправлять детальный анализ?
SEND_DETAILED_ANALYSIS = os.getenv("SEND_DETAILED_ANALYSIS", "true").lower() == "true"

# ============================================================================
# CACHING SETTINGS
# ============================================================================

# Длительность кэша (часы)
CACHE_DURATION_HOURS = int(os.getenv("CACHE_DURATION_HOURS", "24"))

# Директория кэша
CACHE_DIR = Path(os.getenv("CACHE_DIR", "logs"))

# ============================================================================
# LOGGING SETTINGS
# ============================================================================

# Уровень логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Файл логов
LOG_FILE = Path(os.getenv("LOG_FILE", "logs/bot.log"))

# Максимальный размер файла логов (байты)
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", "10485760"))  # 10MB

# Количество backup файлов
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", "5"))

# ============================================================================
# FILTERING SETTINGS
# ============================================================================

# Whitelist пар (если пусто - все USDT)
_whitelist = os.getenv("TRADING_PAIRS_WHITELIST", "")
TRADING_PAIRS_WHITELIST: List[str] = (
    [p.strip() for p in _whitelist.split(",") if p.strip()]
    if _whitelist
    else []
)

# Blacklist пар
_blacklist = os.getenv("TRADING_PAIRS_BLACKLIST", "")
TRADING_PAIRS_BLACKLIST: List[str] = (
    [p.strip() for p in _blacklist.split(",") if p.strip()]
    if _blacklist
    else []
)

# ============================================================================
# HEALTH CHECK SETTINGS
# ============================================================================

# Интервал health check (секунды)
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "3600"))  # 1 час

# ============================================================================
# OPTIONAL FEATURES
# ============================================================================

# База данных (для будущего функционала)
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///signals.db")

# Discord уведомления (опционально)
USE_DISCORD = os.getenv("USE_DISCORD", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


# ============================================================================
# VALIDATION
# ============================================================================

class ConfigValidationError(Exception):
    """Ошибка валидации конфигурации"""
    pass


def validate_settings() -> bool:
    """
    Проверить критичные настройки

    Returns:
        True если все настройки корректны

    Raises:
        ConfigValidationError: При обнаружении критических ошибок
    """
    errors = []
    warnings = []

    # === Критичные настройки ===

    # Telegram
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        errors.append("TELEGRAM_BOT_TOKEN не установлен в .env")

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        errors.append("TELEGRAM_CHAT_ID не установлен в .env")

    # Интервалы
    if CHECK_INTERVAL < 10:
        errors.append("CHECK_INTERVAL должен быть >= 10 секунд")

    if SIGNAL_COOLDOWN < 60:
        warnings.append("SIGNAL_COOLDOWN < 60 секунд может вызвать спам")

    # Пороги
    if PRICE_CHANGE_THRESHOLD <= 0:
        errors.append("PRICE_CHANGE_THRESHOLD должен быть > 0")

    if PRICE_CHANGE_THRESHOLD < 5:
        warnings.append("PRICE_CHANGE_THRESHOLD < 5% может дать много ложных сигналов")

    # RSI
    if RSI_OVERBOUGHT <= RSI_OVERSOLD:
        errors.append("RSI_OVERBOUGHT должен быть > RSI_OVERSOLD")

    if RSI_PERIOD < 2:
        errors.append("RSI_PERIOD должен быть >= 2")

    # Таймауты
    if MEXC_API_TIMEOUT < 5:
        warnings.append("MEXC_API_TIMEOUT < 5 секунд может вызвать таймауты")

    # Rate limiting
    if REQUESTS_PER_SECOND > 20:
        warnings.append("REQUESTS_PER_SECOND > 20 может вызвать rate limit от MEXC")

    # === Логирование результатов ===

    if errors:
        for error in errors:
            logger.error(f"❌ {error}")
        raise ConfigValidationError(
            f"Найдено {len(errors)} критических ошибок в настройках"
        )

    if warnings:
        for warning in warnings:
            logger.warning(f"⚠️  {warning}")

    logger.info("✅ Все критичные настройки корректны")

    if warnings:
        logger.info(f"ℹ️  Найдено {len(warnings)} предупреждений (не критично)")

    return True


def log_settings_summary():
    """Логировать сводку текущих настроек"""
    logger.info("=" * 70)
    logger.info("📋 КОНФИГУРАЦИЯ БОТА")
    logger.info("=" * 70)

    # Безопасно отображаем токен
    token_display = (
        f"{TELEGRAM_BOT_TOKEN[:10]}...{TELEGRAM_BOT_TOKEN[-4:]}"
        if TELEGRAM_BOT_TOKEN and len(TELEGRAM_BOT_TOKEN) > 14
        else "не установлен"
    )

    logger.info(f"Telegram Bot Token: {token_display}")
    logger.info(f"Telegram Chat ID: {TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else 'не установлен'}")
    logger.info("")

    logger.info(f"MEXC Base URL: {MEXC_BASE_URL}")
    logger.info(f"API Timeout: {MEXC_API_TIMEOUT}s")
    logger.info(f"Max Connections: {MEXC_MAX_CONNECTIONS}")
    logger.info("")

    logger.info(f"Check Interval: {CHECK_INTERVAL}s")
    logger.info(f"Signal Cooldown: {SIGNAL_COOLDOWN}s")
    logger.info("")

    logger.info(f"Price Threshold: {PRICE_CHANGE_THRESHOLD}%")
    logger.info(f"RSI Settings: Period={RSI_PERIOD}, OB={RSI_OVERBOUGHT}, OS={RSI_OVERSOLD}")
    logger.info("")

    logger.info(f"Send Charts: {'✓' if SEND_CHART else '✗'}")
    logger.info(f"Send Detailed Analysis: {'✓' if SEND_DETAILED_ANALYSIS else '✗'}")
    logger.info("")

    logger.info(f"Log Level: {LOG_LEVEL}")
    logger.info(f"Log File: {LOG_FILE}")
    logger.info("")

    if TRADING_PAIRS_WHITELIST:
        logger.info(f"Whitelist: {len(TRADING_PAIRS_WHITELIST)} пар")

    if TRADING_PAIRS_BLACKLIST:
        logger.info(f"Blacklist: {len(TRADING_PAIRS_BLACKLIST)} пар")

    logger.info("=" * 70)


# ============================================================================
# INITIALIZATION
# ============================================================================

# Создаём необходимые директории
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
Path("charts").mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)

# ============================================================================
# MAIN (для тестирования)
# ============================================================================

if __name__ == "__main__":
    # Настраиваем базовое логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

    try:
        # Валидируем настройки
        validate_settings()

        # Показываем сводку
        log_settings_summary()

        logger.info("\n✅ Конфигурация готова для production!")

    except ConfigValidationError as e:
        logger.error(f"\n❌ ОШИБКА КОНФИГУРАЦИИ: {e}")
        logger.error("Исправьте ошибки в .env файле перед запуском бота")
        exit(1)

    except Exception as e:
        logger.error(f"\n❌ Неожиданная ошибка: {e}", exc_info=True)
        exit(1)