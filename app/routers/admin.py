import base64
import io
import json
from collections import defaultdict
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    BufferedInputFile,
)
from litellm import acompletion
from loguru import logger
from pydantic import BaseModel

from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice, ask_user_raw
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter


# Define Pydantic model for payment information
class PaymentInfo(BaseModel):
    amount: Optional[int]
    is_valid: bool  # Whether there's a clear payment amount in the document


router = Router()


# Helper function for calculating median
def get_median(ratios):
    if not ratios:
        return 0
    ratios.sort()
    return ratios[len(ratios) // 2]


async def admin_handler(message: Message, state: FSMContext):
    # Show admin options
    response = await ask_user_choice(
        message.chat.id,
        "Вы администратор бота. Что вы хотите сделать?",
        # todo: rework this?
        choices={
            "notify_users": "Рассылка пользователям",
            # stats
            "view_stats": "Посмотреть статистику (подробно)",
            "view_simple_stats": "Посмотреть статистику (кратко)",
            # not finished
            # "mark_payment": "Отметить оплату пользователя вручную",
            # testing
            "register": "Протестировать бота (обычный сценарий)",
            # other
            "other": "Другие действия",
        },
        state=state,
        timeout=None,
    )

    if response == "other":

        response = await ask_user_choice(
            message.chat.id,
            "Другие команды:",
            choices={
                "view_year_stats": "Посмотреть статистику по годам выпуска",
                "five_year_stats": "График по пятилеткам выпуска",
                "payment_stats": "Круговая диаграмма оплат",
                # old
                "export": "Экспортировать данные",
                # too late
                # "notify_early_payment": "Уведомить о раннем платеже",
            },
            state=state,
            timeout=None,
        )

    if response == "export":
        await export_handler(message, state)
    elif response == "view_stats":
        await show_stats(message)
    elif response == "view_simple_stats":
        await show_simple_stats(message)
    elif response == "view_year_stats":
        await show_year_stats(message)
    elif response == "five_year_stats":
        await show_five_year_stats(message)
    elif response == "payment_stats":
        await show_payment_stats(message)
    # elif response == "mark_payment":
    # await mark_payment_handler(message, state)
    elif response == "notify_users":
        from app.routers.crm import notify_users_handler

        await notify_users_handler(message, state)
    # For "register", continue with normal flow
    return response


@commands_menu.add_command(
    "export", "Экспорт списка участников (активных и удаленных)", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("export"), AdminFilter())
async def export_handler(message: Message, state: FSMContext):
    """Экспорт списка зарегистрированных или удаленных участников в Google Sheets или CSV"""
    notif = await send_safe(message.chat.id, "Подготовка экспорта...")

    # Ask user for export type
    export_type_response = await ask_user_choice(
        message.chat.id,
        "Что вы хотите экспортировать?",
        choices={"registered": "Зарегистрированные участники", "deleted": "Удаленные участники"},
        state=state,
        timeout=None,
    )

    # Ask user for export format
    export_format_response = await ask_user_choice(
        message.chat.id,
        "Выберите формат экспорта:",
        choices={"sheets": "Google Таблицы", "csv": "CSV Файл"},
        state=state,
        timeout=None,
    )

    from app.router import app

    # Handle registered users export
    if export_type_response == "registered":
        if export_format_response == "sheets":
            await notif.edit_text("Экспорт данных в Google Таблицы...")
            result = await app.export_registered_users_to_google_sheets()
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

    # Handle deleted users export
    else:  # export_type_response == "deleted"
        if export_format_response == "sheets":
            await notif.edit_text("Экспорт удаленных участников в Google Таблицы...")
            await send_safe(
                message.chat.id,
                "Экспорт удаленных участников в Google Таблицы пока не поддерживается",
            )
        else:
            # Export to CSV
            await notif.edit_text("Экспорт удаленных участников в CSV файл...")
            csv_content, result_message = await app.export_deleted_users_to_csv()

            if csv_content:
                # Send the CSV content as a file using send_safe
                await send_safe(message.chat.id, csv_content, filename="удаленные_участники.csv")
            else:
                await send_safe(message.chat.id, result_message)

    await notif.delete()


def _format_graduate_type(grad_type: str, plural=False):
    from app.app import GRADUATE_TYPE_MAP, GRADUATE_TYPE_MAP_PLURAL

    if plural:
        return GRADUATE_TYPE_MAP_PLURAL[grad_type.upper()]
    return GRADUATE_TYPE_MAP[grad_type.upper()]


@commands_menu.add_command("stats", "Статистика регистраций", visibility=Visibility.ADMIN_ONLY)
@router.message(Command("stats"), AdminFilter())
async def show_stats(message: Message):
    """Показать статистику регистраций"""
    from app.router import app
    from app.app import PAYMENT_STATUS_MAP

    # Initialize stats text
    stats_text = "<b>📊 Статистика регистраций</b>\n\n"

    # 1. Count registrations by city
    city_cursor = app.collection.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    city_stats = await city_cursor.to_list(length=None)

    stats_text += "<b>🌆 По городам:</b>\n"
    total = 0
    for stat in city_stats:
        city = stat["_id"]
        count = stat["count"]
        total += count
        stats_text += f"• {city}: <b>{count}</b> человек\n"
    stats_text += f"\nВсего: <b>{total}</b> человек\n\n"

    # 2. Distribution by graduate type
    grad_cursor = app.collection.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    grad_stats = await grad_cursor.to_list(length=None)

    stats_text += "<b>👥 По статусу:</b>\n"
    for stat in grad_stats:
        grad_type = (
            stat["_id"] or "GRADUATE"
        ).upper()  # Default to GRADUATE if None and ensure uppercase
        count = stat["count"]
        text = _format_graduate_type(grad_type, plural=count != 1)
        stats_text += f"• {text}: <b>{count}</b>\n"
    stats_text += "\n"

    # 3. Payment statistics by city
    payment_cursor = app.collection.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "payments": {
                        "$push": {
                            "payment": {"$ifNull": ["$payment_amount", 0]},
                            "formula": {"$ifNull": ["$formula_payment_amount", 0]},
                            "regular": {"$ifNull": ["$regular_payment_amount", 0]},
                            "discounted": {"$ifNull": ["$discounted_payment_amount", 0]},
                        }
                    },
                    "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    )
    payment_stats = await payment_cursor.to_list(length=None)

    stats_text += "<b>💰 Статистика оплат:</b>\n"
    total_paid = 0
    total_formula = 0
    total_regular = 0
    total_discounted = 0

    for stat in payment_stats:
        city = stat["_id"]
        paid = stat["total_paid"]
        payments = stat["payments"]

        # Calculate median percentages for paid registrations
        paid_ratios_formula = []
        paid_ratios_regular = []
        paid_ratios_discounted = []

        for p in payments:
            if p["payment"] > 0:  # Only include those who paid
                if p["formula"] > 0:
                    paid_ratios_formula.append((p["payment"] / p["formula"]) * 100)
                if p["regular"] > 0:
                    paid_ratios_regular.append((p["payment"] / p["regular"]) * 100)
                if p["discounted"] > 0:
                    paid_ratios_discounted.append((p["payment"] / p["discounted"]) * 100)

        # Calculate medians
        median_formula = get_median(paid_ratios_formula)
        median_regular = get_median(paid_ratios_regular)
        median_discounted = get_median(paid_ratios_discounted)

        # Calculate totals
        formula_total = sum(p["formula"] for p in payments)
        regular_total = sum(p["regular"] for p in payments)
        discounted_total = sum(p["discounted"] for p in payments)

        total_paid += paid
        total_formula += formula_total
        total_regular += regular_total
        total_discounted += discounted_total

        stats_text += f"\n<b>{city}:</b>\n"
        stats_text += f"💵 Собрано: <b>{paid:,}</b> руб.\n"
        stats_text += f"📊 Медиана % от формулы: <i>{median_formula:.1f}%</i>\n"
        stats_text += f"📊 Медиана % от регулярной: <i>{median_regular:.1f}%</i>\n"
        stats_text += f"📊 Медиана % от мин. со скидкой: <i>{median_discounted:.1f}%</i>\n\n"

        # Payment status distribution
        stats_text += "<u>Статусы платежей:</u>\n"
        stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{stat['confirmed_count']}</b>\n"
        stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{stat['pending_count']}</b>\n"
        stats_text += f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{stat['declined_count'] + stat['unpaid_count']}</b>\n"

    # Add totals
    if total_paid > 0:
        stats_text += f"\n<b>💵 Итого собрано: {total_paid:,} руб.</b>\n"

        # Calculate overall medians
        all_ratios_formula = []
        all_ratios_regular = []
        all_ratios_discounted = []

        for stat in payment_stats:
            for p in stat["payments"]:
                if p["payment"] > 0:
                    if p["formula"] > 0:
                        all_ratios_formula.append((p["payment"] / p["formula"]) * 100)
                    if p["regular"] > 0:
                        all_ratios_regular.append((p["payment"] / p["regular"]) * 100)
                    if p["discounted"] > 0:
                        all_ratios_discounted.append((p["payment"] / p["discounted"]) * 100)

        total_median_formula = get_median(all_ratios_formula)
        total_median_regular = get_median(all_ratios_regular)
        total_median_discounted = get_median(all_ratios_discounted)

        stats_text += f"📊 Общая медиана % от формулы: <i>{total_median_formula:.1f}%</i>\n"
        stats_text += f"📊 Общая медиана % от регулярной: <i>{total_median_regular:.1f}%</i>\n"
        stats_text += (
            f"📊 Общая медиана % от мин. со скидкой: <i>{total_median_discounted:.1f}%</i>\n"
        )

    await send_safe(message.chat.id, stats_text)


@commands_menu.add_command(
    "simple_stats", "Краткая статистика регистраций", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("simple_stats"), AdminFilter())
async def show_simple_stats(message: Message):
    """Показать краткую статистику регистраций"""
    from app.router import app
    from app.app import PAYMENT_STATUS_MAP

    stats_text = "<b>📊 Краткая статистика регистраций</b>\n\n"

    # 1. Count registrations by city
    city_cursor = app.collection.aggregate(
        [{"$group": {"_id": "$target_city", "count": {"$sum": 1}}}]
    )
    city_stats = await city_cursor.to_list(length=None)

    stats_text += "<b>🌆 По городам:</b>\n"
    total = 0
    for stat in city_stats:
        city = stat["_id"]
        count = stat["count"]
        total += count
        stats_text += f"• {city}: <b>{count}</b> человек\n"
    stats_text += f"\nВсего: <b>{total}</b> человек\n\n"

    # 2. Distribution by graduate type
    grad_cursor = app.collection.aggregate(
        [
            {
                "$addFields": {
                    "normalized_type": {
                        "$toUpper": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$graduate_type", None]},
                                        {"$eq": [{"$toUpper": "$graduate_type"}, "GRADUATE"]},
                                    ]
                                },
                                "GRADUATE",
                                "$graduate_type",
                            ]
                        }
                    }
                }
            },
            {"$group": {"_id": "$normalized_type", "count": {"$sum": 1}}},
        ]
    )
    grad_stats = await grad_cursor.to_list(length=None)

    stats_text += "<b>👥 По статусу:</b>\n"
    for stat in grad_stats:
        grad_type = (
            stat["_id"] or "GRADUATE"
        ).upper()  # Default to GRADUATE if None and ensure uppercase
        count = stat["count"]
        text = _format_graduate_type(grad_type, plural=count != 1)
        stats_text += f"• {text}: <b>{count}</b>\n"
    stats_text += "\n"

    # 3. Basic payment status distribution (without amounts)
    payment_cursor = app.collection.aggregate(
        [
            {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
            {"$match": {"target_city": {"$ne": "Белград"}}},  # Exclude Belgrade as it's free
            {"$match": {"graduate_type": {"$ne": "TEACHER"}}},  # Exclude teachers as they don't pay
            {
                "$group": {
                    "_id": "$target_city",
                    "confirmed_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}
                    },
                    "pending_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", "pending"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "declined_count": {
                        "$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}
                    },
                    "unpaid_count": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$eq": ["$payment_status", None]},
                                        {"$eq": ["$payment_status", "Не оплачено"]},
                                        {"$not": "$payment_status"},  # No payment_status field
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
    )
    payment_stats = await payment_cursor.to_list(length=None)

    stats_text += "<b>💰 Статусы оплат:</b>\n"
    total_confirmed = 0
    total_pending = 0
    total_declined = 0
    total_unpaid = 0

    for stat in payment_stats:
        city = stat["_id"]
        confirmed = stat["confirmed_count"]
        pending = stat["pending_count"]
        declined = stat["declined_count"]
        unpaid = stat["unpaid_count"]

        total_confirmed += confirmed
        total_pending += pending
        total_declined += declined
        total_unpaid += unpaid

        stats_text += f"\n<b>{city}:</b>\n"
        stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{confirmed}</b>\n"
        stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{pending}</b>\n"
        stats_text += f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{declined + unpaid}</b>\n"

    # Add totals
    total_with_payment = total_confirmed + total_pending + total_declined + total_unpaid
    if total_with_payment > 0:
        stats_text += f"\n<b>Всего по статусам:</b>\n"
        stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{total_confirmed}</b>\n"
        stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{total_pending}</b>\n"
        stats_text += f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{total_declined + total_unpaid}</b>\n"

    await send_safe(message.chat.id, stats_text)


@commands_menu.add_command(
    "normalize_db", "Нормализовать типы выпускников в БД", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("normalize_db"), AdminFilter())
async def normalize_db(message: Message):
    """Normalize graduate types in the database"""
    from app.router import app

    # Send initial message
    status_msg = await send_safe(message.chat.id, "Нормализация типов выпускников в базе данных...")

    # Run normalization
    modified = await app.normalize_graduate_types()

    # Update message with results
    await status_msg.edit_text(f"✅ Нормализация завершена. Обновлено записей: {modified}")


# todo: auto-determine file type from name.
# async def extract_payment_from_image(
#         file_bytes: bytes
# file_name: str
# ) -> PaymentInfo:
# if file_name.endswith(".pdf"):
#     file_type = "application/pdf"
## elif file_name.endswith(".jpg") or file_name.endswith(".jpeg") or file_name.endswith(".png"):
# else:
#     file_type = "image/{file_name.split('.')[-1]}"
async def extract_payment_from_image(
    file_bytes: bytes, file_type: str = "image/jpeg"
) -> PaymentInfo:
    """Extract payment amount from an image or PDF using GPT-4 Vision via litellm"""
    try:
        # Define the system prompt for payment extraction
        system_prompt = """You are a payment receipt analyzer.
        Your task is to extract ONLY the payment amount in rubles from the receipt image or PDF.

        If you cannot determine the amount or if it's ambiguous, set amount to null and is_valid to false."""

        # For images, encode to base64
        encoded_file = base64.b64encode(file_bytes).decode("utf-8")
        if file_type not in ["image/jpeg", "image/png", "application/pdf"]:
            raise ValueError(f"Unsupported file type: {file_type}")

        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Please extract the payment amount from this receipt:",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{file_type};base64,{encoded_file}"},
                    },
                ],
            },
        ]

        # Make the API call with the Pydantic model
        response = await acompletion(
            model="claude-3-5-sonnet-20240620",
            messages=messages,
            max_tokens=100,
            response_format=PaymentInfo,
        )

        return PaymentInfo(**json.loads(response.choices[0].message.content))
    except Exception as e:
        logger.error(f"Error extracting payment amount: {e}")
        return PaymentInfo(amount=None, is_valid=False)


