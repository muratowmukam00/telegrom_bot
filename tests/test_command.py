# import pytest
# from bot.handlers.commands import start, help_command  # Предполагаемые функции
#
# @pytest.mark.asyncio
# async def test_start_command():
#     from aiogram.types import Message
#     from unittest.mock import AsyncMock
#
#     message = AsyncMock(spec=Message)
#     message.chat.id = 12345
#     message.text = "/start"
#
#     await start(message)
#     message.answer.assert_called_with("Welcome to MEXC Signal Bot!")  # Замените на реальный текст
#
# @pytest.mark.asyncio
# async def test_help_command():
#     message = AsyncMock(spec=Message)
#     message.chat.id = 12345
#     message.text = "/help"
#
#     await help_command(message)
#     message.answer.assert_called_with("Available commands:\n/start - Start the bot\n/help - Show this help")  # Замените на реальный текст