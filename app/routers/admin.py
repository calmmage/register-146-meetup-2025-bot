from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
import asyncio
import os
from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    ReplyKeyboardRemove,
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from dotenv import load_dotenv
from loguru import logger
from textwrap import dedent
from typing import Dict, List

from app.app import App, TargetCity, RegisteredUser
from botspot import commands_menu
from botspot.user_interactions import ask_user, ask_user_choice, ask_user_raw
from botspot.utils import send_safe, is_admin
from botspot.utils.admin_filter import AdminFilter
from botspot.commands_menu import add_command

router = Router()


async def admin_handler(message: Message, state: FSMContext):
    # Show admin options
    response = await ask_user_choice(
        message.chat.id,
        "Вы администратор бота. Что вы хотите сделать?",
        choices={
            "register": "Зарегистрироваться на встречу",
            "export": "Экспортировать данные",
            "view_stats": "Посмотреть статистику",
        },
        state=state,
        timeout=None,
    )

    if response == "export":
        await export_handler(message, state)
    elif response == "view_stats":
        await show_stats(message)
    # For "register", continue with normal flow
    return response


@commands_menu.add_command("export", "Экспорт списка зарегистрированных участников")
@router.message(Command("export"), AdminFilter())
async def export_handler(message: Message, state: FSMContext):
    """Экспорт списка зарегистрированных участников в Google Sheets или CSV"""
    notif = await send_safe(message.chat.id, "Подготовка экспорта...")

    # Ask user for export format
    response = await ask_user_choice(
        message.chat.id,
        "Выберите формат экспорта:",
        choices={"sheets": "Google Таблицы", "csv": "CSV Файл"},
        state=state,
        timeout=None,
    )

    from app.router import app

    if response == "sheets":
        await notif.edit_text("Экспорт данных в Google Таблицы...")
        result = await app.export_registered_users()
        await send_safe(message.chat.id, result)
    else:
        # Export to CSV
        await notif.edit_text("Экспорт данных в CSV файл...")
        csv_content, result_message = await app.export_to_csv()

        if csv_content:
            # Send the CSV content as a file using send_safe
            await send_safe(message.chat.id, csv_content, filename="участники_встречи.csv")
        else:
            await send_safe(message.chat.id, result_message)

    await notif.delete()


@commands_menu.add_command("stats", "Статистика регистраций")
@router.message(Command("stats"), AdminFilter())
async def show_stats(message: Message):
    """Показать статистику регистраций"""
    # Count registrations by city
    from app.router import app

    cursor = app.collection.aggregate([{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}])
    stats = await cursor.to_list(length=None)

    # Format stats
    stats_text = "Статистика регистраций:\n\n"
    total = 0

    for stat in stats:
        city = stat["_id"]
        count = stat["count"]
        total += count
        stats_text += f"{city}: {count} человек\n"

    stats_text += f"\nВсего: {total} человек"

    await send_safe(message.chat.id, stats_text)