@commands_menu.add_command(
    "parse_payment", "Анализ платежа с помощью GPT-4", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("parse_payment"), AdminFilter())
async def parse_payment_handler(message: Message, state: FSMContext):
    """Hidden admin command to test payment parsing from images/PDFs"""
    # Ask user to send a payment proof
    response = await ask_user_raw(
        message.chat.id,
        "Отправьте скриншот или PDF с подтверждением платежа для анализа суммы платежа",
        state,
        timeout=300,  # 5 minutes timeout
    )

    if not response:
        await send_safe(message.chat.id, "Время ожидания истекло.")
        return

    # Check if the message has a photo or document
    has_photo = response.photo is not None and len(response.photo) > 0
    has_pdf = response.document is not None and response.document.mime_type == "application/pdf"

    if not (has_photo or has_pdf):
        await send_safe(message.chat.id, "Пожалуйста, отправьте изображение или PDF-файл")
        return

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Анализирую платеж...")

    try:
        # Download the file
        from botspot.core.dependency_manager import get_dependency_manager

        deps = get_dependency_manager()
        bot = deps.bot

        file_id = None
        if has_photo and response.photo:
            # Get the largest photo
            file_id = response.photo[-1].file_id
            file_type = "image/jpeg"
        elif has_pdf and response.document:
            file_id = response.document.file_id
            file_type = "application/pdf"
        else:
            await status_msg.edit_text("❌ Не удалось получить файл")
            return

        if not file_id:
            await status_msg.edit_text("❌ Не удалось получить файл")
            return

        # Download the file
        file = await bot.get_file(file_id)
        if not file or not file.file_path:
            await status_msg.edit_text("❌ Не удалось получить путь к файлу")
            return

        file_bytes = await bot.download_file(file.file_path)
        if not file_bytes:
            await status_msg.edit_text("❌ Не удалось скачать файл")
            return

        # Extract payment information directly from the file
        result = await extract_payment_from_image(file_bytes.read(), file_type)

        # Format the response
        if result.is_valid:
            response_text = f"✅ Обнаружен платеж на сумму: <b>{result.amount}</b> руб."
        else:
            response_text = "❌ Не удалось извлечь сумму платежа"

        # Update the status message with the results
        await status_msg.edit_text(response_text, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text(f"❌ Произошла ошибка: {str(e)}")


@commands_menu.add_command(
    "year_stats", "Статистика регистраций по годам выпуска", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("year_stats"), AdminFilter())
async def show_year_stats(message: Message):
    """Show registration statistics by graduation year with matplotlib diagrams"""
    from app.router import app

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация статистики по годам выпуска...")

    # Get all registrations
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out teachers and others without graduation year
        }
    )
    registrations = await cursor.to_list(length=None)

    if not registrations:
        await status_msg.edit_text("❌ Нет данных о регистрациях с указанным годом выпуска.")
        return

    # Group registrations by city and year
    cities = ["Москва", "Пермь", "Санкт-Петербург", "Белград"]
    city_year_counts = {}

    for city in cities:
        city_year_counts[city] = defaultdict(int)

    all_years = set()

    for reg in registrations:
        city = reg.get("target_city")
        year = reg.get("graduation_year")

        # Skip registrations without valid graduation year (teachers, etc.)
        if not year or year == 0 or city not in cities:
            continue

        # Count by city and year
        city_year_counts[city][year] += 1
        all_years.add(year)

    # Group years into 5-year periods for text statistics
    min_year = min(all_years)
    max_year = max(all_years)

    # Round min_year down to the nearest multiple of 5
    period_start = min_year - (min_year % 5)

    # Create periods (e.g. 1995-1999, 2000-2004, etc.)
    periods = []
    period_labels = []
    current = period_start

    while current <= max_year:
        period_end = current + 4
        periods.append((current, period_end))
        period_labels.append(f"{current}-{period_end}")
        current += 5

    # Count registrations by period for each city
    period_counts = {city: [0] * len(periods) for city in cities}

    for city in cities:
        for year, count in city_year_counts[city].items():
            # Find which period this year belongs to
            for i, (start, end) in enumerate(periods):
                if start <= year <= end:
                    period_counts[city][i] += count
                    break

    # Prepare the summary statistics text
    stats_text = "<b>📊 Статистика регистраций по годам выпуска</b>\n\n"

    # Add total registrations per period
    stats_text += "<b>🎓 По периодам (все города):</b>\n"

    for i, period in enumerate(period_labels):
        period_total = sum(period_counts[city][i] for city in cities)
        stats_text += f"• {period}: <b>{period_total}</b> человек\n"

    # Add city breakdown
    for city in cities:
        stats_text += f"\n<b>🏙️ {city}:</b>\n"
        for i, period in enumerate(period_labels):
            count = period_counts[city][i]
            stats_text += f"• {period}: <b>{count}</b> человек\n"

    # Convert data to pandas DataFrame for seaborn
    data = []
    sorted_years = sorted(all_years)

    for city in cities:
        for year in sorted_years:
            count = city_year_counts[city].get(year, 0)
            if count > 0:  # Only include non-zero values
                data.append({"Город": city, "Год выпуска": year, "Количество": count})

    df = pd.DataFrame(data)

    # Define the color palette
    city_palette = {
        "Москва": "#FF6666",  # stronger red
        "Пермь": "#5599FF",  # stronger blue
        "Санкт-Петербург": "#66CC66",  # stronger green
        "Белград": "#FF00FF",  # stronger purple
    }

    # Create figure with better size for readability
    plt.figure(figsize=(15, 8), dpi=100)

    # Use seaborn with custom styling
    sns.set_style("whitegrid")

    # Create the bar plot
    ax = sns.barplot(
        data=df, x="Год выпуска", y="Количество", hue="Город", palette=city_palette, errorbar=None
    )

    # Add annotations for each bar
    for container in ax.containers:
        ax.bar_label(container, fontsize=9, fontweight="bold", padding=3)

    # Enhance the plot with better styling
    plt.title("Количество регистраций по годам выпуска", fontsize=18, pad=20)
    plt.xlabel("Год выпуска", fontsize=14, labelpad=10)
    plt.ylabel("Количество человек", fontsize=14, labelpad=10)
    plt.xticks(rotation=45)
    plt.legend(title="Город", fontsize=12, title_fontsize=14)

    # Adjust layout
    plt.tight_layout()

    # Save the plot to a bytes buffer
    buf_all_cities = io.BytesIO()
    plt.savefig(buf_all_cities, format="png")
    buf_all_cities.seek(0)
    plt.close()

    # Send the stats text and diagram
    await status_msg.delete()

    # Send the text first
    await send_safe(message.chat.id, stats_text, parse_mode="HTML")

    # Send the diagram
    await message.answer_photo(
        BufferedInputFile(buf_all_cities.getvalue(), filename="registration_stats.png")
    )


