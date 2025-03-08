from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
)

from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter

router = Router()


async def admin_handler(message: Message, state: FSMContext):
    # Show admin options
    response = await ask_user_choice(
        message.chat.id,
        "Вы администратор бота. Что вы хотите сделать?",
        # todo: rework this?
        choices={
            "register": "Протестировать бота (обычный сценарий)",
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


@commands_menu.add_command("stats", "Статистика регистраций", visibility=Visibility.ADMIN_ONLY)
@router.message(Command("stats"), AdminFilter())
async def show_stats(message: Message):
    """Показать статистику регистраций"""
    from app.router import app
    from app.app import GRADUATE_TYPE_MAP, PAYMENT_STATUS_MAP

    # Initialize stats text
    stats_text = "<b>📊 Статистика регистраций</b>\n\n"

    # 1. Count registrations by city
    city_cursor = app.collection.aggregate([
        {"$group": {"_id": "$target_city", "count": {"$sum": 1}}}
    ])
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
    grad_cursor = app.collection.aggregate([
        {"$group": {"_id": "$graduate_type", "count": {"$sum": 1}}}
    ])
    grad_stats = await grad_cursor.to_list(length=None)

    stats_text += "<b>👥 По статусу:</b>\n"
    for stat in grad_stats:
        grad_type = stat["_id"] or "GRADUATE"  # Default to GRADUATE if None
        count = stat["count"]
        # Get singular form from map and make it plural by adding 'и' or 'я'
        singular = GRADUATE_TYPE_MAP.get(grad_type, grad_type)
        plural = singular + ("и" if singular.endswith("к") else "я")  # Add proper plural ending
        stats_text += f"• {plural}: <b>{count}</b>\n"
    stats_text += "\n"

    # 3. Payment statistics by city
    payment_cursor = app.collection.aggregate([
        {"$match": {"target_city": {"$ne": "Санкт-Петербург"}}},  # Exclude SPb as it's free
        {"$group": {
            "_id": "$target_city",
            "total_paid": {"$sum": {"$ifNull": ["$payment_amount", 0]}},
            "confirmed_count": {"$sum": {"$cond": [{"$eq": ["$payment_status", "confirmed"]}, 1, 0]}},
            "pending_count": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": ["$payment_status", "pending"]},
                ]}, 1, 0
            ]}},
            "declined_count": {"$sum": {"$cond": [{"$eq": ["$payment_status", "declined"]}, 1, 0]}},
            "unpaid_count": {"$sum": {"$cond": [
                {"$or": [
                    {"$eq": ["$payment_status", None]},
                    {"$eq": ["$payment_status", "Не оплачено"]}
                ]}, 1, 0
            ]}},
            "total_formula": {"$sum": {"$ifNull": ["$formula_payment_amount", 0]}},
            "total_regular": {"$sum": {"$ifNull": ["$regular_payment_amount", 0]}},
            "total_discounted": {"$sum": {"$ifNull": ["$discounted_payment_amount", 0]}}
        }}
    ])
    payment_stats = await payment_cursor.to_list(length=None)

    stats_text += "<b>💰 Статистика оплат:</b>\n"
    total_paid = 0
    total_formula = 0
    total_regular = 0
    total_discounted = 0

    for stat in payment_stats:
        city = stat["_id"]
        paid = stat["total_paid"]
        formula = stat["total_formula"]
        regular = stat["total_regular"]
        discounted = stat["total_discounted"]
        
        total_paid += paid
        total_formula += formula
        total_regular += regular
        total_discounted += discounted

        # Calculate percentage of various amounts collected
        pct_of_formula = (paid / formula * 100) if formula > 0 else 0
        pct_of_regular = (paid / regular * 100) if regular > 0 else 0
        pct_of_discounted = (paid / discounted * 100) if discounted > 0 else 0

        stats_text += f"\n<b>{city}:</b>\n"
        stats_text += f"💵 Собрано: <b>{paid:,}</b> руб.\n"
        stats_text += f"📊 % от формулы: <i>{pct_of_formula:.1f}%</i>\n"
        stats_text += f"📊 % от регулярной: <i>{pct_of_regular:.1f}%</i>\n"
        stats_text += f"📊 % от мин. со скидкой: <i>{pct_of_discounted:.1f}%</i>\n\n"
        
        # Payment status distribution
        stats_text += "<u>Статусы платежей:</u>\n"
        stats_text += f"✅ {PAYMENT_STATUS_MAP['confirmed']}: <b>{stat['confirmed_count']}</b>\n"
        stats_text += f"⏳ {PAYMENT_STATUS_MAP['pending']}: <b>{stat['pending_count']}</b>\n"
        stats_text += f"❌ {PAYMENT_STATUS_MAP['declined']}: <b>{stat['declined_count']}</b>\n"
        stats_text += f"⚪️ {PAYMENT_STATUS_MAP[None]}: <b>{stat['unpaid_count']}</b>\n"

    # Add totals
    if total_paid > 0:
        stats_text += f"\n<b>💵 Итого собрано: {total_paid:,} руб.</b>\n"
        total_pct_formula = (total_paid / total_formula * 100) if total_formula > 0 else 0
        total_pct_regular = (total_paid / total_regular * 100) if total_regular > 0 else 0
        total_pct_discounted = (total_paid / total_discounted * 100) if total_discounted > 0 else 0
        stats_text += f"📊 % от общей формулы: <i>{total_pct_formula:.1f}%</i>\n"
        stats_text += f"📊 % от общей регулярной: <i>{total_pct_regular:.1f}%</i>\n"
        stats_text += f"📊 % от общей мин. со скидкой: <i>{total_pct_discounted:.1f}%</i>\n"

    await send_safe(message.chat.id, stats_text)
