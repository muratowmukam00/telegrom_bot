import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# MEXC API
MEXC_API_KEY = os.getenv("MEXC_API_KEY")
MEXC_API_SECRET = os.getenv("MEXC_API_SECRET")
MEXC_BASE_URL = "https://contract.mexc.com"

# Bot Settings
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", 60))
PRICE_CHANGE_THRESHOLD = float(os.getenv("PRICE_CHANGE_THRESHOLD", 8))

# RSI Settings
RSI_PERIOD = int(os.getenv("RSI_PERIOD", 14))
RSI_OVERBOUGHT = int(os.getenv("RSI_OVERBOUGHT", 70))
RSI_OVERSOLD = int(os.getenv("RSI_OVERSOLD", 30))

# Logging
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