@commands_menu.add_command(
    "five_year_stats", "График по пятилеткам выпуска", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("five_year_stats"), AdminFilter())
async def show_five_year_stats(message: Message):
    """Показать график регистраций по пятилеткам выпуска и городам"""
    from app.router import app

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация графика по пятилеткам выпуска...")

    # Get all registrations
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
        }
    )
    registrations = await cursor.to_list(length=None)

    if not registrations:
        await status_msg.edit_text("❌ Нет данных о регистрациях с указанным годом выпуска.")
        return

    # Convert MongoDB records to pandas DataFrame
    df = pd.DataFrame(registrations)

    # Обработка годов выпуска
    df["graduation_year"] = pd.to_numeric(df["graduation_year"], errors="coerce")
    df = df.dropna(subset=["graduation_year"])
    df["Пятилетка"] = df["graduation_year"].apply(lambda y: f"{int(y)//5*5}–{int(y)//5*5 + 4}")

    # Упрощённая категоризация городов
    def simplify_city(city):
        if pd.isna(city):
            return "Другие"
        city = str(city).strip().lower()
        if "перм" in city:
            return "Пермь"
        elif "моск" in city:
            return "Москва"
        elif "спб" in city or "питер" in city or "санкт" in city:
            return "Санкт-Петербург"
        elif "белград" in city:
            return "Белград"
        else:
            return "Другие"

    df["Город (укрупнённо)"] = df["target_city"].apply(simplify_city)

    # Группировка по пятилеткам и городам
    pivot = (
        df.groupby(["Пятилетка", "Город (укрупнённо)"])["full_name"]
        .count()
        .unstack()
        .fillna(0)
        .sort_index()
    )

    # Упорядочим колонки
    city_order = ["Пермь", "Москва", "Санкт-Петербург", "Белград", "Другие"]
    available_cities = [c for c in city_order if c in pivot.columns]
    if available_cities:
        pivot = pivot[available_cities]

    # Построение графика
    plt.figure(figsize=(12, 7), dpi=100)
    ax = pivot.plot(kind="bar", stacked=True, figsize=(12, 7), colormap="Set2")

    plt.title("Зарегистрировавшиеся по пятилеткам выпуска (города: Пермь, Москва, СПб, Белград)")
    plt.xlabel("Пятилетка")
    plt.ylabel("Количество участников")
    plt.xticks(rotation=45)
    plt.legend(title="Город", bbox_to_anchor=(1.05, 1), loc="upper left")
    plt.tight_layout()
    plt.grid(axis="y")

    # Подписи на графике
    for bar_idx, (idx, row) in enumerate(pivot.iterrows()):
        cumulative = 0
        for city in pivot.columns:
            value = row[city]
            if value > 0:
                ax.text(
                    x=bar_idx,
                    y=cumulative + value / 2,
                    s=int(value),
                    ha="center",
                    va="center",
                    fontsize=9,
                )
                cumulative += value

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    # Delete status message
    await status_msg.delete()

    # Send the diagram
    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="five_year_stats.png"),
        caption="📊 Зарегистрировавшиеся по пятилеткам выпуска и городам участия",
    )


