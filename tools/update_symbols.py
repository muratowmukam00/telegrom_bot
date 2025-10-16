#!/usr/bin/env python3
# tools/update_symbols.py
import aiohttp
import asyncio
import logging
from pathlib import Path
from datetime import datetime

# === Настройки ===
MEXC_URL = "https://contract.mexc.com/api/v1/contract/detail"
SAVE_PATH = Path("data/symbols_usdt.txt")
LOG_PATH = Path("logs/update_symbols.log")

# === Логирование ===
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# === Основная функция ===
async def update_symbols():
    logger.info("🔄 Начало обновления списка USDT-пар MEXC...")
    print("🔄 Обновление списка USDT-пар MEXC...")

    try:
        async with aiohttp.ClientSession(
            headers={"User-Agent": "Mozilla/5.0 (compatible; MexcUpdater/1.0)"}
        ) as session:
            async with session.get(MEXC_URL, timeout=30) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error(f"Ошибка HTTP {resp.status}: {text}")
                    print(f"❌ Ошибка HTTP {resp.status}")
                    return

                data = await resp.json()
                if not data.get("success"):
                    logger.error(f"Ошибка ответа API: {data}")
                    print("❌ Ошибка в ответе API")
                    return

                contracts = data.get("data", [])
                usdt_pairs = sorted([
                    c["symbol"] for c in contracts if c["symbol"].endswith("_USDT")
                ])

                if not usdt_pairs:
                    logger.warning("⚠️ Не найдено ни одной USDT пары!")
                    print("⚠️ Не найдено ни одной USDT пары!")
                    return

                SAVE_PATH.parent.mkdir(parents=True, exist_ok=True)
                SAVE_PATH.write_text("\n".join(usdt_pairs))
                logger.info(f"✅ Обновлено {len(usdt_pairs)} USDT пар → {SAVE_PATH}")
                print(f"✅ Обновлено {len(usdt_pairs)} USDT пар → {SAVE_PATH}")

    except asyncio.TimeoutError:
        logger.error("⏰ Таймаут запроса к API MEXC")
        print("⏰ Таймаут запроса к API MEXC")
    except Exception as e:
        logger.exception(f"Ошибка обновления списка пар: {e}")
        print(f"❌ Ошибка обновления списка пар: {e}")

# === Точка входа ===
if __name__ == "__main__":
    start = datetime.now()
    asyncio.run(update_symbols())
    duration = (datetime.now() - start).total_seconds()
    print(f"🏁 Завершено за {duration:.2f} сек.")
    logger.info(f"🏁 Завершено за {duration:.2f} сек.")
