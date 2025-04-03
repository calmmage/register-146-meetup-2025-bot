from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from typing import Dict, Any

from app.routers.admin import router
from app.app import TargetCity
from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice, ask_user_confirmation, ask_user_raw
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter


def apply_message_templates(template: str, user_data: Dict[str, Any]) -> str:
    """
    Apply template substitutions to a message based on user data.
    
    Args:
        template: The message template containing placeholders
        user_data: Dictionary with user information
        
    Returns:
        Personalized message with replaced placeholders
    """
    from app.router import time_of_event, venue_of_event, address_of_event, padezhi
    
    # Extract user data
    user_name = user_data.get("full_name", "")
    user_city_value = user_data.get("target_city", "")
    user_year = user_data.get("graduation_year", "")
    user_class = user_data.get("class_letter", "")
    
    # Convert city string to enum for dictionary lookups
    city_enum = None
    for city_enum_value in TargetCity:
        if city_enum_value.value == user_city_value:
            city_enum = city_enum_value
            break
    
    # Get city-specific details
    user_city_padezh = padezhi.get(city_enum, user_city_value) if city_enum else "городе"
    user_address = address_of_event.get(city_enum, "Уточняется") if city_enum else "Уточняется"
    user_venue = venue_of_event.get(city_enum, "Уточняется") if city_enum else "Уточняется"
    user_time = time_of_event.get(city_enum, "Уточняется") if city_enum else "Уточняется"
    
    # Apply substitutions
    result = template
    result = result.replace("{name}", user_name)
    result = result.replace("{city}", user_city_value)
    result = result.replace("{city_padezh}", user_city_padezh)
    result = result.replace("{address}", user_address)
    result = result.replace("{venue}", user_venue)
    result = result.replace("{time}", user_time)
    result = result.replace("{year}", str(user_year))
    result = result.replace("{class}", str(user_class))
    
    return result


@commands_menu.add_command(
    "notify", "Отправить уведомление пользователям", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("notify"), AdminFilter())
async def notify_users_handler(message: Message, state: FSMContext):
    """Notify users with a custom message using a step-by-step flow without state management"""

    # Step 1: Select audience (unpaid, paid, or everybody)
    audience = await ask_user_choice(
        message.chat.id,
        "Шаг 1: Кому отправить уведомление?",
        choices={
            "unpaid": "Неоплатившим пользователям",
            "paid": "Оплатившим пользователям",
            "all": "Всем пользователям",
            "cancel": "Отмена",
        },
        state=state,
        timeout=None,
    )

    if audience == "cancel":
        await send_safe(message.chat.id, "Операция отменена")
        return

    # Step 2: Select city
    city = await ask_user_choice(
        message.chat.id,
        "Шаг 2: Выберите город для рассылки",
        choices={
            "MOSCOW": "Москва",
            "PERM": "Пермь",
            "SAINT_PETERSBURG": "Санкт-Петербург",
            "BELGRADE": "Белград",
            "all": "Все города",
            "cancel": "Отмена",
        },
        state=state,
        timeout=None,
    )

    if city == "cancel":
        await send_safe(message.chat.id, "Операция отменена")
        return

    # Step 3: Enter text to be sent
    response = await ask_user_raw(
        message.chat.id,
        "Шаг 3: Введите текст сообщения для отправки\n\n"
        "Доступные шаблоны для подстановки:\n"
        "- {name} - имя пользователя\n"
        "- {city} - название города\n"
        "- {city_padezh} - название города в предложном падеже (в Москве, в Перми)\n"
        "- {address} - адрес встречи\n"
        "- {venue} - место проведения\n"
        "- {time} - время начала\n"
        "- {year} - год выпуска\n"
        "- {class} - буква класса\n\n"
        "Поддерживается HTML форматирование",
        state=state,
        timeout=None,
    )
    notification_text = response.html_text

    if not notification_text or notification_text.lower() == "отмена":
        await send_safe(message.chat.id, "Операция отменена")
        return

    # Get user list based on audience and city
    from app.router import app

    # Show processing message
    status_msg = await send_safe(message.chat.id, "⏳ Получение списка пользователей...")

    # Get appropriate user list
    if audience == "unpaid":
        users = await app.get_unpaid_users(city if city != "all" else None)
        audience_name = "не оплативших пользователей"
    elif audience == "paid":
        users = await app.get_paid_users(city if city != "all" else None)
        audience_name = "оплативших пользователей"
    else:  # all
        users = await app.get_all_users(city if city != "all" else None)
        audience_name = "всех пользователей"

    # Check if we have users matching criteria
    if not users:
        await status_msg.edit_text("❌ Пользователи, соответствующие критериям, не найдены!")
        return

    # Format city for display
    city_name = {
        "MOSCOW": "Москве",
        "PERM": "Перми",
        "SAINT_PETERSBURG": "Санкт-Петербурге",
        "BELGRADE": "Белграде",
        "all": "всех городах",
    }.get(city, city)

    # Generate preview report
    preview = f"📊 Найдено {len(users)} {audience_name} в {city_name}:\n\n"

    # Show a preview of up to 10 users
    for i, user in enumerate(users[:10], 1):
        username = user.get("username", "без имени")
        user_id = user.get("user_id", "??")
        full_name = user.get("full_name", "Имя не указано")
        user_city = user.get("target_city", "Город не указан")

        preview += f"{i}. {full_name} (@{username or user_id})\n"
        preview += f"   🏙️ {user_city}\n"

    if len(users) > 10:
        preview += f"\n... и еще {len(users) - 10} пользователей"

    # Message preview with personalization example
    preview += "\n\n<b>Предварительный просмотр сообщения:</b>\n\n"
    preview += notification_text
    
    # Define all available template markers
    template_markers = ["{name}", "{city}", "{city_padezh}", "{address}", "{venue}", "{time}", "{year}", "{class}"]
    
    # If we have users and there are templates in the message, show a personalized example
    if users and any(marker in notification_text for marker in template_markers):
        example_user = users[0]  # Take the first user for the example
        
        # Create a personalized example using our utility function
        personalized_example = apply_message_templates(notification_text, example_user)
        
        preview += "\n\n<b>Пример персонализированного сообщения для пользователя:</b>\n"
        preview += f"<i>{example_user.get('full_name', '')}</i>\n\n"
        preview += personalized_example

    # Update status message with preview
    await status_msg.edit_text(preview)

    # Step 4: Ask for final confirmation
    confirm = await ask_user_confirmation(
        message.chat.id,
        f"Шаг 4: ⚠️ Вы собираетесь отправить сообщение {len(users)} пользователям. Продолжить?",
        state=state,
    )

    if not confirm:
        await send_safe(message.chat.id, "Операция отменена")
        return

    # Send notifications
    sent_count = 0
    failed_count = 0

    status_msg = await send_safe(message.chat.id, "⏳ Отправка уведомлений...")

    for user in users:
        user_id = user.get("user_id")
        if not user_id:
            failed_count += 1
            continue

        try:
            # Process templates for this user using our utility function
            personalized_text = apply_message_templates(notification_text, user)
            
            await send_safe(user_id, personalized_text)
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


