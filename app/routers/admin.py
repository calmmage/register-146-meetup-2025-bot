import base64
import json
from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
)
from litellm import acompletion
from loguru import logger
from pydantic import BaseModel
from typing import Optional

from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice, ask_user_raw, ask_user_confirmation
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
            "register": "Протестировать бота (обычный сценарий)",
            "export": "Экспортировать данные",
            "view_stats": "Посмотреть статистику (подробно)",
            "view_simple_stats": "Посмотреть статистику (кратко)",
            "notify_early_payment": "Уведомить о раннем платеже",
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
    elif response == "notify_early_payment":
        await notify_early_payment_handler(message, state)
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
    "notify_early_payment", "Уведомить о раннем платеже", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("notify_early_payment"), AdminFilter())
async def notify_early_payment_handler(message: Message, state: FSMContext):
    """Notify users who haven't paid yet about the early payment deadline"""

    # Ask user for action choice
    response = await ask_user_choice(
        message.chat.id,
        "Что вы хотите сделать?",
        choices={
            "notify": "Отправить уведомления о раннем платеже",
            "dry_run": "Тестовый режим (показать список, но не отправлять)",
            "cancel": "Отмена",
        },
        state=state,
        timeout=None,
    )

    if response == "cancel":
        await send_safe(message.chat.id, "Операция отменена")
        return

    from app.router import app

    # Show processing message
    status_msg = await send_safe(message.chat.id, "⏳ Получение списка неоплативших...")

    # Get list of users who haven't paid
    unpaid_users = await app.get_unpaid_users()

    # Check if we have unpaid users
    if not unpaid_users:
        await status_msg.edit_text("✅ Все пользователи оплатили!")
        return

    # Generate report for both dry run and actual notification
    report = f"📊 Найдено {len(unpaid_users)} пользователей без оплаты:\n\n"

    for i, user in enumerate(unpaid_users, 1):
        username = user.get("username", "без имени")
        user_id = user.get("user_id", "??")
        full_name = user.get("full_name", "Имя не указано")
        city = user.get("target_city", "Город не указан")
        payment_status = user.get("payment_status", "Не оплачено")

        # Format payment status
        if payment_status == "pending":
            payment_status = "Оплачу позже"
        elif payment_status == "declined":
            payment_status = "Отклонено"
        else:
            payment_status = "Не оплачено"

        report += f"{i}. {full_name} (@{username or user_id})\n"
        report += f"   🏙️ {city}, 💰 {payment_status}\n\n"

    # Update status message with report
    await status_msg.edit_text(report)

    # For dry run, we're done
    if response == "dry_run":
        await send_safe(message.chat.id, "🔍 Тестовый режим завершен. Уведомления не отправлялись.")
        return

    # For actual notification, ask for confirmation
    confirm = await ask_user_confirmation(
        message.chat.id,
        f"⚠️ Вы собираетесь отправить уведомление {len(unpaid_users)} пользователям о раннем платеже. Продолжить?",
        state=state,
    )

    if not confirm:
        await send_safe(message.chat.id, "Операция отменена")
        return

    # Send notifications
    notification_text = (
        "🔔 <b>Напоминание о раннем платеже</b>\n\n"
        "Здравствуйте! Напоминаем, что до окончания периода ранней оплаты "
        "осталось совсем немного времени.\n\n"
        "Оплатив сейчас, вы получаете скидку:\n"
        "- Москва: 1000 руб.\n"
        "- Пермь: 500 руб.\n\n"
        "Чтобы оплатить, используйте команду /pay"
    )

    sent_count = 0
    failed_count = 0

    status_msg = await send_safe(message.chat.id, "⏳ Отправка уведомлений...")

    for user in unpaid_users:
        user_id = user.get("user_id")
        if not user_id:
            failed_count += 1
            continue

        try:
            await send_safe(user_id, notification_text)
            sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send notification to user {user_id}: {e}")
            failed_count += 1

    # Update status message with results
    result_text = (
        f"✅ Уведомления отправлены!\n\n"
        f"📊 Статистика:\n"
        f"- Успешно отправлено: {sent_count}\n"
        f"- Ошибок: {failed_count}"
    )

    await status_msg.edit_text(result_text)
