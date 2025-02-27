import asyncio
import os
from aiogram import Router, html, F
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
from datetime import datetime
from dotenv import load_dotenv
from loguru import logger
from textwrap import dedent
from typing import Dict, List

from app.app import App, TargetCity, RegisteredUser
from botspot import commands_menu
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe, is_admin
from botspot.utils.admin_filter import AdminFilter

router = Router()
app = App()

# Load environment variables
load_dotenv()

# Dictionary to track log messages for each user
log_messages: Dict[int, List[Message]] = {}

date_of_event = {
    TargetCity.PERM: "22 Марта, Сб",
    TargetCity.MOSCOW: "29 Марта, Сб",
    TargetCity.SAINT_PETERSBURG: "29 Марта, Сб",
}

padezhi = {
    TargetCity.PERM: "Перми",
    TargetCity.MOSCOW: "Москве",
    TargetCity.SAINT_PETERSBURG: "Санкт-Петербурге",
}

# Add payment QR codes and details
payment_details = {
    TargetCity.MOSCOW.value: {
        "card": "1234 5678 9012 3456",
        "name": "Иванов Иван Иванович",
        "qr_code": "moscow_payment_qr.png",
    },
    TargetCity.PERM.value: {
        "card": "9876 5432 1098 7654",
        "name": "Петров Петр Петрович",
        "qr_code": "perm_payment_qr.png",
    },
    TargetCity.SAINT_PETERSBURG.value: {
        "info": "Оплата не требуется. Все расходы участники несут самостоятельно."
    },
}

# Create directory for payment QR codes if it doesn't exist
os.makedirs(os.path.join("assets", "payment_qr"), exist_ok=True)


async def handle_registered_user(message: Message, state: FSMContext, registration):
    """Handle interaction with already registered user"""

    # Get all user registrations
    registrations = await app.get_user_registrations(message.from_user.id)

    if len(registrations) > 1:
        # User has multiple registrations
        info_text = "Вы зарегистрированы на встречи выпускников в нескольких городах:\n\n"

        for reg in registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)

            info_text += (
                f"• {city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'})\n"
            )
            info_text += f"  ФИО: {reg['full_name']}\n"
            info_text += (
                f"  Год выпуска: {reg['graduation_year']}, Класс: {reg['class_letter']}\n\n"
            )

        info_text += "Что вы хотите сделать?"

        response = await ask_user_choice(
            message.chat.id,
            info_text,
            choices={
                "register_another": "Зарегистрироваться в другом городе",
                "manage": "Управлять регистрациями",
                "nothing": "Ничего, всё в порядке",
            },
            state=state,
            timeout=None,
        )

        if response == "register_another":
            await register_user(message, state, reuse_info=registration)
        elif response == "manage":
            await manage_registrations(message, state, registrations)
        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваши регистрации в силе. До встречи!",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        # User has only one registration
        reg = registration
        city = reg["target_city"]
        city_enum = next((c for c in TargetCity if c.value == city), None)

        info_text = dedent(
            f"""
            Вы зарегистрированы на встречу выпускников:
            
            ФИО: {reg["full_name"]}
            Год выпуска: {reg["graduation_year"]}
            Класс: {reg["class_letter"]}
            Город: {city} ({date_of_event[city_enum] if city_enum else "дата неизвестна"})
            
            Что вы хотите сделать?
            """
        )

        response = await ask_user_choice(
            message.chat.id,
            info_text,
            choices={
                "change": "Изменить данные регистрации",
                "cancel": "Отменить регистрацию",
                "register_another": "Зарегистрироваться в другом городе",
                "nothing": "Ничего, всё в порядке",
            },
            state=state,
            timeout=None,
        )

        if response == "change":
            # Delete current registration and start new one
            await app.delete_user_registration(message.from_user.id, city)
            await send_safe(message.chat.id, "Давайте обновим вашу регистрацию.")
            await register_user(message, state)

        elif response == "cancel":
            # Delete registration
            await app.delete_user_registration(message.from_user.id, city)

            # Log cancellation
            await app.log_registration_canceled(
                message.from_user.id, message.from_user.username, city
            )

            await send_safe(
                message.chat.id,
                "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )

        elif response == "register_another":
            # Keep existing registration and start new one with reused info
            await send_safe(message.chat.id, "Давайте зарегистрируемся в другом городе.")
            await register_user(message, state, reuse_info=registration)

        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваша регистрация в силе. До встречи!",
                reply_markup=ReplyKeyboardRemove(),
            )


