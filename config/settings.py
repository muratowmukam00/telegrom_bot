import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ===== TELEGRAM =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ===== MEXC API =====
MEXC_BASE_URL = os.getenv("MEXC_BASE_URL", "https://contract.mexc.com")
MEXC_API_TIMEOUT = int(os.getenv("MEXC_API_TIMEOUT", 10))

# ===== BOT SETTINGS =====
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", 20))
REQUESTS_PER_SECOND = float(os.getenv("REQUESTS_PER_SECOND", 15))

# ===== PRICE FILTER =====
PRICE_CHANGE_THRESHOLD = float(os.getenv("PRICE_CHANGE_THRESHOLD", 8))  # %
PRICE_CHECK_PERIOD_MINUTES = int(os.getenv("PRICE_CHECK_PERIOD_MINUTES", 15))

# ===== RSI SETTINGS =====
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", 70))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", 30))

# ===== SIGNAL SETTINGS =====
SIGNAL_COOLDOWN = int(os.getenv("SIGNAL_COOLDOWN", 300))  # 5 минут между сигналами одной пары
MIN_SIGNALS_PER_CYCLE = int(os.getenv("MIN_SIGNALS_PER_CYCLE", 1))

# ===== CACHING =====
CACHE_DURATION_HOURS = int(os.getenv("CACHE_DURATION_HOURS", 24))
CACHE_DIR = Path(os.getenv("CACHE_DIR", "logs"))

# ===== LOGGING =====
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = Path(os.getenv("LOG_FILE", "logs/bot.log"))
LOG_MAX_BYTES = int(os.getenv("LOG_MAX_BYTES", 10485760))  # 10MB
LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 5))

# ===== DATABASE (опционально для будущей функциональности) =====
USE_DATABASE = os.getenv("USE_DATABASE", "false").lower() == "true"
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///signals.db")

# ===== DISCORD NOTIFICATIONS (опционально) =====
USE_DISCORD = os.getenv("USE_DISCORD", "false").lower() == "true"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

# ===== NOTIFCATION SETTINGS =====
SEND_CHART = os.getenv("SEND_CHART", "true").lower() == "true"
SEND_DETAILED_ANALYSIS = os.getenv("SEND_DETAILED_ANALYSIS", "true").lower() == "true"

# ===== FILTERING =====
# Какие пары мониторить (если пусто - все USDT пары)
TRADING_PAIRS_WHITELIST = os.getenv("TRADING_PAIRS_WHITELIST", "").split(",") if os.getenv(
    "TRADING_PAIRS_WHITELIST") else []
TRADING_PAIRS_BLACKLIST = os.getenv("TRADING_PAIRS_BLACKLIST", "").split(",") if os.getenv(
    "TRADING_PAIRS_BLACKLIST") else []

# ===== HEALTH CHECK =====
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", 3600))  # каждый час


# ===== VALIDATION =====
def validate_settings():
    """Проверить критичные настройки"""
    errors = []

    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        errors.append("TELEGRAM_BOT_TOKEN не установлен в .env")

    if not TELEGRAM_CHAT_ID or TELEGRAM_CHAT_ID == "YOUR_CHAT_ID_HERE":
        errors.append("TELEGRAM_CHAT_ID не установлен в .env")

    if CHECK_INTERVAL < 10:
        errors.append("CHECK_INTERVAL должен быть >= 10 секунд")

    if PRICE_CHANGE_THRESHOLD <= 0:
        errors.append("PRICE_CHANGE_THRESHOLD должен быть > 0")

    if RSI_OVERBOUGHT <= RSI_OVERSOLD:
        errors.append("RSI_OVERBOUGHT должен быть > RSI_OVERSOLD")

    if errors:
        for error in errors:
            print(f"❌ {error}")
        return False

    return True


# Создаём директории если нужно
CACHE_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

if __name__ == "__main__":
    print("=" * 60)
    print("📋 ТЕКУЩИЕ НАСТРОЙКИ")
    print("=" * 60)
    print(f"Bot Token: {'✓ установлен' if TELEGRAM_BOT_TOKEN else '✗ не установлен'}")
    print(f"Chat ID: {TELEGRAM_CHAT_ID if TELEGRAM_CHAT_ID else '✗ не установлен'}")
    print(f"Check Interval: {CHECK_INTERVAL}s")
    print(f"Price Threshold: {PRICE_CHANGE_THRESHOLD}%")
    print(f"RSI Settings: Period={RSI_PERIOD}, OB={RSI_OVERBOUGHT}, OS={RSI_OVERSOLD}")
    print(f"Max Concurrent: {MAX_CONCURRENT_REQUESTS}")
    print(f"Log Level: {LOG_LEVEL}")
    print("=" * 60)

    if validate_settings():
        print("✅ ВСЕ НАСТРОЙКИ КОРРЕКТНЫ")
    else:
        print("❌ ЕСТЬ ОШИБКИ В НАСТРОЙКАХ")