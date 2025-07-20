from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from typing import Dict, Any

from app.routers.admin import router
from app.app import TargetCity, App
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
    from app.router import time_of_event, venue_of_event, address_of_event, padezhi, date_of_event

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
    user_date = date_of_event.get(city_enum, "Уточняется") if city_enum else "Уточняется"

    # Apply substitutions
    result = template
    result = result.replace("{name}", user_name)
    result = result.replace("{city}", user_city_value)
    result = result.replace("{city_padezh}", user_city_padezh)
    result = result.replace("{address}", user_address)
    result = result.replace("{venue}", user_venue)
    result = result.replace("{date}", user_date)
    result = result.replace("{time}", user_time)
    result = result.replace("{year}", str(user_year))
    result = result.replace("{class}", str(user_class))

    return result


@commands_menu.add_command(
    "notify", "Отправить уведомление пользователям", visibility=Visibility.ADMIN_ONLY
)
@router.message(Command("notify"), AdminFilter())
async def notify_users_handler(message: Message, state: FSMContext, app: App):
    """Notify users with a custom message using a step-by-step flow without state management"""
    if not message.from_user:
        await send_safe(message.chat.id, "❌ Ошибка: не удалось определить отправителя")
        return

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
    # Only show enabled cities
    city_choices = {
        "all": "Все города",
        "cancel": "Отмена",
    }
    
    # Add enabled cities only by looping through TargetCity enum
    for city_enum in TargetCity:
        if app.is_city_enabled(city_enum.value):
            # Convert enum name to choice key (e.g., PERM_SUMMER_2025 -> PERM_SUMMER_2025)
            city_key = city_enum.name
            city_choices[city_key] = city_enum.value
    
    city = await ask_user_choice(
        message.chat.id,
        "Шаг 2: Выберите город для рассылки",
        choices=city_choices,
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

    if not response or not response.html_text:
        await send_safe(message.chat.id, "Операция отменена")
        return

    notification_text = response.html_text

    if notification_text.lower() == "отмена":
        await send_safe(message.chat.id, "Операция отменена")
        return

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
    }.get(city or "", city or "")

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
    template_markers = [
        "{name}",
        "{city}",
        "{city_padezh}",
        "{address}",
        "{venue}",
        "{time}",
        "{year}",
        "{class}",
    ]

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

    # First send a detailed report to the validation chat
    validation_report = f"📢 <b>МАССОВАЯ РАССЫЛКА ЗАПУЩЕНА</b>\n\n"
    validation_report += f"👤 Инициатор: {message.from_user.username or message.from_user.id}\n"
    validation_report += f"🎯 Целевая аудитория: {len(users)} пользователей\n"
    validation_report += f"🏙️ Город: {city_name}\n"
    validation_report += f"💰 Категория: {audience_name}\n\n"
    validation_report += f"🗒️ <b>Список получателей:</b>\n"

    # Add a list of users (limited to avoid oversized message)
    for i, user in enumerate(users[:20], 1):
        username = user.get("username", "без имени")
        user_id = user.get("user_id", "??")
        full_name = user.get("full_name", "Имя не указано")
        city = user.get("target_city", "Город не указан")
        validation_report += f"{i}. {full_name} (@{username or user_id}) - {city}\n"

    if len(users) > 20:
        validation_report += f"...и еще {len(users) - 20} пользователей\n"

    # Add template text to the report
    validation_report += f"\n📋 <b>Шаблон сообщения:</b>\n"
    validation_report += notification_text

    # Send report to validation chat before starting the actual notifications
    await app.log_to_chat(validation_report, "events")

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

            # Notify validation chat about sent message
            validation_message = (
                f"✅ Уведомление отправлено пользователю {user.get('full_name')} "
                f"(@{user.get('username') or user_id})\n🏙️ "
                f"{user.get('target_city', 'Город не указан')}"
            )
            await app.log_to_chat(validation_message, "events")
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
async def test_user_selection_handler(message: Message, state: FSMContext, app: App):
    """Test the user selection methods by reporting counts for each city and payment status"""

    # Show processing message
    status_msg = await send_safe(message.chat.id, "⏳ Тестирование выборки пользователей...")

    # Cities to test
    cities = ["MOSCOW", "PERM", "SAINT_PETERSBURG", "BELGRADE", "PERM_SUMMER_2025", "all"]

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
            "PERM_SUMMER_2025": "Пермь (Летняя встреча 2025)",
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
async def notify_early_payment_handler(message: Message, state: FSMContext, app: App):
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

    # First send a detailed report to the validation chat
    validation_report = f"📢 <b>МАССОВАЯ РАССЫЛКА ЗАПУЩЕНА</b>\n\n"
    if message.from_user:
        validation_report += f"👤 Инициатор: {message.from_user.username or message.from_user.id}\n"
    else:
        validation_report += f"👤 Инициатор: Неизвестно\n"
    validation_report += f"🎯 Целевая аудитория: {len(unpaid_users)} пользователей без оплаты\n\n"
    validation_report += f"🗒️ <b>Список получателей:</b>\n"

    # Add a list of users (limited to avoid oversized message)
    for i, user in enumerate(unpaid_users[:20], 1):
        username = user.get("username", "без имени")
        user_id = user.get("user_id", "??")
        full_name = user.get("full_name", "Имя не указано")
        city = user.get("target_city", "Город не указан")
        validation_report += f"{i}. {full_name} (@{username or user_id}) - {city}\n"

    if len(unpaid_users) > 20:
        validation_report += f"...и еще {len(unpaid_users) - 20} пользователей\n"

    # Add template text to the report
    validation_report += f"\n📋 <b>Шаблон сообщения:</b>\n"
    template_text = (
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
    validation_report += template_text

    # Send report to validation chat before starting the actual notifications
    await app.log_to_chat(validation_report, "events")

    # Then use the same template for the actual notifications
    notification_text = template_text

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

            # Notify validation chat about sent message
            validation_message = (
                f"✅ Уведомление отправлено пользователю {user.get('full_name')} "
                f"(@{user.get('username') or user_id})\n🏙️ "
                f"{user.get('target_city', 'Город не указан')}"
            )
            await app.log_to_chat(validation_message, "events")
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


# @commands_menu.add_command(
#     "send_feedback_request", "Отправить запрос на обратную связь", visibility=Visibility.ADMIN_ONLY
# )
# @router.message(Command("send_feedback_request"), AdminFilter())
# async def send_feedback_request_handler(message: Message, state: FSMContext):
#     """Send feedback request messages to users"""
#     if not message.from_user:
#         await send_safe(message.chat.id, "❌ Ошибка: не удалось определить отправителя")
#         return

#     # Step 1: Select city
#     city = await ask_user_choice(
#         message.chat.id,
#         "Шаг 1: Выберите город, по которому хотите запросить обратную связь:",
#         choices={
#             "MOSCOW": "Москва",
#             "PERM": "Пермь",
#             "SAINT_PETERSBURG": "Санкт-Петербург",
#             "BELGRADE": "Белград",
#             "all": "Все города",
#             "cancel": "Отмена",
#         },
#         state=state,
#         timeout=None,
#     )

#     if city == "cancel":
#         await send_safe(message.chat.id, "Операция отменена")
#         return

#     # Step 2: Ask if this is a test or production run
#     run_type = await ask_user_choice(
#         message.chat.id,
#         "Шаг 2: Это тестовый запуск или боевой?",
#         choices={
#             "test": "Тестовый (отправить только себе)",
#             "prod": "Боевой (отправить всем пользователям)",
#             "cancel": "Отмена",
#         },
#         state=state,
#         timeout=None,
#     )

#     if run_type == "cancel":
#         await send_safe(message.chat.id, "Операция отменена")
#         return

#     # Show processing message
#     status_msg = await send_safe(message.chat.id, "⏳ Получение списка пользователей...")

#     # Get city-specific details and dates for messages
#     city_display_name = {
#         "MOSCOW": "Москве",
#         "PERM": "Перми",
#         "SAINT_PETERSBURG": "Санкт-Петербурге",
#         "BELGRADE": "Белграде",
#         "all": "разных городах",
#     }.get(city or "", city or "")

#     target_users = []

#     if run_type == "test":
#         # Just the admin for test run
#         admin_data = {
#             "user_id": message.from_user.id,
#             "username": message.from_user.username,
#             "full_name": message.from_user.full_name,
#             "target_city": city if city != "all" else "MOSCOW",  # Default to Moscow for test
#         }
#         target_users = [admin_data]
#     else:
#         # Real users for production run
#         target_users = await app.get_users_without_feedback(city if city != "all" else None)

#     # Check if we have users matching criteria
#     if not target_users:
#         await status_msg.edit_text("❌ Пользователи, соответствующие критериям, не найдены!")
#         return

#     # Generate preview report
#     preview = f"📊 Найдено {len(target_users)} пользователей для отправки запроса обратной связи по {city_display_name}:\n\n"

#     # Show a preview of up to 10 users
#     for i, user in enumerate(target_users[:10], 1):
#         username = user.get("username", "без имени")
#         user_id = user.get("user_id", "??")
#         full_name = user.get("full_name", "Имя не указано")
#         user_city = user.get("target_city", "Город не указан")

#         preview += f"{i}. {full_name} (@{username or user_id})\n"
#         preview += f"   🏙️ {user_city}\n"

#     if len(target_users) > 10:
#         preview += f"\n... и еще {len(target_users) - 10} пользователей"

#     # Update status message with preview
#     await status_msg.edit_text(preview)

#     # Step 3: Ask for confirmation
#     confirm = await ask_user_confirmation(
#         message.chat.id,
#         f"Шаг 3: ⚠️ Вы собираетесь отправить запрос обратной связи {len(target_users)} пользователям. Продолжить?",
#         state=state,
#     )

#     if not confirm:
#         await send_safe(message.chat.id, "Операция отменена")
#         return

#     # First send a detailed report to the validation chat
#     validation_report = f"📢 <b>МАССОВАЯ РАССЫЛКА ЗАПРОСОВ ОБРАТНОЙ СВЯЗИ ЗАПУЩЕНА</b>\n\n"
#     validation_report += f"👤 Инициатор: {message.from_user.username or message.from_user.id}\n"
#     validation_report += f"🎯 Целевая аудитория: {len(target_users)} пользователей в {city_display_name}\n"
#     validation_report += f"🚀 Режим запуска: {'Тестовый' if run_type == 'test' else 'Боевой'}\n\n"
#     validation_report += f"🗒️ <b>Список получателей:</b>\n"

#     # Add a list of users (limited to avoid oversized message)
#     for i, user in enumerate(target_users[:20], 1):
#         username = user.get("username", "без имени")
#         user_id = user.get("user_id", "??")
#         full_name = user.get("full_name", "Имя не указано")
#         user_city = user.get("target_city", "Город не указан")
#         validation_report += f"{i}. {full_name} (@{username or user_id}) - {user_city}\n"

#     if len(target_users) > 20:
#         validation_report += f"...и еще {len(target_users) - 20} пользователей\n"

#     # Send report to validation chat before starting the actual messages
#     await app.log_to_chat(validation_report, "events")

#     # Start sending the messages
#     sent_count = 0
#     failed_count = 0

#     status_msg = await send_safe(message.chat.id, "⏳ Отправка запросов обратной связи...")

#     from botspot.core.dependency_manager import get_dependency_manager
#     deps = get_dependency_manager()
#     bot = deps.bot

#     for user in target_users:
#         user_id = user.get("user_id")
#         if not user_id:
#             failed_count += 1
#             continue

#         try:
#             # Get city-specific information
#             user_city = user.get("target_city")
#             user_city_enum = None
#             for city_enum_value in TargetCity:
#                 if city_enum_value.value == user_city:
#                     user_city_enum = city_enum_value
#                     break

#             city_name = user_city if user_city else "вашем городе"
#             city_date = date_of_event.get(user_city_enum, "недавно") if user_city_enum else "недавно"
#             day_of_week = ""

#             if "Марта" in city_date:
#                 day_of_week = "субботу"
#             elif "Апреля" in city_date:
#                 day_of_week = "субботу"

#             # Personalize the initial message (from Petr Lavrov)
#             initial_message = (
#                 f"Привет! Как тебе встреча выпускников в {city_name}? Было классно что получилось добраться. "
#                 f"У меня к сожалению не получилось приехать, но очень радостно на сердце что такие встречи реальны."
#             )

#             # Send the initial message as if from Petr
#             await send_safe(user_id, initial_message, parse_mode="HTML")

#             # Wait 30 seconds to simulate natural delay
#             await asyncio.sleep(30)

#             # Send photo link message
#             photo_links_message = (
#                 "Вот кстати ссылки на альбомы встреч в каждой локации:\n"
#                 "Пермь: ХХХ\n"
#                 "Москва: ХХХ\n"
#                 "Питер: ХХХ"
#             )

#             await send_safe(user_id, photo_links_message)

#             # Wait 2 minutes (120 seconds)
#             await asyncio.sleep(120)

#             # Send the request for feedback message
#             feedback_request = (
#                 "Как думаешь, удобно ли бы тебе было нам дать обратную связь по тому как прошло, "
#                 "чтобы мы в следующий раз еще лучше сделали? Я тебе сейчас через чат-бот сделаю запрос, если удобно - ответь пожалуйста."
#             )

#             await send_safe(user_id, feedback_request)

#             # Wait 3 minutes (180 seconds) before the bot sends its message
#             await asyncio.sleep(180)

#             # Final feedback bot message with correct city and date
#             feedback_bot_message = (
#                 f"Я чат-бот, собираю обратную связь по встрече в {city_name} в {day_of_week}, {city_date}. "
#                 f"Благодаря в том числе и твоей обратной связи мы продолжаем улучшать наши мероприятия, "
#                 f"помоги нам пожалуйста, потрать 4 минуты.\n\n"
#                 f"Пожалуйста, используй команду /feedback чтобы оставить обратную связь."
#             )

#             await send_safe(user_id, feedback_bot_message)

#             sent_count += 1

#             # Notify validation chat about sent message sequence
#             validation_message = f"✅ Запрос обратной связи отправлен пользователю {user.get('full_name')} (@{user.get('username') or user_id})\n🏙️ {user.get('target_city', 'Город не указан')}"
#             await app.log_to_chat(validation_message, "events")

#         except Exception as e:
#             logger.error(f"Failed to send feedback request to user {user_id}: {e}")
#             failed_count += 1

#             # Log error to validation chat
#             error_message = f"❌ Ошибка отправки запроса обратной связи пользователю {user.get('full_name')} (@{user.get('username') or user_id}): {str(e)}"
#             await app.log_to_chat(error_message, "errors")

#     # Update status message with results
#     result_text = (
#         f"✅ Запросы обратной связи отправлены!\n\n"
#         f"📊 Статистика:\n"
#         f"- Успешно отправлено: {sent_count}\n"
#         f"- Ошибок: {failed_count}"
#     )

#     await status_msg.edit_text(result_text)