async def manage_registrations(message: Message, state: FSMContext, registrations):
    """Allow user to manage multiple registrations"""

    # Create choices for each city
    choices = {}
    for reg in registrations:
        city = reg["target_city"]
        choices[city] = f"Управлять регистрацией в городе {city}"

    choices["all"] = "Отменить все регистрации"
    choices["back"] = "Вернуться назад"

    response = await ask_user_choice(
        message.chat.id,
        "Выберите регистрацию для управления:",
        choices=choices,
        state=state,
        timeout=None,
    )

    if response == "all":
        # Confirm deletion of all registrations
        confirm = await ask_user_choice(
            message.chat.id,
            "Вы уверены, что хотите отменить ВСЕ регистрации?",
            choices={"yes": "Да, отменить все", "no": "Нет, вернуться назад"},
            state=state,
            timeout=None,
        )

        if confirm == "yes":
            await app.delete_user_registration(message.from_user.id)

            # Log cancellation of all registrations
            await app.log_registration_canceled(message.from_user.id, message.from_user.username)

            await send_safe(
                message.chat.id,
                "Все ваши регистрации отменены. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            # Go back to registration management
            await manage_registrations(message, state, registrations)

    elif response == "back":
        # Go back to main menu
        await handle_registered_user(message, state, registrations[0])

    else:
        # Manage specific city registration
        city = response
        reg = next(r for r in registrations if r["target_city"] == city)

        city_enum = next((c for c in TargetCity if c.value == city), None)

        info_text = dedent(
            f"""
            Регистрация в городе {city}:
            
            ФИО: {reg["full_name"]}
            Год выпуска: {reg["graduation_year"]}
            Класс: {reg["class_letter"]}
            Дата: {date_of_event[city_enum] if city_enum else "неизвестна"}
            
            Что вы хотите сделать?
            """
        )

        action = await ask_user_choice(
            message.chat.id,
            info_text,
            choices={
                "change": "Изменить данные",
                "cancel": "Отменить регистрацию",
                "back": "Вернуться назад",
            },
            state=state,
            timeout=None,
        )

        if action == "change":
            # Delete this registration and start new one
            await app.delete_user_registration(message.from_user.id, city)
            await send_safe(message.chat.id, f"Давайте обновим вашу регистрацию в городе {city}.")

            # Pre-select the city for the new registration
            await register_user(message, state, preselected_city=city)

        elif action == "cancel":
            # Delete this registration
            await app.delete_user_registration(message.from_user.id, city)

            # Log cancellation
            await app.log_registration_canceled(
                message.from_user.id, message.from_user.username, city
            )

            # Check if user has other registrations
            remaining = await app.get_user_registrations(message.from_user.id)

            if remaining:
                await send_safe(
                    message.chat.id,
                    f"Регистрация в городе {city} отменена. У вас остались другие регистрации.",
                )
                await handle_registered_user(message, state, remaining[0])
            else:
                await send_safe(
                    message.chat.id,
                    "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                    reply_markup=ReplyKeyboardRemove(),
                )

        else:  # "back"
            # Go back to registration management
            await manage_registrations(message, state, registrations)


async def register_user(
    message: Message, state: FSMContext, preselected_city=None, reuse_info=None
):
    """Register a user for an event"""
    user_id = message.from_user.id
    username = message.from_user.username

    # Initialize log messages list for this user if not exists
    if user_id not in log_messages:
        log_messages[user_id] = []

    # Log registration start
    log_msg = await app.log_registration_step(
        user_id,
        username,
        "Начало регистрации",
        f"Предвыбранный город: {preselected_city}, Повторное использование данных: {'Да' if reuse_info else 'Нет'}",
    )
    if log_msg:
        log_messages[user_id].append(log_msg)

    # Get existing registrations to avoid duplicates
    existing_registrations = await app.get_user_registrations(user_id)
    existing_cities = [reg["target_city"] for reg in existing_registrations]

    # step 1 - greet user, ask location
    location = None

    if preselected_city:
        # Use preselected city if provided
        location = next((c for c in TargetCity if c.value == preselected_city), None)

        # Log preselected city
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Выбор города",
            f"Предвыбранный город: {location.value if location else preselected_city}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    if not location:
        # Filter out cities the user is already registered for
        available_cities = {
            city.value: f"{city.value} ({date_of_event[city]})"
            for city in TargetCity
            if city.value not in existing_cities
        }

        # If no cities left, inform the user
        if not available_cities:
            await send_safe(
                message.chat.id,
                "Вы уже зарегистрированы на встречи во всех доступных городах!",
                reply_markup=ReplyKeyboardRemove(),
            )

            # Log no cities available
            log_msg = await app.log_registration_step(
                user_id,
                username,
                "Нет доступных городов",
                "Пользователь уже зарегистрирован во всех городах",
            )
            if log_msg:
                log_messages[user_id].append(log_msg)

            return

        question = dedent(
            """
            Выберите город, где планируете посетить встречу:
            """
        )

        response = await ask_user_choice(
            message.chat.id,
            question,
            choices=available_cities,
            state=state,
            timeout=None,
        )
        location = TargetCity(response)

        # Log city selection
        log_msg = await app.log_registration_step(
            user_id, username, "Выбор города", f"Выбранный город: {location.value}"
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # If we have info to reuse, skip asking for name and class
    if reuse_info:
        full_name = reuse_info["full_name"]
        graduation_year = reuse_info["graduation_year"]
        class_letter = reuse_info["class_letter"]

        # Confirm reusing the information
        confirm_text = dedent(
            f"""
            Хотите использовать те же данные для регистрации в городе {location.value}?
            
            ФИО: {full_name}
            Год выпуска: {graduation_year}
            Класс: {class_letter}
            """
        )

        confirm = await ask_user_choice(
            message.chat.id,
            confirm_text,
            choices={"yes": "Да, использовать эти данные", "no": "Нет, ввести новые данные"},
            state=state,
            timeout=None,
        )

        # Log reuse decision
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Повторное использование данных",
            f"Решение: {'Использовать существующие данные' if confirm == 'yes' else 'Ввести новые данные'}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

        if confirm == "no":
            # User wants to enter new info
            reuse_info = None

    # If not reusing info, ask for it
    if not reuse_info:
        # Ask for full name with validation
        full_name = None
        while full_name is None:
            question = dedent(
                """
                Как вас зовут?
                Пожалуйста, введите полное ФИО.
                """
            )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # Validate full name
            valid, error = app.validate_full_name(response)
            if valid:
                full_name = response
            else:
                await send_safe(message.chat.id, f"❌ {error} Пожалуйста, попробуйте еще раз.")

        # Log full name
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Ввод ФИО",
            f"ФИО: {full_name}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

        # Ask for graduation year and class letter with validation
        graduation_year = None
        class_letter = None

        while graduation_year is None or class_letter is None or not class_letter:
            if graduation_year is not None and class_letter is None:
                # We have a year but need a class letter
                question = "А букву класса?"
            else:
                question = dedent(
                    """
                    Пожалуйста, введите год выпуска и букву класса.
                    Например, "2025 Б".
                    """
                )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # If we already have a year and just need the letter
            if graduation_year is not None and class_letter is None:
                # Validate just the class letter
                valid, error = app.validate_class_letter(response)
                if valid:
                    class_letter = response.upper()
                else:
                    await send_safe(message.chat.id, f"❌ {error} Пожалуйста, попробуйте еще раз.")
            else:
                # Parse and validate both year and letter
                year, letter, error = app.parse_graduation_year_and_class_letter(response)

                if error:
                    await send_safe(message.chat.id, f"❌ {error}")
                    # If we got a valid year but no letter, save the year
                    if year is not None and letter == "":
                        graduation_year = year
                else:
                    graduation_year = year
                    class_letter = letter

        # Log graduation info
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Ввод года выпуска и класса",
            f"Год: {graduation_year}, Класс: {class_letter}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # Save the registration
    await app.save_registered_user(
        RegisteredUser(
            full_name=full_name,
            graduation_year=graduation_year,
            class_letter=class_letter,
            target_city=location,
        ),
        user_id=user_id,
        username=username,
    )

    # Log registration completion
    log_msg = await app.log_registration_step(
        user_id,
        username,
        "Регистрация завершена",
        f"Город: {location.value}, ФИО: {full_name}, Выпуск: {graduation_year} {class_letter}",
    )
    if log_msg:
        log_messages[user_id].append(log_msg)

    # Log to events chat
    await app.log_registration_completed(
        user_id, username, full_name, graduation_year, class_letter, location.value
    )

    # Clear log messages
    await delete_log_messages(user_id)

    # Send confirmation message with payment info in one message
    confirmation_msg = (
        f"Спасибо, {full_name}!\n"
        f"Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}. "
    )

    if location.value != TargetCity.SAINT_PETERSBURG.value:
        confirmation_msg += "Сейчас пришлем информацию об оплате..."
        await send_safe(message.chat.id, confirmation_msg)
        # Process payment after registration
        await process_payment(message, state, location.value, graduation_year)
    else:
        confirmation_msg += "\nДля встречи в Санкт-Петербурге оплата не требуется. Все расходы участники несут самостоятельно."
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )


# Add this function to delete log messages
async def delete_log_messages(user_id: int) -> None:
    """Delete all log messages for a user"""
    if user_id not in log_messages:
        return

    from botspot.core.dependency_manager import get_dependency_manager

    deps = get_dependency_manager()
    bot = deps.bot

    for msg in log_messages[user_id]:
        try:
            await bot.delete_message(chat_id=msg.chat.id, message_id=msg.message_id)
        except Exception as e:
            logger.error(f"Failed to delete log message: {e}")

    # Clear the list
    log_messages[user_id] = []


@commands_menu.add_command("export", "Экспорт списка зарегистрированных участников")
@router.message(AdminFilter(), Command("export"))
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

    if response == "sheets":
        # Export to Google Sheets
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


# General message handler for any text
@router.message(F.text)
async def general_message_handler(message: Message, state: FSMContext):
    """Handle any text message by routing to the start command"""
    await send_safe(
        message.chat.id, "Для регистрации или управления вашей записью используйте команду /start"
    )
    # Option 2: Uncomment to just run the basic flow for any message
    # await start_handler(message, state)


async def show_stats(message: Message):
    """Показать статистику регистраций"""
    # Count registrations by city
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


async def process_payment(message: Message, state: FSMContext, city: str, graduation_year: int):
    """Process payment for an event registration"""
    user_id = message.from_user.id
    username = message.from_user.username

    # Show typing status and delay
    try:
        from botspot.core.dependency_manager import get_dependency_manager

        deps = get_dependency_manager()
        if hasattr(deps, "bot"):
            bot = deps.bot
            await bot.send_chat_action(chat_id=message.chat.id, action="typing")
            await asyncio.sleep(3)  # 3 second delay
        else:
            logger.warning("Bot not available in dependency manager, skipping typing indicator")
            await asyncio.sleep(3)
    except Exception as e:
        logger.warning(f"Could not show typing indicator: {e}")
        await asyncio.sleep(3)

    # Check if it's an early registration (before March 15)
    early_registration_date = datetime.strptime("2025-03-15", "%Y-%m-%d")
    today = datetime.now()
    early_registration = today < early_registration_date

    # Calculate payment amount
    regular_amount, final_amount = app.calculate_payment_amount(
        city, graduation_year, early_registration
    )

    # Prepare payment message - split into parts for better UX
    payment_msg_part1 = dedent(
        f"""
        💰 Оплата мероприятия
        
        Для оплаты мероприятия используется следующая формула:
        
        Москва → 1000р + 200 * (2025 - год выпуска)
        Пермь → 500р + 100 * (2025 - год выпуска)
        Санкт-Петербург - за свой счет
    """
    )

    # Send part 1
    await send_safe(message.chat.id, payment_msg_part1)

    # Delay between messages
    await asyncio.sleep(10)

    # Prepare part 2 with payment calculation
    if early_registration:
        discount_amount = regular_amount - final_amount
        payment_msg_part2 = dedent(
            f"""
            Для вас минимальный взнос: {final_amount} руб.
            
            🎁 У вас ранняя регистрация (до 15 марта)!
            Скидка: {discount_amount} руб.
            
            А если перевести больше, то на мероприятие сможет прийти еще один первокурсник 😊
        """
        )
    else:
        payment_msg_part2 = dedent(
            f"""
            Для вас минимальный взнос: {final_amount} руб.
            
            А если перевести больше, то на мероприятие сможет прийти еще один первокурсник 😊
        """
        )

    # Send part 2
    await send_safe(message.chat.id, payment_msg_part2)

    # Delay between messages
    await asyncio.sleep(5)

    # Prepare part 3 with payment details
    payment_msg_part3 = dedent(
        f"""
        Реквизиты для оплаты:
        Карта: {payment_details[city]["card"]}
        Получатель: {payment_details[city]["name"]}
    """
    )

    # Send part 3
    await send_safe(message.chat.id, payment_msg_part3)

    # Delay between messages
    await asyncio.sleep(10)

    # Send QR code if available
    qr_path = os.path.join("assets", "payment_qr", payment_details[city]["qr_code"])
    if os.path.exists(qr_path):
        try:
            await send_safe(message.chat.id, "QR-код для оплаты:", file=FSInputFile(qr_path))
        except Exception as e:
            logger.warning(f"Could not send QR code: {e}")
            await send_safe(
                message.chat.id,
                "QR-код временно недоступен. Пожалуйста, используйте реквизиты выше.",
            )

    # Ask for payment confirmation
    await send_safe(
        message.chat.id,
        "Пожалуйста, отправьте скриншот подтверждения оплаты или нажмите кнопку ниже, если хотите оплатить позже.",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Оплачу позже")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )

    # For now, just assume the user will pay later
    logger.info(f"User {user_id} will pay later for {city}")

    # Save payment info with pending status
    await app.save_payment_info(user_id, city, final_amount)

    # Notify user
    await send_safe(
        message.chat.id,
        "Хорошо! Вы можете оплатить позже, используя команду /pay",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Log to events chat
    try:
        await app.log_payment_submission(
            user_id, username, registration, final_amount, regular_amount
        )
    except Exception as e:
        logger.warning(f"Could not log payment submission: {e}")


# Add payment command handler
@commands_menu.add_command("pay", "Оплатить участие")
@router.message(Command("pay"))
async def pay_handler(message: Message, state: FSMContext):
    """Handle payment for registered users"""
    user_id = message.from_user.id

    # Check if user is registered
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        await send_safe(
            message.chat.id,
            "Вы еще не зарегистрированы на встречу. Используйте /start для регистрации.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Filter registrations that require payment
    payment_registrations = [
        reg for reg in registrations if reg["target_city"] != TargetCity.SAINT_PETERSBURG.value
    ]

    if not payment_registrations:
        await send_safe(
            message.chat.id,
            "У вас нет регистраций, требующих оплаты.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # If user has multiple registrations requiring payment, ask which one to pay for
    if len(payment_registrations) > 1:
        choices = {}
        for reg in payment_registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)
            status = reg.get("payment_status", "не оплачено")
            status_emoji = "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"

            choices[city] = f"{city} ({date_of_event[city_enum]}) - {status_emoji} {status}"

        response = await ask_user_choice(
            message.chat.id,
            "У вас несколько регистраций. Для какого города вы хотите оплатить участие?",
            choices=choices,
            state=state,
            timeout=None,
        )

        # Find the selected registration
        selected_reg = next(
            (reg for reg in payment_registrations if reg["target_city"] == response), None
        )
    else:
        # Only one registration requiring payment
        selected_reg = payment_registrations[0]

    # Process payment for the selected registration
    await process_payment(
        message, state, selected_reg["target_city"], selected_reg["graduation_year"]
    )


# Add callback handlers for payment verification
@router.callback_query(lambda c: c.data and c.data.startswith("payment_"))
async def payment_verification_callback(callback_query: CallbackQuery, state: FSMContext):
    """Handle payment verification callbacks from admins"""
    # Extract data from callback
    parts = callback_query.data.split("_")
    action = parts[1]  # confirm, decline, or pending
    user_id = int(parts[2])
    city = parts[3]

    # Get the registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

    if not registration:
        await callback_query.answer("Регистрация не найдена")
        return

    admin_id = callback_query.from_user.id
    admin_username = callback_query.from_user.username

    # Check if user is admin
    if not is_admin(callback_query.from_user):
        await callback_query.answer("Только администраторы могут проверять платежи")
        return

    # Handle different actions
    if action == "confirm":
        # Confirm payment
        await app.update_payment_status(user_id, city, "confirmed")

        # Log confirmation
        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "confirmed",
            f"Подтверждено администратором {admin_username or admin_id}",
        )

        # Notify user
        await send_safe(
            user_id,
            f"✅ Ваш платеж для участия во встрече в городе {city} подтвержден! Спасибо за оплату.",
        )

        await callback_query.answer("Платеж подтвержден")

    elif action == "decline":
        # Ask admin for reason
        await callback_query.answer("Укажите причину отклонения")

        # Store callback data in state for later use
        await state.update_data(payment_decline_user_id=user_id, payment_decline_city=city)

        # Ask for reason in private chat with admin
        await send_safe(
            admin_id,
            f"Укажите причину отклонения платежа для пользователя {registration.get('username', user_id)} ({registration['full_name']}):",
        )

        # Set state to wait for reason
        await state.set_state("waiting_for_payment_decline_reason")

    elif action == "pending":
        # Mark as pending for further review
        await app.update_payment_status(user_id, city, "pending")

        # Log pending status
        await app.log_payment_verification(
            user_id,
            registration.get("username", ""),
            registration,
            "pending",
            f"Отложено администратором {admin_username or admin_id}",
        )

        # Notify user
        await send_safe(
            user_id,
            f"⏳ Ваш платеж для участия во встрече в городе {city} находится на проверке. Мы свяжемся с вами, если потребуется дополнительная информация.",
        )

        await callback_query.answer("Платеж отмечен как требующий дополнительной проверки")

    # Update the inline keyboard to reflect the action
    await callback_query.message.edit_reply_markup(
        InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"✅ Платеж {action}ed администратором {admin_username or admin_id}",
                        callback_data="payment_done",
                    )
                ]
            ]
        )
    )