# @commands_menu.add_command(
#     "mark_payment", "Пометить оплату пользователя", visibility=Visibility.ADMIN_ONLY
# )
# @router.message(Command("mark_payment"), AdminFilter())
# async def mark_payment_handler(message: Message, state: FSMContext):
#     """Поиск пользователя по имени или юзернейму и отметка оплаты"""
#     from app.router import app
#
#     # Ask for search term
#     search_message = await ask_user(
#         message.chat.id, "Введите часть ФИО или @username пользователя для поиска:", state
#     )
#
#     from app.router import app
#
#     search_term = message.text.strip()
#     if len(search_term) < 3:
#         await send_safe(
#             message.chat.id,
#             "Поисковый запрос слишком короткий. Введите не менее 3 символов:",
#         )
#         return
#
#     # Get state data
#     state_data = await state.get_data()
#     search_message_id = state_data.get("search_message_id")
#
#     # Show searching message
#     status_msg = await send_safe(
#         message.chat.id,
#         f"🔍 Поиск пользователей по запросу '{search_term}'...",
#     )
#
#     # Build search query (search in username or fullname)
#     if search_term.startswith("@"):
#         # Remove @ for username search
#         username_query = search_term[1:].lower()
#         query = {"username": {"$regex": username_query, "$options": "i"}}
#     else:
#         # Search in full_name
#         query = {"full_name": {"$regex": search_term, "$options": "i"}}
#
#     # Execute search
#     cursor = app.collection.find(query)
#     users = await cursor.to_list(length=None)
#
#     # Group users by user_id to avoid duplicates
#     users_by_id = {}
#     for user in users:
#         user_id = user.get("user_id")
#         if user_id not in users_by_id:
#             users_by_id[user_id] = user
#
#     # Check if we found any users
#     if not users_by_id:
#         await status_msg.edit_text(
#             f"❌ Пользователи по запросу '{search_term}' не найдены. Попробуйте другой запрос."
#         )
#         return
#
#     # Prepare choices for selection
#     choices = {}
#     for user_id, user in users_by_id.items():
#         username = user.get("username", "")
#         full_name = user.get("full_name", "Имя не указано")
#         city = user.get("target_city", "Город не указан")
#         payment_status = user.get("payment_status", "Не оплачено")
#
#         # Format payment status
#         if payment_status == "confirmed":
#             payment_status = "Оплачено"
#         elif payment_status == "pending":
#             payment_status = "Оплачу позже"
#         elif payment_status == "declined":
#             payment_status = "Отклонено"
#         else:
#             payment_status = "Не оплачено"
#
#         # Format display text
#         display = f"{full_name}"
#         if username:
#             display += f" (@{username})"
#         display += f" - {city}, {payment_status}"
#
#         # Add to choices
#         choices[str(user_id)] = display
#
#     # Add cancel option
#     choices["cancel"] = "❌ Отмена"
#
#     # Update search status message
#     await status_msg.edit_text(
#         f"🔍 Найдено {len(users_by_id)} пользователей по запросу '{search_term}'.\nВыберите пользователя:"
#     )
#
#     # Ask for user selection
#     response = await ask_user_choice(
#         message.chat.id,
#         "Выберите пользователя:",
#         choices=choices,
#         state=state,
#         timeout=None,
#     )
#
#     # Handle response
#     if response == "cancel":
#         await send_safe(message.chat.id, "Операция отменена.")
#         await state.clear()
#         return
#
#     # Get selected user
#     user_id = int(response)
#     selected_user = users_by_id.get(user_id)
#
#     if not selected_user:
#         await send_safe(message.chat.id, "Ошибка: выбранный пользователь не найден в результатах.")
#         await state.clear()
#         return
#
#     # Get all cities for this user to choose from
#     all_registrations = await app.get_user_registrations(user_id)
#
#     # Filter only cities that require payment (exclude SPb, Belgrade, and teacher registrations)
#     payment_registrations = [
#         reg
#         for reg in all_registrations
#         if reg["target_city"] != "Санкт-Петербург"
#         and reg["target_city"] != "Белград"
#         and reg.get("graduate_type", "GRADUATE") != "TEACHER"
#     ]
#
#     if not payment_registrations:
#         await send_safe(
#             message.chat.id,
#             f"У пользователя {selected_user.get('full_name')} нет регистраций, требующих оплаты.",
#         )
#         await state.clear()
#         return
#
#     # If only one city requires payment, select it automatically
#     if len(payment_registrations) == 1:
#         city = payment_registrations[0]["target_city"]
#         graduation_year = payment_registrations[0]["graduation_year"]
#
#         # Calculate payment amounts
#         graduate_type = payment_registrations[0].get("graduate_type", "GRADUATE")
#         regular_amount, discount, discounted_amount, formula_amount = app.calculate_payment_amount(
#             city, graduation_year, graduate_type
#         )
#
#         # Store values for confirmation
#         await state.update_data(
#             selected_user_id=user_id,
#             selected_city=city,
#             regular_amount=regular_amount,
#             discounted_amount=discounted_amount,
#             formula_amount=formula_amount,
#             graduation_year=graduation_year,
#             graduate_type=graduate_type,
#         )
#
#         # Ask for payment amount
#         username = selected_user.get("username", "")
#         username_display = f" (@{username})" if username else ""
#
#         # Format status message with payment options
#         from datetime import datetime
#         from app.routers.payment import EARLY_REGISTRATION_DATE
#
#         # Check if we're in early registration period
#         today = datetime.now()
#         is_early_registration = today < EARLY_REGISTRATION_DATE
#
#         payment_options = f"💰 Варианты суммы:\n"
#
#         if is_early_registration:
#             payment_options += f"• Ранняя оплата (со скидкой): {discounted_amount} руб.\n"
#
#         payment_options += f"• Стандартная сумма: {regular_amount} руб.\n"
#
#         if formula_amount > regular_amount:
#             payment_options += f"• По формуле: {formula_amount} руб.\n"
#
#         status_msg = await send_safe(
#             message.chat.id,
#             f"Пользователь: {selected_user.get('full_name')}{username_display}\n"
#             f"Город: {city}\n"
#             f"Год выпуска: {graduation_year}\n\n"
#             f"{payment_options}\n"
#             f"Введите сумму оплаты:",
#         )
#     else:
#         # Multiple cities, ask which one to mark payment for
#         city_choices = {}
#         for reg in payment_registrations:
#             city = reg["target_city"]
#             payment_status = reg.get("payment_status", "Не оплачено")
#
#             # Format payment status
#             if payment_status == "confirmed":
#                 status_emoji = "✅"
#             elif payment_status == "pending":
#                 status_emoji = "⏳"
#             elif payment_status == "declined":
#                 status_emoji = "❌"
#             else:
#                 status_emoji = "⚪"
#
#             city_choices[city] = f"{city} {status_emoji}"
#
#         # Add cancel option
#         city_choices["cancel"] = "❌ Отмена"
#
#         # Ask for city selection
#         response = await ask_user_choice(
#             message.chat.id,
#             f"У пользователя {selected_user.get('full_name')} несколько регистраций. Выберите город:",
#             choices=city_choices,
#             state=state,
#             timeout=None,
#         )
#
#         if response == "cancel":
#             await send_safe(message.chat.id, "Операция отменена.")
#             await state.clear()
#             return
#
#         # Get the registration for selected city
#         selected_reg = next(
#             (reg for reg in payment_registrations if reg["target_city"] == response), None
#         )
#
#         if not selected_reg:
#             await send_safe(message.chat.id, "Ошибка: выбранный город не найден.")
#             await state.clear()
#             return
#
#         city = selected_reg["target_city"]
#         graduation_year = selected_reg["graduation_year"]
#
#         # Calculate payment amounts
#         graduate_type = selected_reg.get("graduate_type", "GRADUATE")
#         regular_amount, discount, discounted_amount, formula_amount = app.calculate_payment_amount(
#             city, graduation_year, graduate_type
#         )
#
#         # Store values for confirmation
#         await state.update_data(
#             selected_user_id=user_id,
#             selected_city=city,
#             regular_amount=regular_amount,
#             discounted_amount=discounted_amount,
#             formula_amount=formula_amount,
#             graduation_year=graduation_year,
#             graduate_type=graduate_type,
#         )
#
#         # Ask for payment amount
#         username = selected_user.get("username", "")
#         username_display = f" (@{username})" if username else ""
#
#         # Format status message with payment options
#         from datetime import datetime
#         from app.routers.payment import EARLY_REGISTRATION_DATE
#
#         # Check if we're in early registration period
#         today = datetime.now()
#         is_early_registration = today < EARLY_REGISTRATION_DATE
#
#         payment_options = f"💰 Варианты суммы:\n"
#
#         if is_early_registration:
#             payment_options += f"• Ранняя оплата (со скидкой): {discounted_amount} руб.\n"
#
#         payment_options += f"• Стандартная сумма: {regular_amount} руб.\n"
#
#         if formula_amount > regular_amount:
#             payment_options += f"• По формуле: {formula_amount} руб.\n"
#
#         while True:
#             try:
#                 response = await ask_user(
#                     message.chat.id,
#                     f"Пользователь: {selected_user.get('full_name')}{username_display}\n"
#                     f"Город: {city}\n"
#                     f"Год выпуска: {graduation_year}\n\n"
#                     f"{payment_options}\n"
#                     f"Введите сумму оплаты:",
#                 )
#                 if not response:
#                     return
#                 payment_amount = int(response)
#                 break
#             except:
#                 await send_safe(
#                     message.chat.id, "❌ Некорректная сумма. Введите положительное число:"
#                 )
#
#     from app.router import app
#
#     # Get user info
#     user_data = await app.collection.find_one({"user_id": user_id, "target_city": city})
#
#     if not user_data:
#         await send_safe(message.chat.id, "❌ Ошибка: пользователь или регистрация не найдены.")
#         await state.clear()
#         return
#
#     # Format confirmation message
#     username = user_data.get("username", "")
#     username_display = f" (@{username})" if username else ""
#     full_name = user_data.get("full_name", "Неизвестное имя")
#
#     # Get current payment amount if exists
#     current_amount = user_data.get("payment_amount", 0)
#     payment_status = user_data.get("payment_status", None)
#
#     confirmation_text = f"⚠️ Подтвердите данные платежа:\n\n"
#     confirmation_text += f"👤 {full_name}{username_display}\n"
#     confirmation_text += f"🏙️ {city}\n"
#     confirmation_text += f"💰 Сумма к зачислению: {payment_amount} руб.\n"
#
#     if payment_status == "confirmed" and current_amount > 0:
#         # This is an additional payment
#         confirmation_text += (
#             f"\n⚠️ У пользователя уже есть подтвержденный платеж на сумму {current_amount} руб.\n"
#         )
#         confirmation_text += (
#             f"✅ Итоговая сумма после зачисления: {current_amount + payment_amount} руб."
#         )
#
#     confirm = await ask_user_confirmation(
#         message.chat.id,
#         confirmation_text,
#         state=state,
#     )
#
#     if not confirm:
#         await send_safe(message.chat.id, "Операция отменена.")
#         await state.clear()
#         return
#
#     await app.update_payment_status(
#         user_id=user_id,
#         city=city,
#         status="confirmed",
#         payment_amount=payment_amount,
#         admin_id=message.from_user.id,
#         admin_username=message.from_user.username,
#         admin_comment="Платеж отмечен администратором",
#     )
#
#     # Get updated user data
#     updated_user = await app.collection.find_one({"user_id": user_id, "target_city": city})
#     total_amount = updated_user.get("payment_amount", payment_amount)
#
#     # Send success message
#     success_message = (
#         f"✅ Платеж успешно зачислен!\n\n"
#         f"👤 {full_name}{username_display}\n"
#         f"🏙️ {city}\n"
#         f"💰 Сумма платежа: {payment_amount} руб.\n"
#     )
#
#     if total_amount != payment_amount:
#         success_message += f"💵 Итоговая сумма: {total_amount} руб.\n"
#
#     # Notify the user about the payment
#     try:
#         user_notification = (
#             f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден!\n"
#             f"Сумма: {payment_amount} руб."
#         )
#
#         if total_amount != payment_amount:
#             user_notification += f"\nОбщая сумма внесенных платежей: {total_amount} руб."
#
#         user_notification += "\nСпасибо за оплату."
#
#         await send_safe(user_id, user_notification)
#         success_message += "\n✉️ Уведомление пользователю отправлено."
#     except Exception as e:
#         logger.error(f"Failed to notify user {user_id} about payment: {e}")
#         success_message += "\n⚠️ Не удалось отправить уведомление пользователю."
#
#     await send_safe(message.chat.id, success_message)
#
#     # Auto-export to Google Sheets
#     await app.export_registered_users_to_google_sheets()


