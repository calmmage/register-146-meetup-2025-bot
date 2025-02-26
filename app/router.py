from aiogram import Router, html, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardRemove
from dotenv import load_dotenv
from textwrap import dedent
from typing import Dict, List, Optional
from aiogram.types import Message as TelegramMessage

from app.app import App, TargetCity, RegisteredUser
from botspot import commands_menu
from botspot.core.dependency_manager import get_dependency_manager
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe, is_admin
from botspot.utils.admin_filter import AdminFilter

router = Router()
app = App()

# Load environment variables
load_dotenv()

# Dictionary to track log messages for each user
log_messages: Dict[int, List[TelegramMessage]] = {}

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
    
    registered_user = RegisteredUser(
        full_name=full_name,
        graduation_year=graduation_year,
        class_letter=class_letter,
        target_city=location,
    )

    # Save with user_id and username
    await app.save_registered_user(
        registered_user, user_id=message.from_user.id, username=message.from_user.username
    )

    # Log registration completion
    log_msg = await app.log_registration_step(
        user_id,
        username,
        "Регистрация завершена",
        f"Город: {location.value}, ФИО: {full_name}, Год: {graduation_year}, Класс: {class_letter}",
    )
    if log_msg:
        log_messages[user_id].append(log_msg)

    await send_safe(
        message.chat.id,
        f"Спасибо, {html.bold(full_name)}!\n"
        "Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}.",
        reply_markup=ReplyKeyboardRemove(),
    )

    # Log to events chat
    registration_data = {
        "full_name": full_name,
        "graduation_year": graduation_year,
        "class_letter": class_letter,
        "target_city": location.value,
    }
    await app.log_registration_complete(user_id, username, registration_data)

    # Delete all log messages for this user
    await delete_log_messages(user_id)


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