@commands_menu.add_command(
    "test_user_selection", "Тест выборки пользователей", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("test_user_selection"), AdminFilter())
async def test_user_selection_handler(message: Message, state: FSMContext):
    """Test the user selection methods by reporting counts for each city and payment status"""
    from app.router import app

    # Show processing message
    status_msg = await send_safe(message.chat.id, "⏳ Тестирование выборки пользователей...")

    # Cities to test
    cities = ["MOSCOW", "PERM", "SAINT_PETERSBURG", "BELGRADE", "all"]

    # Initialize report
    report = "📊 <b>Результаты тестирования выборки пользователей:</b>\n\n"
    report += "<i>Примечание: Санкт-Петербург, Белград и учителя автоматически помечаются как оплатившие.</i>\n\n"

    # Get counts for all cities combined
    all_users = await app.get_all_users()
    all_paid = await app.get_paid_users()
    all_unpaid = await app.get_unpaid_users()

    report += f"<b>Все города:</b>\n"
    report += f"- Всего пользователей: {len(all_users)}\n"
    report += f"- Оплатившие: {len(all_paid)}\n"
    report += f"- Неоплатившие: {len(all_unpaid)}\n\n"

    # Get counts for each city
    for city in cities:
        if city == "all":
            continue  # Already handled above

        city_display = {
            "MOSCOW": "Москва",
            "PERM": "Пермь",
            "SAINT_PETERSBURG": "Санкт-Петербург",
            "BELGRADE": "Белград",
        }.get(city, city)

        city_all = await app.get_all_users(city)
        city_paid = await app.get_paid_users(city)
        city_unpaid = await app.get_unpaid_users(city)

        report += f"<b>{city_display}:</b>\n"
        report += f"- Всего пользователей: {len(city_all)}\n"
        report += f"- Оплатившие: {len(city_paid)}\n"
        report += f"- Неоплатившие: {len(city_unpaid)}\n\n"

    # Update status message with report
    await status_msg.edit_text(report, parse_mode="HTML")


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
    status_msg = await send_safe(message.chat.id, "⏳ Получение списка не оплативших...")

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

    # Send notifications with templating
    notification_text = (
        "🔔 <b>Напоминание о раннем платеже</b>\n\n"
        "Привет, {name}! Напоминаем, что до окончания периода ранней оплаты "
        "осталось совсем немного времени (до 15 марта 2025).\n\n"
        "Оплатив сейчас, ты получаешь скидку для участия в {city_padezh}:\n"
        "- Москва: 1000 руб.\n"
        "- Пермь: 500 руб.\n\n"
        "Место проведения: {venue}\n"
        "Адрес: {address}\n"
        "Время начала: {time}\n\n"
        "Чтобы оплатить, используй команду /pay"
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
            # Process templates for this user using our utility function
            personalized_text = apply_message_templates(notification_text, user)
            
            await send_safe(user_id, personalized_text)
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
