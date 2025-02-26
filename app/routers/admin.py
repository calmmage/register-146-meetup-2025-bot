from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from botspot.user_interactions import ask_user, ask_user_choice
from botspot.commands_menu import add_command
from botspot.utils import reply_safe

router = Router()

@add_command("error_test", "Test error handling", visibility="hidden")
@router.message(Command("error_test"))
async def error_test(message: Message) -> None:
    """Demonstrate error handling"""
    raise ValueError("This is a test error!")
