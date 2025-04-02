from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger

from app.routers.admin import router
from botspot import commands_menu
from botspot.components.qol.bot_commands_menu import Visibility
from botspot.user_interactions import ask_user_choice, ask_user_confirmation, ask_user_raw
from botspot.utils import send_safe
from botspot.utils.admin_filter import AdminFilter


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
            "moscow": "Москва",
            "perm": "Пермь",
            "all": "Оба города",
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
        "Шаг 3: Введите текст сообщения для отправки\n\n" "Поддерживается форматирование",
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
    city_name = {"moscow": "Москве", "perm": "Перми", "all": "обоих городах"}.get(city, city)

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

    # Message preview
    preview += "\n\n<b>Предварительный просмотр сообщения:</b>\n\n"
    preview += notification_text

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
        "Привет! Напоминаем, что до окончания периода ранней оплаты "
        "осталось совсем немного времени (до 15 марта 2025).\n\n"
        "Оплатив сейчас, ты получаешь скидку:\n"
        "- Москва: 1000 руб.\n"
        "- Пермь: 500 руб.\n\n"
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
