from aiogram import Router, types
from aiogram.filters import Command
import logging
from datetime import datetime

router = Router(name="commands")
logger = logging.getLogger(__name__)

start_time = datetime.now()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    logger.info(f"/start от пользователя {message.from_user.id} ({message.from_user.username})")
    await message.answer(
        "👋 <b>Добро пожаловать в MEXC Signal Bot v1.0.0!</b>\n\n"
        "Бот мониторит фьючерсы MEXC и отправляет сигналы, когда все фильтры совпадают.\n\n"
        "<b>Фильтры:</b>\n"
        "1️⃣ Изменение цены ≥ 8% за 15 минут\n"
        "2️⃣ RSI 1h > 70 или < 30\n"
        "3️⃣ RSI 15m > 70 или < 30\n\n"
        "🤖 Бот активен и работает.",
        parse_mode="HTML"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    logger.info(f"/help от пользователя {message.from_user.id}")
    await message.answer(
        "<b>📚 Справка по командам:</b>\n\n"
        "/start — запуск бота\n"
        "/status — проверить состояние\n"
        "/help — справка\n"
        "/about — информация о версии",
        parse_mode="HTML"
    )

@router.message(Command("status"))
async def cmd_status(message: types.Message):
    uptime = datetime.now() - start_time
    await message.answer(
        f"✅ <b>Статус: РАБОТАЕТ</b>\n\n"
        f"⏱ Аптайм: <code>{uptime}</code>\n"
        "🔄 Мониторинг: Активен\n"
        "📊 Проверка: Каждую минуту\n"
        "🎯 Фильтры: Все активны",
        parse_mode="HTML"
    )

@router.message(Command("about"))
async def cmd_about(message: types.Message):
    await message.answer(
        "🤖 <b>MEXC Signal Bot</b>\n"
        "Версия: <code>1.0.0</code>\n"
        "Автор: <b>@muhammet</b>\n"
        "Назначение: мониторинг сигналов фьючерсов MEXC.",
        parse_mode="HTML"
    )
