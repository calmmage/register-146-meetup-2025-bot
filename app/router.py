from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    ReplyKeyboardRemove,
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from aiogram.fsm.state import State, StatesGroup
from dotenv import load_dotenv
from loguru import logger
from textwrap import dedent
from typing import Dict, List
from datetime import datetime

from app.app import App, TargetCity, RegisteredUser, GraduateType
from app.routers.admin import admin_handler
from botspot import commands_menu
from botspot.user_interactions import ask_user, ask_user_choice
from botspot.utils import send_safe, is_admin

router = Router()

# Load environment variables
load_dotenv()

# Dictionary to track log messages for each user
log_messages: Dict[int, List[Message]] = {}

date_of_event = {
    TargetCity.PERM: "29 Марта, Сб",
    TargetCity.MOSCOW: "5 Апреля, Сб",
    TargetCity.SAINT_PETERSBURG: "5 Апреля, Сб",
    TargetCity.BELGRADE: "5 Апреля, Сб",
    TargetCity.PERM_SUMMER_2025: "2 Августа, Сб",
}

# Add event dates in datetime format for comparison
event_dates = {
    TargetCity.PERM: datetime(2025, 3, 29),
    TargetCity.MOSCOW: datetime(2025, 4, 5),
    TargetCity.SAINT_PETERSBURG: datetime(2025, 4, 5),
    TargetCity.BELGRADE: datetime(2025, 4, 5),
    TargetCity.PERM_SUMMER_2025: datetime(2025, 8, 2),
}


def is_event_passed(city: TargetCity) -> bool:
    """Check if the event for a given city has already passed"""
    today = datetime.now()
    return today > event_dates[city]


time_of_event = {
    TargetCity.PERM: "17:00",
    TargetCity.MOSCOW: "18:00",
    TargetCity.SAINT_PETERSBURG: "17:00",
    TargetCity.BELGRADE: "Уточняется",  # Предположительно
    TargetCity.PERM_SUMMER_2025: "18:00-24:00",
}

venue_of_event = {
    TargetCity.PERM: "Пермское бистро",
    TargetCity.MOSCOW: "People Loft",
    TargetCity.SAINT_PETERSBURG: "Family Loft",
    TargetCity.BELGRADE: "Уточняется",
    TargetCity.PERM_SUMMER_2025: "База \"Чайка\", Беседка 11",
}

address_of_event = {
    TargetCity.PERM: "ул. Сибирская, 8",
    TargetCity.MOSCOW: "1-я ул. Энтузиастов, 12, метро Авиамоторная",
    TargetCity.SAINT_PETERSBURG: "Кожевенная линия, 34, Метро горный институт",
    TargetCity.BELGRADE: "Уточняется",
    TargetCity.PERM_SUMMER_2025: "г. Пермь, ул. Встречная 33",
}

padezhi = {
    TargetCity.PERM: "Перми",
    TargetCity.MOSCOW: "Москве",
    TargetCity.SAINT_PETERSBURG: "Санкт-Петербурге",
    TargetCity.BELGRADE: "Белграде",
    TargetCity.PERM_SUMMER_2025: "Перми",
}