# Handler for payment decline reason
@router.message(lambda message: message.text and message.chat.type == "private")
async def payment_decline_reason_handler(message: Message, state: FSMContext):
    """Handle payment decline reason from admin"""
    # Check if we're waiting for a decline reason
    current_state = await state.get_state()
    if current_state != "waiting_for_payment_decline_reason":
        return

    # Get stored data
    data = await state.get_data()
    user_id = data.get("payment_decline_user_id")
    city = data.get("payment_decline_city")

    if not user_id or not city:
        await send_safe(message.chat.id, "Ошибка: данные о платеже не найдены")
        await state.clear()
        return

    # Get the registration
    registration = await app.collection.find_one({"user_id": user_id, "target_city": city})

    if not registration:
        await send_safe(message.chat.id, "Ошибка: регистрация не найдена")
        await state.clear()
        return

    # Update payment status with reason
    reason = message.text
    await app.update_payment_status(user_id, city, "declined", reason)

    # Log decline
    await app.log_payment_verification(
        user_id, registration.get("username", ""), registration, "declined", reason
    )

    # Notify user
    await send_safe(
        user_id,
        f"❌ Ваш платеж для участия во встрече в городе {city} отклонен.\n\nПричина: {reason}\n\nПожалуйста, используйте команду /pay чтобы повторить попытку оплаты.",
    )

    # Confirm to admin
    await send_safe(
        message.chat.id,
        f"Платеж отклонен. Пользователь {registration.get('username', user_id)} ({registration['full_name']}) уведомлен.",
    )

    # Clear state
    await state.clear()


@commands_menu.add_command("start", "Start the bot")
@router.message(CommandStart())
@router.message(F.text, F.chat.type == "private")  # only handle private messages
async def start_handler(message: Message, state: FSMContext):
    """
    Main scenario flow.
    """

    if is_admin(message.from_user):
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
            return
        elif response == "view_stats":
            await show_stats(message)
            return
        # For "register", continue with normal flow

    # Check if user is already registered
    existing_registration = await app.get_user_registration(message.from_user.id)

    if existing_registration:
        # User is already registered, show options
        await handle_registered_user(message, state, existing_registration)
    else:
        # New user, start registration
        await register_user(message, state)