@commands_menu.add_command(
    "payment_stats", "Круговая диаграмма оплат", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("payment_stats"), AdminFilter())
async def show_payment_stats(message: Message):
    """Показать круговую диаграмму оплат по пятилеткам выпуска"""
    from app.router import app

    # Send status message
    status_msg = await send_safe(message.chat.id, "⏳ Генерация круговой диаграммы оплат...")

    # Get all registrations
    cursor = app.collection.find(
        {
            "graduation_year": {
                "$exists": True,
                "$ne": 0,
            },  # Filter out entries without graduation year
            "payment_status": "confirmed",  # Only include confirmed payments
            "payment_amount": {"$gt": 0},  # Only include payments > 0
        }
    )
    registrations = await cursor.to_list(length=None)

    if not registrations:
        await status_msg.edit_text("❌ Нет данных об оплатах с указанным годом выпуска.")
        return

    # Convert MongoDB records to pandas DataFrame
    df = pd.DataFrame(registrations)

    # Обработка годов выпуска
    df["graduation_year"] = pd.to_numeric(df["graduation_year"], errors="coerce")
    df = df.dropna(subset=["graduation_year"])
    df["Пятилетка"] = df["graduation_year"].apply(lambda y: f"{int(y)//5*5}–{int(y)//5*5 + 4}")

    # Группировка и сумма по пятилеткам
    donation_by_period = df.groupby("Пятилетка")["payment_amount"].sum()
    donation_by_period = donation_by_period[donation_by_period > 0].sort_index()

    # Построение круговой диаграммы
    plt.figure(figsize=(10, 10), dpi=100)

    # Get a nicer color palette
    colors = plt.cm.Set3.colors[: len(donation_by_period)]

    # Add percentage and absolute values to the labels
    total = donation_by_period.sum()
    labels = [
        f"{period}: {amount:,.0f} ₽ ({amount/total:.1%})"
        for period, amount in zip(donation_by_period.index, donation_by_period.values)
    ]

    plt.pie(
        donation_by_period.values,
        labels=labels,
        autopct="",  # We already added percentages to labels
        startangle=90,
        colors=colors,
        shadow=False,
        wedgeprops={"linewidth": 1, "edgecolor": "white"},
    )

    plt.title("Суммарные оплаты по пятилеткам выпуска", fontsize=16, pad=20)
    plt.tight_layout()

    # Save the plot to a bytes buffer
    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    buf.seek(0)
    plt.close()

    # Delete status message
    await status_msg.delete()

    # Send the diagram
    await message.answer_photo(
        BufferedInputFile(buf.getvalue(), filename="payment_stats.png"),
        caption="💰 Суммарные оплаты по пятилеткам выпуска",
    )