async def handle_registered_user(message: Message, state: FSMContext, registration, app: App):
    """Handle interaction with already registered user"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Get all user registrations
    registrations = await app.get_user_registrations(message.from_user.id)

    # We always want to show the same consistent menu regardless of payment status
    # No special case for unpaid registration - everything is handled in the same interface

    if len(registrations) > 1:
        # User has multiple registrations
        info_text = "Вы зарегистрированы на встречи выпускников в нескольких городах:\n\n"

        for reg in registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)

            # Add payment status indicator
            payment_status = ""
            if city != TargetCity.SAINT_PETERSBURG.value and city != TargetCity.BELGRADE.value:
                status = reg.get("payment_status", "не оплачено")
                status_emoji = (
                    "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"
                )
                payment_status = f" - {status_emoji} {status}"

            info_text += f"• {city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'}){payment_status}\n"
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
            await register_user(message, state, app, reuse_info=registration)
        elif response == "manage":
            await manage_registrations(message, state, registrations, app)
        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваши регистрации в силе. До встречи!\n\n"
                "Используйте команду /info для получения подробной информации о встречах (дата, время, адрес).",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        # User has only one registration
        reg = registration
        city = reg["target_city"]
        full_name = reg["full_name"]
        graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

        city_enum = next((c for c in TargetCity if c.value == city), None)

        # Check if payment is needed and not confirmed
        needs_payment = False
        if (
            city != TargetCity.SAINT_PETERSBURG.value
            and city != TargetCity.BELGRADE.value
            and graduate_type != GraduateType.TEACHER.value
            and graduate_type != GraduateType.ORGANIZER.value
            and reg.get("payment_status") != "confirmed"
        ):
            needs_payment = True

        # Payment status display
        payment_status = ""
        if (
            city != TargetCity.SAINT_PETERSBURG.value
            and city != TargetCity.BELGRADE.value
            and graduate_type != GraduateType.TEACHER.value
            and graduate_type != GraduateType.ORGANIZER.value
        ):
            status = reg.get("payment_status", "не оплачено")
            status_emoji = "✅" if status == "confirmed" else "❌" if status == "declined" else "⏳"
            payment_status = f"Статус оплаты: {status_emoji} {status}\n"

        info_text = dedent(
            f"""
            Вы зарегистрированы на встречу выпускников:
            
            ФИО: {reg["full_name"]}
            """
        )

        # Show different info based on graduate type
        if graduate_type == GraduateType.TEACHER.value:
            info_text += "Статус: Учитель\n"
        elif graduate_type == GraduateType.NON_GRADUATE.value:
            info_text += "Статус: Не выпускник\n"
        elif graduate_type == GraduateType.ORGANIZER.value:
            info_text += "Статус: Организатор\n"
        else:
            info_text += f"Год выпуска: {reg['graduation_year']}\n"
            info_text += f"Класс: {reg['class_letter']}\n"

        info_text += (
            f"Город: {city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'})\n"
        )
        info_text += payment_status
        info_text += "\nЧто вы хотите сделать?"

        choices = {}
        if needs_payment:
            choices["pay"] = "Оплатить участие"

        # Prepare choices for the menu
        choices.update(
            {
                "register_another": "Зарегистрироваться в другом городе",
                "cancel": "Отменить регистрацию",
            }
        )

        # Add payment option if needed

        choices["nothing"] = "Ничего, всё в порядке"

        response = await ask_user_choice(
            message.chat.id,
            info_text,
            choices=choices,
            state=state,
            timeout=None,
        )

        # Log single registration action choice
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {
                    "button": response,
                    "context": "single_registration_menu",
                    "city": city,
                    "needs_payment": needs_payment,
                    "payment_status": reg.get("payment_status"),
                },
                message.from_user.id,
                message.from_user.username,
            )

        if response == "cancel":
            await cancel_registration_handler(message, state, app)

        elif response == "pay":
            # Process payment for this registration
            from app.routers.payment import process_payment

            # Store the original user information in the state
            await state.update_data(
                original_user_id=message.from_user.id, original_username=message.from_user.username
            )

            # Get graduation year and graduate type
            graduation_year = reg["graduation_year"]
            graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

            # Process payment
            skip_instructions = reg.get("payment_status") is not None  # Skip if already seen
            await process_payment(
                message,
                state,
                city,
                graduation_year,
                skip_instructions,
                graduate_type=graduate_type,
            )

        elif response == "register_another":
            # Keep existing registration and start new one with reused info
            await send_safe(message.chat.id, "Давайте зарегистрируемся в другом городе.")
            await register_user(message, state, app, reuse_info=registration)

        else:  # "nothing"
            await send_safe(
                message.chat.id,
                "Отлично! Ваша регистрация в силе. До встречи!\n\nИспользуйте команду /info для получения подробной информации о встречах (дата, время, адрес).",
                reply_markup=ReplyKeyboardRemove(),
            )


async def manage_registrations(message: Message, state: FSMContext, registrations, app: App):
    """Allow user to manage multiple registrations"""
    assert message.from_user is not None

    # Create choices for each city
    choices = {}
    for reg in registrations:
        city = reg["target_city"]
        choices[city] = f"Управлять регистрацией в городе {city}"

    choices["all"] = "Отменить все регистрации"
    choices["back"] = "Вернуться назад"

    # Log entering registration management
    if message.from_user:
        await app.save_event_log(
            "navigation",
            {
                "action": "enter_registration_management",
                "cities": [reg["target_city"] for reg in registrations],
            },
            message.from_user.id,
            message.from_user.username,
        )

    response = await ask_user_choice(
        message.chat.id,
        "Выберите регистрацию для управления:",
        choices=choices,
        state=state,
        timeout=None,
    )

    # Log button click
    if message.from_user:
        await app.save_event_log(
            "button_click",
            {
                "button": response,
                "context": "registration_management",
                "cities": [reg["target_city"] for reg in registrations],
            },
            message.from_user.id,
            message.from_user.username,
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

        # Log confirmation button click
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {"button": confirm, "context": "confirm_delete_all_registrations"},
                message.from_user.id,
                message.from_user.username,
            )

        if confirm == "yes":
            await app.delete_user_registration(message.from_user.id)

            # Log cancellation of all registrations
            # Get user info for logging
            user_reg = await app.get_user_registration(message.from_user.id)
            full_name = user_reg.get("full_name", "Unknown") if user_reg else "Unknown"
            city = "все города"  # All cities

            await app.log_registration_canceled(
                message.from_user.id, message.from_user.username or "", full_name, city
            )

            await send_safe(
                message.chat.id,
                "Все ваши регистрации отменены. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            # Go back to registration management
            await manage_registrations(message, state, registrations, app)

    elif response == "back":
        # Go back to main menu
        await handle_registered_user(message, state, registrations[0], app)

    else:
        # Manage specific city registration
        city = response
        assert city is not None
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
                "cancel": "Отменить регистрацию",
                "back": "Вернуться назад",
            },
            state=state,
            timeout=None,
        )

        # Log city-specific action
        if message.from_user:
            await app.save_event_log(
                "button_click",
                {"button": action, "context": "city_registration_management", "city": city},
                message.from_user.id,
                message.from_user.username,
            )

        if action == "cancel":
            # Delete this registration
            await app.delete_user_registration(message.from_user.id, city)

            # Log cancellation
            await app.log_registration_canceled(
                message.from_user.id,
                message.from_user.username or "",
                reg.get("full_name", "Unknown"),
                city,
            )

            # Check if user has other registrations
            remaining = await app.get_user_registrations(message.from_user.id)

            if remaining:
                await send_safe(
                    message.chat.id,
                    f"Регистрация в городе {city} отменена. У вас остались другие регистрации.",
                )
                await handle_registered_user(message, state, remaining[0], app)
            else:
                await send_safe(
                    message.chat.id,
                    "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                    reply_markup=ReplyKeyboardRemove(),
                )

        else:  # "back"
            # Go back to registration management
            await manage_registrations(message, state, registrations, app=app)


async def handle_cancel_option(response, message: Message, state: FSMContext) -> bool:
    """Helper function to handle cancel option in user interactions"""
    if response == "cancel":
        await send_safe(
            message.chat.id,
            "Регистрация отменена. Если передумаете, используйте /start чтобы начать заново.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return True
    return False


async def register_user(
    message: Message, state: FSMContext, app: App, preselected_city=None, reuse_info=None
):
    """Register a user for an event"""
    assert message.from_user is not None
    user_id = message.from_user.id
    username = message.from_user.username

    # Initialize log messages list for this user if not exists
    if user_id not in log_messages:
        log_messages[user_id] = []

    # Initialize all variables that could be unbound
    full_name = None
    graduation_year = None
    class_letter = None
    location = None
    graduate_type = GraduateType.GRADUATE  # Default type - will be overridden in specific cases

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
    if preselected_city:
        # Use preselected city if provided
        location = next((c for c in TargetCity if c.value == preselected_city), None)

        # Check if event has passed for this city
        if location and is_event_passed(location):
            await send_safe(
                message.chat.id,
                f"К сожалению, встреча в городе {location.value} уже прошла.\n\n"
                "Вы можете:\n"
                "1. Выбрать другой город, если там встреча еще не прошла\n"
                "2. Следить за новостями в группе школы, чтобы не пропустить следующие встречи",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

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
        # Filter out cities the user is already registered for, cities where events have passed, and disabled cities
        available_cities = {
            city.value: f"{city.value} ({date_of_event[city]})"
            for city in TargetCity
            if city.value not in existing_cities
            and not is_event_passed(city)
            and app.is_city_enabled(city.value)
        }
        available_cities["cancel"] = "Отменить регистрацию"  # Add cancel option

        # If no cities left, inform the user
        if not available_cities:
            await send_safe(
                message.chat.id,
                "К сожалению, все встречи уже прошли или вы уже зарегистрированы во всех доступных городах.\n\n"
                "Следите за новостями в группе школы, чтобы не пропустить следующие встречи.",
                reply_markup=ReplyKeyboardRemove(),
            )

            # Log no cities available
            log_msg = await app.log_registration_step(
                user_id,
                username,
                "Нет доступных городов",
                "Пользователь уже зарегистрирован во всех городах или все встречи прошли",
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

        # Handle cancel
        if await handle_cancel_option(response, message, state):
            return

        # Handle timeout/None response
        if response is None:
            await send_safe(
                message.chat.id,
                "⏰ Время ожидания истекло. Пожалуйста, начните регистрацию заново с команды /start",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        location = TargetCity(response)

        # Log city selection
        log_msg = await app.log_registration_step(
            user_id, username, "Выбор города", f"Выбранный город: {location.value}"
        )

        # Also log to event_logs collection
        await app.save_event_log(
            "registration_step",
            {
                "step": "city_selection",
                "city": location.value,
                "available_cities": list(available_cities.keys()),
                "existing_cities": existing_cities,
            },
            user_id,
            username,
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # If we have info to reuse, skip asking for name and class
    if reuse_info:
        full_name = reuse_info["full_name"]
        graduation_year = reuse_info["graduation_year"]
        class_letter = reuse_info["class_letter"]
        graduate_type = GraduateType(reuse_info.get("graduate_type", GraduateType.GRADUATE.value))

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
            choices={
                "yes": "Да, использовать эти данные",
                "no": "Нет, ввести новые данные",
                "cancel": "Отменить регистрацию",
            },
            state=state,
            timeout=None,
        )

        # Handle cancel
        if await handle_cancel_option(confirm, message, state):
            return

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
                Представьтесь, пожалуйста.
                Можно имя и фамилию, можно полные ФИО
                """
            )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # Handle timeout/None response
            if response is None:
                await send_safe(
                    message.chat.id,
                    "⏰ Время ожидания истекло. Пожалуйста, начните регистрацию заново с команды /start",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return

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
                    Например, "2003 Б".
                    
                    <tg-spoiler>Если вы учитель школы 146 (нынешний или бывший), нажмите: /i_am_a_teacher
                    Если вы не выпускник, но друг школы 146 - нажмите: /i_am_a_friend
                    Если вы организатор встречи - нажмите: /i_am_an_organizer</tg-spoiler>
                    """
                )

            response = await ask_user(
                message.chat.id,
                question,
                state=state,
                timeout=None,
            )

            # Handle timeout/None response
            if response is None:
                await send_safe(
                    message.chat.id,
                    "⏰ Время ожидания истекло. Пожалуйста, начните регистрацию заново с команды /start",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return

            # Check for special commands
            if response == "/i_am_a_teacher":
                # User is a teacher
                graduation_year = 0  # Special value for teachers
                class_letter = "Т"  # "Т" for "Учитель"
                graduate_type = GraduateType.TEACHER

                # Log teacher status
                log_msg = await app.log_registration_step(
                    user_id,
                    username,
                    "Статус участника",
                    "Учитель",
                )
                if log_msg:
                    log_messages[user_id].append(log_msg)

                # await send_safe(
                #     message.chat.id,
                #     "Вы зарегистрированы как учитель. Участие для учителей бесплатное.",
                # )
                break

            elif response == "/i_am_a_friend":
                # User is not a graduate
                graduation_year = 2000  # Special value for non-graduates
                class_letter = "Н"  # "Н" for "Не выпускник"
                graduate_type = GraduateType.NON_GRADUATE

                # Log non-graduate status
                log_msg = await app.log_registration_step(
                    user_id,
                    username,
                    "Статус участника",
                    "Не выпускник",
                )
                if log_msg:
                    log_messages[user_id].append(log_msg)

                await send_safe(message.chat.id, "Вы зарегистрированы как друг школы 146!")
                break

            elif response == "/i_am_an_organizer":
                # User wants to be an organizer - trigger validation flow
                await send_safe(
                    message.chat.id, 
                    "Статус организатора требует подтверждения. Ваш запрос будет отправлен администраторам на рассмотрение."
                )
                
                # Trigger the organizer validation handler
                await i_am_organizer_handler(message, state, app)
                
                # Return from registration flow to wait for validation
                return

            # If we already have a year and just need the letter
            elif graduation_year is not None and class_letter is None:
                # Validate just the class letter
                class_letter = response.strip().split()[-1]
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
                    graduate_type = GraduateType.GRADUATE

        # Log graduation info
        log_msg = await app.log_registration_step(
            user_id,
            username,
            "Ввод года выпуска и класса",
            f"Год: {graduation_year}, Класс: {class_letter}",
        )
        if log_msg:
            log_messages[user_id].append(log_msg)

    # Internal validation - log error but don't expose to user
    if not all([full_name, graduation_year is not None, class_letter, location, graduate_type]):
        logger.error(
            f"Registration validation failed - missing required fields: "
            f"full_name={full_name}, "
            f"graduation_year={graduation_year}, "
            f"class_letter={class_letter}, "
            f"location={location}, "
            f"graduate_type={graduate_type}"
        )

    # Save the registration
    await app.save_registered_user(
        RegisteredUser(
            full_name=full_name,
            graduation_year=graduation_year,
            class_letter=class_letter,
            target_city=location,
            graduate_type=graduate_type,
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
        user_id,
        username,
        full_name,
        graduation_year,
        class_letter,
        location.value,
        graduate_type.value,
    )

    # Clear log messages
    await delete_log_messages(user_id)

    # Send confirmation message with payment info in one message
    confirmation_msg = (
        f"Спасибо, {full_name}!\n"
        f"Вы зарегистрированы на встречу выпускников школы 146 "
        f"в {padezhi[location]} {date_of_event[location]}. "
    )

    # Skip payment flow for St. Petersburg, Belgrade, teachers, and organizers
    if location.value == TargetCity.SAINT_PETERSBURG.value:
        # Mark Saint Petersburg registrations as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (Санкт-Петербург)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля встречи в Санкт-Петербурге оплата не требуется. Все расходы участники несут самостоятельно."
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    elif location.value == TargetCity.BELGRADE.value:
        # Mark Belgrade registrations as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (Белград)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля встречи в Белграде оплата не требуется. Все расходы участники несут самостоятельно."
        confirmation_msg += (
            "\n\nПрисоединяйтесь к группе встречи в Telegram: https://t.me/+8-4xPvS-PTcxZTEy"
        )
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    elif graduate_type == GraduateType.TEACHER:
        # Mark teachers as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (учитель)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля учителей участие бесплатное. Спасибо за вашу работу!"
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )

        # Auto-export to sheets after registration with confirmed payment
        await app.export_registered_users_to_google_sheets()
    elif graduate_type == GraduateType.ORGANIZER:
        # Mark organizers as paid automatically
        await app.update_payment_status(
            user_id=user_id,
            city=location.value,
            status="confirmed",
            admin_comment="Автоматически подтверждено (организатор)",
            payment_amount=0,
        )

        confirmation_msg += "\nДля организаторов участие бесплатное. Спасибо за вашу помощь!"
        await send_safe(
            message.chat.id,
            confirmation_msg,
            reply_markup=ReplyKeyboardRemove(),
        )

        # Auto-export to sheets after registration with confirmed payment
        await app.export_registered_users_to_google_sheets()
    else:
        # Regular flow for everyone else who needs to pay

        # Calculate payment amounts first
        regular_amount, discount, discounted_amount, formula_amount = app.calculate_payment_amount(
            location.value, graduation_year, graduate_type.value
        )

        # Save payment info with "not paid" status - different from "pending" which is used after "pay later" click
        await app.save_payment_info(
            user_id=user_id,
            city=location.value,
            discounted_amount=discounted_amount,
            regular_amount=regular_amount,
            formula_amount=formula_amount,
            username=username,
            payment_status="not paid",
        )

        confirmation_msg += "Сейчас пришлем информацию об оплате..."
        await send_safe(message.chat.id, confirmation_msg)

        # Import the process_payment function here to avoid circular imports
        from app.routers.payment import process_payment

        # Store the original user information in the state
        await state.update_data(original_user_id=user_id, original_username=username)

        # Process payment directly
        await process_payment(
            message, state, location.value, graduation_year, graduate_type=graduate_type.value
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


@commands_menu.add_command("cancel_registration", "Отменить регистрацию")
@router.message(Command("cancel_registration"))
async def cancel_registration_handler(message: Message, state: FSMContext, app: App):
    """
    Cancel user registration command handler.
    """
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Log the cancel registration command
    await app.save_event_log(
        "command",
        {
            "command": "/cancel_registration",
            "content": message.text,
            "chat_type": message.chat.type,
        },
        message.from_user.id,
        message.from_user.username,
    )

    user_id = message.from_user.id
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        await send_safe(
            message.chat.id,
            "У вас нет активных регистраций. Используйте /start для регистрации на встречу.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    if len(registrations) == 1:
        # User has only one registration, ask for confirmation
        reg = registrations[0]
        city = reg["target_city"]
        full_name = reg["full_name"]
        city_enum = next((c for c in TargetCity if c.value == city), None)

        confirm_text = dedent(
            f"""
            Вы уверены, что хотите отменить регистрацию на встречу в городе {city}?
            
            ФИО: {full_name}
            Год выпуска: {reg["graduation_year"]}
            Класс: {reg["class_letter"]}
            Город: {city} ({date_of_event[city_enum] if city_enum else "дата неизвестна"})
            """
        )

        response = await ask_user_choice(
            message.chat.id,
            confirm_text,
            choices={"yes": "Да, отменить", "no": "Нет, сохранить"},
            state=state,
            timeout=None,
        )

        if response == "yes":
            # Cancel registration
            await app.delete_user_registration(user_id, city)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                city,
            )

            await send_safe(
                message.chat.id,
                "Ваша регистрация отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await send_safe(
                message.chat.id,
                "Отмена регистрации отменена. Ваша регистрация сохранена.",
                reply_markup=ReplyKeyboardRemove(),
            )
    else:
        # User has multiple registrations, ask which one to cancel
        choices = {}
        for reg in registrations:
            city = reg["target_city"]
            city_enum = next((c for c in TargetCity if c.value == city), None)
            choices[city] = (
                f"{city} ({date_of_event[city_enum] if city_enum else 'дата неизвестна'})"
            )

        choices["all"] = "Отменить все регистрации"
        choices["cancel"] = "Ничего не отменять"

        response = await ask_user_choice(
            message.chat.id,
            "Выберите, какую регистрацию вы хотите отменить:",
            choices=choices,
            state=state,
            timeout=None,
        )

        if response == "cancel":
            await send_safe(
                message.chat.id,
                "Отмена операции. Ваши регистрации сохранены.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        if response == "all":
            # Get user info for logging before deleting
            user_reg = registrations[0]
            full_name = user_reg.get("full_name", "Unknown")

            # Cancel all registrations
            await app.delete_user_registration(user_id)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                None,  # Indicates all cities
            )

            await send_safe(
                message.chat.id,
                "Все ваши регистрации отменены. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            # Cancel specific city registration
            city = response
            reg = next(r for r in registrations if r["target_city"] == city)
            full_name = reg["full_name"]

            # Cancel registration
            await app.delete_user_registration(user_id, city)

            # Log cancellation
            await app.log_registration_canceled(
                user_id,
                message.from_user.username or "",
                full_name,
                city,
            )

            await send_safe(
                message.chat.id,
                f"Ваша регистрация в городе {city} отменена. Если передумаете, используйте /start чтобы зарегистрироваться снова.",
                reply_markup=ReplyKeyboardRemove(),
            )


@commands_menu.add_command("info", "Информация о встречах")
@router.message(Command("info"))
async def info_handler(message: Message, state: FSMContext, app: App):
    """
    Show detailed information about events in all cities
    """
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Log the info command
    await app.save_event_log(
        "command",
        {"command": "/info", "content": message.text, "chat_type": message.chat.type},
        message.from_user.id,
        message.from_user.username,
    )

    # Create info text with details for each city
    info_text = "📅 <b>Информация о встречах выпускников 146</b>\n\n"

    # Check if all events have passed
    all_events_passed = all(is_event_passed(city) for city in TargetCity)
    if all_events_passed:
        info_text += "Все встречи выпускников уже прошли. Спасибо, что были с нами! 🎓\n\n"
        info_text += "Следите за новостями в группе школы, чтобы не пропустить следующие встречи."
        await send_safe(message.chat.id, info_text, parse_mode="HTML")
        return

    for city in TargetCity:
        if not app.is_city_enabled(city.value):
            continue

        info_text += f"<b>🏙️ {city.value}</b>\n"

        if is_event_passed(city):
            info_text += f"📆 Дата: {date_of_event[city]} (встреча уже прошла)\n"
        else:
            info_text += f"📆 Дата: {date_of_event[city]}\n"
            info_text += f"⏰ Время: {time_of_event[city]}\n"
            info_text += f"🏢 Место: {venue_of_event[city]}\n"
            info_text += f"📍 Адрес: {address_of_event[city]}\n"

        info_text += "\n"

    # Add registration command info if there are upcoming events
    if not all_events_passed:
        info_text += "Используйте /start для регистрации на встречу.\n"
        info_text += "Используйте /pay для оплаты участия после регистрации.\n"

    await send_safe(message.chat.id, info_text, parse_mode="HTML")


@commands_menu.add_command("status", "Статус регистрации")
@router.message(Command("status"))
async def status_handler(message: Message, state: FSMContext, app: App):
    """
    Show user registration status
    """
    if message.from_user is None:
        logger.error("Message from_user is None")
        return

    # Log the status command
    await app.save_event_log(
        "command",
        {"command": "/status", "content": message.text, "chat_type": message.chat.type},
        message.from_user.id,
        message.from_user.username,
    )

    user_id = message.from_user.id
    registrations = await app.get_user_registrations(user_id)

    if not registrations:
        # Check if all enabled events have passed
        enabled_cities = [city for city in TargetCity if app.is_city_enabled(city.value)]
        all_enabled_events_passed = all(is_event_passed(city) for city in enabled_cities)
        if all_enabled_events_passed:
            await send_safe(
                message.chat.id,
                "Все встречи выпускников уже прошли. Спасибо, что были с нами! 🎓\n\n"
                "Следите за новостями в группе школы, чтобы не пропустить следующие встречи.",
                reply_markup=ReplyKeyboardRemove(),
            )
        else:
            await send_safe(
                message.chat.id,
                "У вас нет активных регистраций. Используйте /start для регистрации на встречу.",
                reply_markup=ReplyKeyboardRemove(),
            )
        return

    status_text = "📋 Ваши регистрации:\n\n"

    for reg in registrations:
        city = reg["target_city"]
        city_enum = next((c for c in TargetCity if c.value == city), None)
        full_name = reg["full_name"]
        graduate_type = reg.get("graduate_type", GraduateType.GRADUATE.value)

        # Add city and date information
        status_text += f"🏙️ Город: {city}"
        if city_enum and city_enum in date_of_event:
            if is_event_passed(city_enum):
                status_text += f" ({date_of_event[city_enum]} - встреча уже прошла)"
            else:
                status_text += f" ({date_of_event[city_enum]})"
        status_text += "\n"

        # Add personal information
        status_text += f"👤 ФИО: {full_name}\n"

        # Show different info based on graduate type
        if graduate_type == GraduateType.TEACHER.value:
            status_text += "👨‍🏫 Статус: Учитель\n"
        elif graduate_type == GraduateType.NON_GRADUATE.value:
            status_text += "👥 Статус: Не выпускник\n"
        elif graduate_type == GraduateType.ORGANIZER.value:
            status_text += "🛠️ Статус: Организатор\n"
        else:
            status_text += f"🎓 Выпуск: {reg['graduation_year']} {reg['class_letter']}\n"

        # Add payment status
        if city == TargetCity.SAINT_PETERSBURG.value or city == TargetCity.BELGRADE.value:
            status_text += "💰 Оплата: За свой счет\n"
        elif graduate_type == GraduateType.TEACHER.value:
            status_text += "💰 Оплата: Бесплатно (учитель)\n"
        elif graduate_type == GraduateType.ORGANIZER.value:
            status_text += "💰 Оплата: Бесплатно (организатор)\n"
        else:
            payment_status = reg.get("payment_status", "не оплачено")
            status_emoji = (
                "✅"
                if payment_status == "confirmed"
                else "❌" if payment_status == "declined" else "⏳"
            )
            status_text += f"💰 Статус оплаты: {status_emoji} {payment_status}\n"

            # Add payment amount if available
            if "payment_amount" in reg:
                status_text += f"💵 Сумма оплаты: {reg['payment_amount']} руб.\n"
            elif payment_status == "pending" and "discounted_payment_amount" in reg:
                status_text += f"💵 Ожидаемая сумма: {reg['discounted_payment_amount']} руб.\n"

        # Add separator between registrations
        status_text += "\n"

    # Add available commands information
    enabled_cities = [city for city in TargetCity if app.is_city_enabled(city.value)]
    all_enabled_events_passed = all(is_event_passed(city) for city in enabled_cities)
    if not all_enabled_events_passed:
        status_text += "Доступные команды:\n"
        status_text += "- /info - подробная информация о встречах (дата, время, адрес)\n"
        status_text += "- /start - управление регистрациями\n"
        status_text += "- /pay - оплатить участие\n"
        status_text += "- /cancel_registration - отменить регистрацию\n"
    else:
        status_text += "Все встречи уже прошли. Спасибо, что были с нами! 🎓\n\n"
        status_text += "Следите за новостями в группе школы, чтобы не пропустить следующие встречи."

    await send_safe(message.chat.id, status_text, reply_markup=ReplyKeyboardRemove())


@commands_menu.add_command("start", "Start the bot")
@router.message(CommandStart())
@router.message(
    F.text, F.chat.type == "private", ~F.text.startswith("/")
)  # only handle private messages that are not commands
async def start_handler(message: Message, state: FSMContext, app: App):
    """
    Main scenario flow.
    """
    assert message.from_user is not None
    # Log the start command
    if message.from_user:
        await app.save_event_log(
            "command",
            {"command": "/start", "content": message.text, "chat_type": message.chat.type},
            message.from_user.id,
            message.from_user.username,
        )

    if is_admin(message.from_user):
        result = await admin_handler(message, state, app=app)
        if result != "register":
            return

    # Check if any enabled events are available
    enabled_cities = [city for city in TargetCity if app.is_city_enabled(city.value)]
    if not enabled_cities:
        await send_safe(
            message.chat.id,
            "В данный момент нет доступных встреч для регистрации. Следите за новостями в группе школы.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Check if all enabled events have passed
    all_enabled_events_passed = all(is_event_passed(city) for city in enabled_cities)
    if all_enabled_events_passed:
        await send_safe(
            message.chat.id,
            "Все встречи выпускников уже прошли. Спасибо, что были с нами! 🎓\n\n"
            "Следите за новостями в группе школы, чтобы не пропустить следующие встречи.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Check if user is already registered for any enabled event
    existing_registration = await app.get_user_registration(message.from_user.id)
    existing_enabled_registration = None
    
    if existing_registration:
        # Check if user has registration for any enabled event
        user_registrations = await app.get_user_registrations(message.from_user.id)
        existing_enabled_registration = next(
            (reg for reg in user_registrations 
             if app.is_city_enabled(reg.get("target_city"))),
            None
        )

    if existing_enabled_registration:
        # User is already registered for an enabled event, show options
        await handle_registered_user(message, state, existing_enabled_registration, app)
    else:
        # New user or user not registered for any enabled event
        # Get the first available enabled city
        available_city = next((city for city in enabled_cities if not is_event_passed(city)), None)
        
        if not available_city:
            await send_safe(
                message.chat.id,
                "К сожалению, все доступные встречи уже прошли. Следите за новостями в группе школы.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        
        # Show information about the available event
        event_info = f"""
👋 Добро пожаловать!

В ближайшее время клуб друзей школы 146 проводит встречу:

📅 Дата: {date_of_event[available_city]}
⏰ Время: {time_of_event[available_city]}
📍 Место: {venue_of_event[available_city]}
🗺️ Адрес: {address_of_event[available_city]}

Хотите зарегистрироваться на эту встречу?
        """
        
        # Ask user if they want to register
        response = await ask_user_choice(
            message.chat.id,
            event_info.strip(),
            choices={
                "yes": "Да, зарегистрироваться",
                "cancel": "Отмена"
            },
            state=state,
            timeout=None,
        )
        
        if response == "cancel" or response is None:
            await send_safe(
                message.chat.id,
                "Регистрация отменена. Если передумаете, просто напишите боту снова!",
                reply_markup=ReplyKeyboardRemove(),
            )
            return
        
        # User wants to register, proceed with registration
        reuse_info = existing_registration if existing_registration else None
        await register_user(message, state, app, 
                          preselected_city=available_city.value, 
                          reuse_info=reuse_info)


# Define organizer validation states
class OrganizerValidationStates(StatesGroup):
    waiting_for_decline_reason = State()


@commands_menu.add_command("i_am_organizer", "Я организатор")
@router.message(Command("i_am_organizer"))
@router.message(Command("i_am_an_organizer"))
async def i_am_organizer_handler(message: Message, state: FSMContext, app: App):
    """Handle organizer validation request"""
    if message.from_user is None:
        logger.error("Message from_user is None")
        return
        
    user_id = message.from_user.id
    username = message.from_user.username or ""
    
    # Log the organizer validation request
    await app.save_event_log(
        "command", 
        {
            "command": "/i_am_organizer",
            "content": message.text,
            "chat_type": message.chat.type
        }, 
        user_id, 
        username
    )
    
    # Get user's existing registration info if available
    user_registration = await app.get_user_registration(user_id)
    user_info = f"👤 Пользователь: {username or ''} (ID: {user_id})\n"
    
    if user_registration:
        user_info += f"👤 ФИО: {user_registration.get('full_name', 'Неизвестно')}\n"
        user_info += f"📍 Город: {user_registration.get('target_city', 'Неизвестно')}\n"
        current_graduate_type = user_registration.get("graduate_type", GraduateType.GRADUATE.value)
        if current_graduate_type == GraduateType.GRADUATE.value:
            user_info += f"🎓 Выпуск: {user_registration.get('graduation_year', 'Неизвестно')} {user_registration.get('class_letter', '')}\n"
        elif current_graduate_type == GraduateType.TEACHER.value:
            user_info += f"👨‍🏫 Текущий статус: Учитель\n"
        elif current_graduate_type == GraduateType.NON_GRADUATE.value:
            user_info += f"👥 Текущий статус: Друг школы\n"
        elif current_graduate_type == GraduateType.ORGANIZER.value:
            user_info += f"🛠️ Текущий статус: Организатор\n"
    else:
        user_info += "ℹ️ Пользователь еще не зарегистрирован\n"
    
    user_info += "\n🛠️ Запрос на статус организатора"
    
    try:
        # Get events chat ID from settings
        events_chat_id = app.settings.events_chat_id
        logger.info(f"Sending organizer validation request to events chat ID: {events_chat_id}")
        
        # Create validation buttons
        validation_buttons = [
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить статус организатора",
                    callback_data=f"confirm_organizer_{user_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отклонить",
                    callback_data=f"decline_organizer_{user_id}",
                )
            ]
        ]
        
        validation_markup = InlineKeyboardMarkup(inline_keyboard=validation_buttons)
        
        # Get bot instance
        from botspot.core.dependency_manager import get_dependency_manager
        deps = get_dependency_manager()
        bot = deps.bot
        
        # Send validation request to events chat
        validation_msg = await bot.send_message(
            chat_id=events_chat_id,
            text=user_info,
            reply_markup=validation_markup,
        )
        
        logger.info(f"Organizer validation request from user {user_id} sent to validation chat")
        
        # Notify user that request was sent
        await send_safe(
            message.chat.id,
            "Ваш запрос на статус организатора отправлен на рассмотрение. "
            "Мы уведомим вас о результате проверки.",
            reply_markup=ReplyKeyboardRemove(),
        )
        
    except Exception as e:
        logger.error(f"Error sending organizer validation request to validation chat: {e}")
        await send_safe(
            message.chat.id,
            "Произошла ошибка при отправке запроса. Пожалуйста, попробуйте позже.",
            reply_markup=ReplyKeyboardRemove(),
        )


# Add callback handlers for organizer confirmation/decline buttons
@router.callback_query(lambda c: c.data and c.data.startswith("confirm_organizer_"))
async def confirm_organizer_callback(callback_query: CallbackQuery, state: FSMContext, app: App):
    """Confirm organizer status"""
    # Check if any state is set (meaning some operation is in progress)
    current_state = await state.get_state()
    if current_state is not None:
        # If any operation is in progress, ignore this callback
        await callback_query.answer("Дождитесь завершения текущей операции...")
        return
    
    # Extract user_id from callback data
    try:
        user_id_str = callback_query.data.replace("confirm_organizer_", "")
        user_id = int(user_id_str)
    except ValueError as e:
        await callback_query.answer(f"Invalid callback data: {e}")
        return
    
    # Get user registration info
    user_registration = await app.get_user_registration(user_id)
    if user_registration:
        username = user_registration.get("username", str(user_id))
        full_name = user_registration.get("full_name", "Неизвестно")
        
        # Update the user's graduate_type to ORGANIZER
        await app.update_user_graduate_type(user_id, GraduateType.ORGANIZER.value)
        
        # If user is registered for events that require payment, mark them as paid
        user_registrations = await app.get_user_registrations(user_id)
        for reg in user_registrations:
            city = reg["target_city"]
            # Skip cities that don't require payment
            if city in [TargetCity.SAINT_PETERSBURG.value, TargetCity.BELGRADE.value]:
                continue
                
            # Update payment status to confirmed for organizers
            await app.update_payment_status(
                user_id=user_id,
                city=city,
                status="confirmed",
                admin_comment="Автоматически подтверждено (организатор)",
                payment_amount=0,
            )
        
        # Notify user
        await send_safe(
            user_id,
            "✅ Ваш статус организатора подтвержден! "
            "Участие для организаторов бесплатное. Спасибо за вашу помощь в организации встреч!",
        )
        
        # Log the confirmation
        await app.save_event_log(
            "organizer_validation", 
            {
                "action": "confirmed",
                "user_id": user_id,
                "username": username,
                "full_name": full_name
            }, 
            user_id, 
            username
        )
        
    else:
        # User doesn't have registration yet, create a record for organizer status
        await send_safe(
            user_id,
            "✅ Ваш статус организатора подтвержден! "
            "При регистрации на встречи участие будет бесплатным. "
            "Спасибо за вашу помощь в организации встреч!",
        )
        
        # Log the confirmation without registration
        await app.save_event_log(
            "organizer_validation", 
            {
                "action": "confirmed", 
                "user_id": user_id,
                "note": "User confirmed as organizer without existing registration"
            }, 
            user_id, 
            ""
        )
    
    # Update callback message
    if callback_query.message:
        try:
            user_info = callback_query.message.text or ""
            new_text = f"{user_info}\n\n✅ СТАТУС ОРГАНИЗАТОРА ПОДТВЕРЖДЕН"
            
            await callback_query.message.edit_text(text=new_text, reply_markup=None)
        except Exception as e:
            logger.error(f"Error updating callback message: {e}")
    
    # Confirm to admin
    await callback_query.answer("Статус организатора подтвержден")
    
    # Auto-export to sheets after confirmation
    await app.export_registered_users_to_google_sheets()


@router.callback_query(lambda c: c.data and c.data.startswith("decline_organizer_"))
async def decline_organizer_callback(callback_query: CallbackQuery, state: FSMContext, app: App):
    """Ask for decline reason for organizer status"""
    # Check if any state is set (meaning some operation is in progress)
    current_state = await state.get_state()
    if current_state is not None:
        # If any operation is in progress, ignore this callback
        await callback_query.answer("Дождитесь завершения текущей операции...")
        return
    
    # Extract user_id from callback data
    try:
        user_id_str = callback_query.data.replace("decline_organizer_", "")
        user_id = int(user_id_str)
    except ValueError as e:
        await callback_query.answer(f"Invalid callback data: {e}")
        return
    
    # Save data for the next step
    await state.set_state(OrganizerValidationStates.waiting_for_decline_reason)
    await state.update_data(
        decline_user_id=user_id, callback_message=callback_query.message
    )
    
    # Ask for decline reason by editing the original message
    if callback_query.message:
        try:
            user_info = callback_query.message.text or ""
            new_text = f"{user_info}\n\n⚠️ Укажите причину отклонения запроса организатора в ответном сообщении:"
            
            await callback_query.message.edit_text(text=new_text, reply_markup=None)
        except Exception as e:
            logger.error(f"Error updating callback message: {e}")
    else:
        # Fallback if message is not available
        await callback_query.answer("Укажите причину отклонения в следующем сообщении")


@router.message(OrganizerValidationStates.waiting_for_decline_reason)
async def organizer_decline_reason_handler(message: Message, state: FSMContext, app: App):
    """Handle organizer status decline reason"""
    # Check if user is admin
    if not is_admin(message.from_user):
        return
    
    # Get data from state
    data = await state.get_data()
    user_id = data.get("decline_user_id")
    callback_message = data.get("callback_message")
    
    if not user_id:
        await message.reply("Ошибка: не найдена информация о запросе организатора")
        await state.clear()
        return
    
    # Get decline reason
    decline_reason = message.text or "Причина не указана"
    
    # Get user info for logging
    user_registration = await app.get_user_registration(user_id)
    username = user_registration.get("username", str(user_id)) if user_registration else ""
    full_name = user_registration.get("full_name", "Неизвестно") if user_registration else "Неизвестно"
    
    # Notify user
    await send_safe(
        user_id,
        f"❌ Ваш запрос на статус организатора отклонен.\n\n"
        f"Причина: {decline_reason}\n\n"
        f"Если у вас есть вопросы по этому решению, обратитесь к администраторам.",
    )
    
    # Log the decline
    await app.save_event_log(
        "organizer_validation", 
        {
            "action": "declined",
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "decline_reason": decline_reason
        }, 
        user_id, 
        username
    )
    
    # Update the original callback message if available
    if callback_message:
        try:
            user_info = callback_message.text or ""
            # Remove the prompt if it exists
            user_info = user_info.split("\n\n⚠️ Укажите причину")[0]
            new_text = f"{user_info}\n\n❌ ЗАПРОС ОРГАНИЗАТОРА ОТКЛОНЕН\nПричина: {decline_reason}"
            
            await callback_message.edit_text(text=new_text, reply_markup=None)
        except Exception as e:
            logger.error(f"Error updating callback message: {e}")
    
    # Confirm to admin with a brief reply
    await message.reply(f"❌ Запрос организатора отклонен")
    
    # Clear state
    await state.clear()
