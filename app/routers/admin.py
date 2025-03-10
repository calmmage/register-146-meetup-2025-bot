import base64
import json
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
)
from litellm import completion
from pydantic import BaseModel
from typing import Optional, Dict, Any

from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice, ask_user_raw
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter


# Define Pydantic model for payment information
class PaymentInfo(BaseModel):
    amount: Optional[float] = None
    is_valid: bool = False  # Whether there's a clear payment amount in the document


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
            "register": "Протестировать бота (обычный сценарий)",
            "export": "Экспортировать данные",
            "view_stats": "Посмотреть статистику (подробно)",
            "view_simple_stats": "Посмотреть статистику (кратко)",
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
    # For "register", continue with normal flow
    return response


@commands_menu.add_command(
    "export", "Экспорт списка зарегистрированных участников", visibility=Visibility.ADMIN_ONLY
)
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


async def extract_payment_from_image(image_bytes: bytes) -> Dict[str, Any]:
    """Extract payment amount from an image or PDF using GPT-4 Vision via litellm"""
    try:
        # Encode image to base64
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")

        # Define the system prompt for payment extraction
        system_prompt = """You are a payment receipt analyzer. 
        Your task is to extract ONLY the payment amount in rubles from the receipt image.
        
        Return a JSON with two fields:
        1. "amount": The payment amount as a number (no currency symbol, just the number)
        2. "is_valid": A boolean indicating whether there is a clear payment amount in the document
        
        If you cannot determine the amount or if it's ambiguous, set amount to null and is_valid to false."""

        # Create the messages for the API call
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
                        "image_url": {"url": f"data:image/jpeg;base64,{encoded_image}"},
                    },
                ],
            },
        ]

        # Make the API call with JSON response format
        response = completion(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=100,
            response_format={"type": "json_object"},
        )

        # Extract content from the response
        if hasattr(response, "choices") and response.choices:
            content = response.choices[0].message.content
        else:
            # Handle litellm's different response format
            content = response.content

        # Parse the JSON response
        if content:
            result = json.loads(content)

            # Ensure the amount is a number if present
            if "amount" in result and result["amount"] is not None:
                result["amount"] = float(result["amount"])

            # Ensure is_valid is a boolean
            if "is_valid" not in result:
                result["is_valid"] = False

            return result
        else:
            return {"error": "No content in response", "amount": None, "is_valid": False}

    except Exception as e:
        return {"error": str(e), "amount": None, "is_valid": False}


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
        elif has_pdf and response.document:
            file_id = response.document.file_id

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

        # Extract payment information
        result = await extract_payment_from_image(file_bytes.read())

        # Format the response
        if "error" in result:
            response_text = f"❌ Ошибка при анализе: {result['error']}"
        else:
            amount = result.get("amount")
            is_valid = result.get("is_valid", False)

            if is_valid and amount is not None:
                response_text = f"✅ Обнаружен платеж на сумму: <b>{amount}</b> руб."
            else:
                response_text = "❌ Не удалось определить сумму платежа. Пожалуйста, убедитесь, что на изображении четко видна сумма платежа."

        # Update the status message with the results
        await status_msg.edit_text(response_text, parse_mode="HTML")

    except Exception as e:
        await status_msg.edit_text(f"❌ Произошла ошибка: {str(e)}")
