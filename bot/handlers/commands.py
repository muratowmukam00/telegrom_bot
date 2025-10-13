from aiogram import Router, types
from aiogram.filters import Command

router = Router()

@router.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    await message.answer(
        "👋 <b>Добро пожаловать в MEXC Signal Bot!</b>\n\n"
        "Бот мониторит фьючерсы MEXC и отправляет сигналы когда все условия выполнены.\n\n"
        "<b>Фильтры:</b>\n"
        "1️⃣ Изменение цены >= 8% за 15 минут\n"
        "2️⃣ RSI 1h > 70 или < 30\n"
        "3️⃣ RSI 15m > 70 или < 30\n\n"
        "🤖 Бот запущен и работает...",
        parse_mode="HTML"
    )

@router.message(Command("help"))
async def cmd_help(message: types.Message):
    """Команда /help"""
    await message.answer(
        "<b>📚 Справка:</b>\n\n"
        "/start - Начало работы\n"
        "/status - Статус бота\n"
        "/help - Эта справка\n\n"
        "Бот автоматически мониторит все USDT пары и отправляет сигналы.",
        parse_mode="HTML"
    )

@router.message(Command("status"))
async def cmd_status(message: types.Message):
    """Команда /status"""
    await message.answer(
        "✅ <b>Статус: РАБОТАЕТ</b>\n\n"
        "🔄 Мониторинг: Активен\n"
        "📊 Проверка: Каждую минуту\n"
        "🎯 Фильтры: Все активны",
        parse_mode="HTML"
    )
